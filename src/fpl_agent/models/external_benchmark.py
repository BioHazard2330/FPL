"""Independent-model benchmark against Solio Analytics (direct user ask,
2026-08-27: "make our optimizer more trustworthy now, without waiting for
4-5 additional gameweeks"). A comparison layer, not a correction layer -
same rule-based, never-average posture `models/decision_fusion.py` already
established for MODEL vs QUALITATIVE vs USER views, extended here to a
fourth, independently-sourced view: an external model. A divergence is
surfaced for investigation, never auto-applied as a correction to our own
projection - see this module's own `classify_divergence` and the CLI/
dashboard callers for the enforced boundary.

Real, disclosed scope limit: Solio publishes top-N lists per category
(~60 distinct players this GW, `ingestion/solio_source.py`), not a full
~600-player universe - every comparison in this module is therefore only
ever computed over the real intersection of "a player Solio chose to
publish AND we could resolve to our own player_id", honestly reported as
`compared_count`/`solio_universe_size`, never silently extrapolated to
players Solio didn't rank.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.models.expected_points import ComponentBreakdown, expected_points, team_next_fixture_projection

# Relative-difference bands (Solio value vs our value, signed). Disclosed,
# not backtest-fit - no completed season yet to calibrate a "real" outlier
# rate against, same honesty posture as every other undisclosed-provenance
# threshold in this project (differentials.py's ownership bands, traps.py's
# minutes threshold). Revisit once real GW outcomes accumulate.
_MINOR_REL = 0.10
_MATERIAL_REL = 0.25
_MAJOR_REL = 0.50
# Below this absolute points floor on BOTH sides, a relative-difference band
# is meaningless (e.g. 0.1 vs 0.2 pts is a 100% relative diff over nothing) -
# always AGREEMENT regardless of the relative-diff bands above.
_ABS_FLOOR = 0.75

CLASSIFICATIONS = ("AGREEMENT", "MINOR_DIVERGENCE", "MATERIAL_DIVERGENCE", "MAJOR_OUTLIER")


def classify_divergence(our_value: float, external_value: float) -> str:
    absolute_diff = external_value - our_value
    if abs(our_value) < _ABS_FLOOR and abs(external_value) < _ABS_FLOOR:
        return "AGREEMENT"
    denom = abs(our_value) if abs(our_value) >= _ABS_FLOOR else _ABS_FLOOR
    relative_diff = absolute_diff / denom
    magnitude = abs(relative_diff)
    if magnitude < _MINOR_REL:
        return "AGREEMENT"
    if magnitude < _MATERIAL_REL:
        return "MINOR_DIVERGENCE"
    if magnitude < _MAJOR_REL:
        return "MATERIAL_DIVERGENCE"
    return "MAJOR_OUTLIER"


@dataclass(frozen=True)
class SolioSnapshotInfo:
    snapshot_id: int
    gameweek: int
    generated_at: str
    retrieved_at: str
    deadline_iso: str | None
    age_hours: float


def latest_solio_snapshot(conn: sqlite3.Connection) -> SolioSnapshotInfo | None:
    row = conn.execute(
        "SELECT id, gameweek, generated_at, retrieved_at, deadline_iso FROM solio_snapshot "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    retrieved = datetime.fromisoformat(row["retrieved_at"])
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - retrieved).total_seconds() / 3600
    return SolioSnapshotInfo(
        snapshot_id=row["id"], gameweek=row["gameweek"], generated_at=row["generated_at"],
        retrieved_at=row["retrieved_at"], deadline_iso=row["deadline_iso"], age_hours=round(age_hours, 2),
    )


@dataclass(frozen=True)
class ComponentComparison:
    component: str
    our_points: float
    solio_points: float | None  # None when Solio doesn't publish this component at all

    @property
    def diff(self) -> float | None:
        return None if self.solio_points is None else self.solio_points - self.our_points


def compare_components(our: ComponentBreakdown, solio_row) -> tuple[list[ComponentComparison], str | None]:
    """Maps our real per-component decomposition onto Solio's own published
    sub-components (goals/assists/bonus/DefCon) where Solio publishes one,
    and groups everything Solio does NOT break out (appearance, clean sheet,
    cards, goals-conceded penalty) into a single 'other' bucket compared
    against Solio's own implied residual (its total minus whatever it did
    publish) - the only honest way to compare a component Solio doesn't
    itemize, rather than inventing a per-field Solio number that doesn't
    exist. Returns (comparisons, largest_driver) - `largest_driver` is the
    component with the largest absolute diff among ones Solio actually
    publishes a real number for (never picked from the 'other' bucket,
    which is a residual, not a real like-for-like Solio figure)."""
    our_other = our.appearance + our.clean_sheet + our.cards + our.conceded
    solio_published_sum = sum(
        v for v in (solio_row["pr_points_from_goals"], solio_row["pr_points_from_assists"],
                     solio_row["pr_bonus_points"], solio_row["pr_defcon_points"]) if v is not None
    )
    solio_other = solio_row["pr_points"] - solio_published_sum if solio_row["pr_points"] is not None else None

    comparisons = [
        ComponentComparison("goals", our.goals, solio_row["pr_points_from_goals"]),
        ComponentComparison("assists", our.assists, solio_row["pr_points_from_assists"]),
        ComponentComparison("bonus", our.bonus, solio_row["pr_bonus_points"]),
        ComponentComparison("defcon", our.defcon, solio_row["pr_defcon_points"]),
        ComponentComparison("other (appearance/CS/cards/conceded)", our_other, solio_other),
    ]

    real_diffs = [(c.component, c.diff) for c in comparisons[:4] if c.diff is not None]
    largest_driver = max(real_diffs, key=lambda pair: abs(pair[1]))[0] if real_diffs else None
    return comparisons, largest_driver


@dataclass(frozen=True)
class PlayerBenchmarkComparison:
    player_id: int
    web_name: str
    our_median: float
    solio_pr_points: float
    absolute_diff: float
    relative_diff: float
    classification: str
    our_rank: int | None
    solio_rank: int | None
    rank_diff: int | None
    component_comparisons: list[ComponentComparison]
    largest_driver: str | None
    solio_categories: tuple[str, ...]


def _solio_player_row(conn: sqlite3.Connection, snapshot_id: int, player_id: int):
    return conn.execute(
        "SELECT * FROM solio_player_projection WHERE snapshot_id=? AND player_id=?",
        (snapshot_id, player_id),
    ).fetchone()


def compare_player(conn: sqlite3.Connection, player_id: int, snapshot: SolioSnapshotInfo, n_gw: int = 1
                    ) -> PlayerBenchmarkComparison | None:
    """Single-player comparison, real EV pulled from our own `expected_points()`
    (never a re-derived number) against the matching Solio row for the given
    snapshot. `None` when Solio never published this player this GW (not a
    real divergence - an absent observation, per this project's no-fabrication
    rule)."""
    solio_row = _solio_player_row(conn, snapshot.snapshot_id, player_id)
    if solio_row is None or solio_row["pr_points"] is None:
        return None

    ep = expected_points(conn, player_id, n_gw=n_gw)
    web_name = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()["web_name"]

    absolute_diff = solio_row["pr_points"] - ep.median
    denom = max(abs(ep.median), _ABS_FLOOR)
    relative_diff = absolute_diff / denom
    classification = classify_divergence(ep.median, solio_row["pr_points"])

    comparisons, largest_driver = ([], None)
    if ep.components is not None:
        comparisons, largest_driver = compare_components(ep.components, solio_row)

    return PlayerBenchmarkComparison(
        player_id=player_id, web_name=web_name, our_median=ep.median, solio_pr_points=solio_row["pr_points"],
        absolute_diff=round(absolute_diff, 2), relative_diff=round(relative_diff, 3), classification=classification,
        our_rank=None, solio_rank=None, rank_diff=None,
        component_comparisons=comparisons, largest_driver=largest_driver,
        solio_categories=tuple((solio_row["categories"] or "").split(",")),
    )


def compare_all_matched_players(conn: sqlite3.Connection, snapshot: SolioSnapshotInfo | None = None, n_gw: int = 1
                                 ) -> list[PlayerBenchmarkComparison]:
    """Every player Solio published AND we could resolve a player_id for, in
    this snapshot - the real, disclosed comparable universe (see module
    docstring). Ranks are computed WITHIN this set only (our_rank = this
    player's position sorting the set by our own median desc; solio_rank the
    same sorting by Solio's prPoints desc) - a rank-1 here means "top of the
    ~60 players Solio chose to publish", not "top of the full player pool"."""
    snapshot = snapshot or latest_solio_snapshot(conn)
    if snapshot is None:
        return []

    player_ids = [
        r["player_id"] for r in conn.execute(
            "SELECT player_id FROM solio_player_projection WHERE snapshot_id=? AND player_id IS NOT NULL",
            (snapshot.snapshot_id,),
        ).fetchall()
    ]
    comparisons = [c for pid in player_ids if (c := compare_player(conn, pid, snapshot, n_gw=n_gw)) is not None]

    by_our = sorted(comparisons, key=lambda c: c.our_median, reverse=True)
    our_rank_of = {c.player_id: i + 1 for i, c in enumerate(by_our)}
    by_solio = sorted(comparisons, key=lambda c: c.solio_pr_points, reverse=True)
    solio_rank_of = {c.player_id: i + 1 for i, c in enumerate(by_solio)}

    result = []
    for c in comparisons:
        our_rank, solio_rank = our_rank_of[c.player_id], solio_rank_of[c.player_id]
        result.append(
            PlayerBenchmarkComparison(
                **{**c.__dict__, "our_rank": our_rank, "solio_rank": solio_rank, "rank_diff": solio_rank - our_rank}
            )
        )
    return result


def top_divergences(
    conn: sqlite3.Connection, n: int = 10, min_classification: str = "MATERIAL_DIVERGENCE",
    snapshot: SolioSnapshotInfo | None = None,
) -> list[PlayerBenchmarkComparison]:
    min_rank = CLASSIFICATIONS.index(min_classification)
    comparisons = compare_all_matched_players(conn, snapshot=snapshot)
    filtered = [c for c in comparisons if CLASSIFICATIONS.index(c.classification) >= min_rank]
    filtered.sort(key=lambda c: abs(c.absolute_diff), reverse=True)
    return filtered[:n]


@dataclass(frozen=True)
class TeamBenchmarkComparison:
    team_id: int
    team_name: str
    our_cs_prob: float
    solio_cs_prob: float | None
    our_goals_for: float
    solio_goals_for: float | None
    classification: str  # over CS prob (points-scale relative-diff bands don't apply well to a 0-1 probability)


_CS_PROB_MINOR = 0.10
_CS_PROB_MATERIAL = 0.20


def _classify_prob_divergence(our_prob: float, solio_prob: float) -> str:
    diff = abs(solio_prob - our_prob)
    if diff < _CS_PROB_MINOR:
        return "AGREEMENT"
    if diff < _CS_PROB_MATERIAL:
        return "MINOR_DIVERGENCE"
    return "MATERIAL_DIVERGENCE"


def compare_team_outlooks(conn: sqlite3.Connection, snapshot: SolioSnapshotInfo | None = None
                           ) -> list[TeamBenchmarkComparison]:
    """Team-level clean-sheet/goals-for benchmark - our own
    `team_next_fixture_projection` (the same odds-blended DC numbers every
    player's `expected_points()` already uses) vs Solio's `bestCleanSheets`/
    `bestAttackingFixtures` team rows. Only covers teams Solio published (its
    own top-10-per-list cut, not the full 20)."""
    snapshot = snapshot or latest_solio_snapshot(conn)
    if snapshot is None:
        return []
    rows = conn.execute(
        "SELECT * FROM solio_team_projection WHERE snapshot_id=? AND team_id IS NOT NULL", (snapshot.snapshot_id,)
    ).fetchall()
    results = []
    for row in rows:
        proj = team_next_fixture_projection(conn, row["team_id"])
        if proj is None:
            continue
        classification = (
            _classify_prob_divergence(proj.cs_prob, row["cs_prob"]) if row["cs_prob"] is not None else "AGREEMENT"
        )
        results.append(TeamBenchmarkComparison(
            team_id=row["team_id"], team_name=row["team_name"], our_cs_prob=round(proj.cs_prob, 3),
            solio_cs_prob=row["cs_prob"], our_goals_for=round(proj.goals_for, 2), solio_goals_for=row["pr_goals_for"],
            classification=classification,
        ))
    return results


@dataclass(frozen=True)
class CaptainBenchmarkComparison:
    our_pick_id: int | None
    our_pick_name: str | None
    our_captain_points: float | None  # our median * 2 (captaincy doubles), for a like-for-like compare
    solio_pick_name: str | None
    solio_captain_points: float | None
    verdict: str  # AGREEMENT / DIVERGENCE / INSUFFICIENT_EVIDENCE
    why: str


def compare_captain_pick(conn: sqlite3.Connection, squad_ids: list[int], snapshot: SolioSnapshotInfo | None = None
                          ) -> CaptainBenchmarkComparison:
    """Cross-checks OUR authoritative captain pick (`optimization.captaincy.
    evaluate_captaincy`'s own top option - never re-derived) against Solio's
    own `topCaptains[0]`. A disagreement is surfaced, never auto-applied -
    the real decision-analysis layer is untouched by this function; callers
    fold this into the existing decision-fusion display, not into the
    decision itself (spec's own "recommend, never act on a divergence
    automatically" constraint)."""
    from fpl_agent.optimization.captaincy import evaluate_captaincy

    snapshot = snapshot or latest_solio_snapshot(conn)
    options = evaluate_captaincy(conn, sorted(squad_ids))
    our_pick = options[0] if options else None

    if snapshot is None or our_pick is None:
        return CaptainBenchmarkComparison(
            our_pick_id=our_pick.player_id if our_pick else None,
            our_pick_name=our_pick.web_name if our_pick else None,
            our_captain_points=round(our_pick.median * 2, 2) if our_pick else None,
            solio_pick_name=None, solio_captain_points=None,
            verdict="INSUFFICIENT_EVIDENCE",
            why="no Solio snapshot available yet" if snapshot is None else "no real captaincy data for this squad",
        )

    solio_top_row = conn.execute(
        "SELECT source_name, player_id, captain_proj_points FROM solio_player_projection "
        "WHERE snapshot_id=? AND captain_proj_points IS NOT NULL ORDER BY captain_proj_points DESC LIMIT 1",
        (snapshot.snapshot_id,),
    ).fetchone()

    our_captain_points = round(our_pick.median * 2, 2)
    if solio_top_row is None:
        return CaptainBenchmarkComparison(
            our_pick_id=our_pick.player_id, our_pick_name=our_pick.web_name,
            our_captain_points=our_captain_points, solio_pick_name=None, solio_captain_points=None,
            verdict="INSUFFICIENT_EVIDENCE", why="Solio published no captain list this snapshot",
        )

    same_player = solio_top_row["player_id"] == our_pick.player_id
    verdict = "AGREEMENT" if same_player else "DIVERGENCE"
    why = (
        f"both models pick {our_pick.web_name}"
        if same_player else
        f"our model picks {our_pick.web_name} ({our_captain_points} pts), Solio's own top captain is "
        f"{solio_top_row['source_name']} ({solio_top_row['captain_proj_points']:.2f} pts) - our decision layer is unchanged"
    )
    return CaptainBenchmarkComparison(
        our_pick_id=our_pick.player_id, our_pick_name=our_pick.web_name, our_captain_points=our_captain_points,
        solio_pick_name=solio_top_row["source_name"], solio_captain_points=solio_top_row["captain_proj_points"],
        verdict=verdict, why=why,
    )


@dataclass(frozen=True)
class TransferTargetBenchmarkComparison:
    our_target_id: int | None
    our_target_name: str | None
    solio_top_differential_name: str | None
    solio_top_transfer_in_name: str | None
    verdict: str  # AGREEMENT / DIVERGENCE / INSUFFICIENT_EVIDENCE
    why: str


def compare_transfer_target(
    conn: sqlite3.Connection, our_target_player_id: int | None, our_target_name: str | None,
    snapshot: SolioSnapshotInfo | None = None,
) -> TransferTargetBenchmarkComparison:
    """`our_target_player_id`/`our_target_name` come from the caller's
    already-computed `analyze_transfer_decision` result (or
    `compare_starting_actions`'s current recommendation) - this function
    never re-derives a transfer target of its own, it only cross-references
    against Solio's own `topDifferentials`/`topTransfersIn`."""
    snapshot = snapshot or latest_solio_snapshot(conn)
    if snapshot is None or our_target_player_id is None:
        return TransferTargetBenchmarkComparison(
            our_target_id=our_target_player_id, our_target_name=our_target_name,
            solio_top_differential_name=None, solio_top_transfer_in_name=None,
            verdict="INSUFFICIENT_EVIDENCE",
            why="no Solio snapshot available yet" if snapshot is None else "no current transfer target to compare",
        )

    solio_row = _solio_player_row(conn, snapshot.snapshot_id, our_target_player_id)
    top_differential = conn.execute(
        "SELECT source_name FROM solio_player_projection WHERE snapshot_id=? AND leverage IS NOT NULL "
        "ORDER BY leverage DESC LIMIT 1", (snapshot.snapshot_id,),
    ).fetchone()
    top_transfer_in = conn.execute(
        "SELECT source_name FROM solio_player_projection WHERE snapshot_id=? AND transfers_in IS NOT NULL "
        "ORDER BY transfers_in DESC LIMIT 1", (snapshot.snapshot_id,),
    ).fetchone()

    if solio_row is not None:
        verdict = "AGREEMENT"
        why = f"Solio also projects {our_target_name} among its {', '.join((solio_row['categories'] or '').split(','))} lists"
    else:
        verdict = "DIVERGENCE"
        why = f"Solio's own top lists don't feature {our_target_name} this snapshot - not itself a reason to change the pick, evidence only"

    return TransferTargetBenchmarkComparison(
        our_target_id=our_target_player_id, our_target_name=our_target_name,
        solio_top_differential_name=top_differential["source_name"] if top_differential else None,
        solio_top_transfer_in_name=top_transfer_in["source_name"] if top_transfer_in else None,
        verdict=verdict, why=why,
    )
