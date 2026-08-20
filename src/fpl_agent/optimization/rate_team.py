"""Rate My Team (competitor-scope closure, 2026-08-20). FPL Copilot and
Fantasy Football Hub both offer a tool that scores an EXISTING squad - not
one this project built via `optimise_squad` from scratch, but any 15 ids a
manager already picked (their own real team, or one drafted elsewhere).
Closes that gap using 100% already-built, already-tested machinery
(build_player_pool, pick_starting_xi, optimise_squad, captaincy_report,
differentials/traps/breakouts/template) - no new modelling, just a new
composition of it.

`efficiency_percent` is a real, non-fabricated score: this squad's real GW1
xP (11 starters + captain bonus, the same corrected formula `fpl build-team`
uses) as a percentage of the best achievable squad's xP under the same full
budget - not an arbitrary 0-100 "rating" invented for the occasion.
"""
import sqlite3
from collections import Counter
from dataclasses import dataclass, field

from fpl_agent.models.availability import list_availability
from fpl_agent.models.breakouts import find_breakouts
from fpl_agent.models.differentials import find_differentials
from fpl_agent.models.expected_points import expected_points_window
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.models.template import get_template
from fpl_agent.models.traps import find_traps
from fpl_agent.optimization.captaincy import CaptainOption, captaincy_report
from fpl_agent.optimization.squad import PlayerCandidate, StartingXI, build_player_pool, optimise_squad, pick_starting_xi


def _xi_total(xi: StartingXI, captain: CaptainOption | None) -> float:
    """Same corrected formula fpl build-team uses: 11 starters + one extra
    copy of the captain's median (real FPL scoring doubles the armband) -
    not a plain sum over the full 15-man squad (which understates the real
    total and was itself a bug fixed earlier this session)."""
    total = sum(c.median for c in xi.starting)
    if captain is not None:
        total += captain.median
    return round(total, 2)


@dataclass(frozen=True)
class SquadRating:
    squad_ids: list[int]
    invalid_ids: list[int]  # ids that aren't real/synced players - never silently dropped
    duplicate_ids: list[int]  # ids repeated in the input - a real squad can never own the same player twice
    total_cost_tenths: int
    bank_tenths: int
    xi: StartingXI
    captain: CaptainOption | None
    vice: CaptainOption | None
    gw1_xp: float
    five_gw_xp: float
    optimal_gw1_xp: float
    efficiency_percent: float
    template_count: int
    differential_ids: list[int] = field(default_factory=list)
    trap_ids: list[int] = field(default_factory=list)
    breakout_ids: list[int] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    rule_violations: list[str] = field(default_factory=list)


def _check_squad_legality(conn: sqlite3.Connection, candidates: list[PlayerCandidate], season: str | None) -> list[str]:
    """Real FPL squad-construction rules (position counts + club limit) -
    flags a violation rather than silently rating an illegal squad as if it
    were submittable."""
    violations = []
    club_limit = get_rule(conn, season, "rules.squad_team_limit", 3)
    position_requirements = {
        r["singular_name_short"]: r["squad_select"]
        for r in conn.execute("SELECT singular_name_short, squad_select FROM element_types").fetchall()
    }
    pos_counts = Counter(c.position for c in candidates)
    for position, required in position_requirements.items():
        actual = pos_counts.get(position, 0)
        if actual != required:
            violations.append(f"{position}: {actual} selected, {required} required")

    club_counts = Counter(c.team_short for c in candidates)
    for club, count in club_counts.items():
        if count > club_limit:
            violations.append(f"{club}: {count} players selected, max {club_limit} allowed")

    return violations


def rate_team(conn: sqlite3.Connection, squad_ids: list[int]) -> SquadRating:
    """A real FPL squad can never own the same player twice - duplicate ids
    in `squad_ids` (a plausible manual-entry typo, e.g. pasting a wrong id
    twice) are deduplicated before rating rather than silently counted as
    two separate squad members (which previously produced a genuinely
    nonsensical output: the same player listed twice in the XI and standing
    as both captain and vice-captain of himself - confirmed live)."""
    season = current_season(conn)
    budget_tenths = get_rule(conn, season, "rules.squad_total_spend", 1000)

    seen: set[int] = set()
    duplicate_ids: list[int] = []
    deduped_ids: list[int] = []
    for pid in squad_ids:
        if pid in seen:
            duplicate_ids.append(pid)
        else:
            seen.add(pid)
            deduped_ids.append(pid)

    pool = build_player_pool(conn, n_gw=1)
    by_id = {c.player_id: c for c in pool}
    squad_candidates = [by_id[pid] for pid in deduped_ids if pid in by_id]
    invalid_ids = [pid for pid in deduped_ids if pid not in by_id]

    xi = pick_starting_xi(conn, squad_candidates) if squad_candidates else StartingXI(starting=[], bench=[])
    cap_report = captaincy_report(conn, [c.player_id for c in squad_candidates]) if squad_candidates else None
    captain = cap_report.best if cap_report else None
    vice = cap_report.second if cap_report else None

    gw1_xp = _xi_total(xi, captain)
    five_gw_xp = round(
        sum(expected_points_window(conn, c.player_id, n_gw=5).total_median for c in xi.starting)
        + (expected_points_window(conn, captain.player_id, n_gw=5).total_median if captain else 0.0),
        2,
    )

    optimal = optimise_squad(conn, n_gw=1, objective="median")
    optimal_xi = pick_starting_xi(conn, optimal.squad)
    optimal_cap_report = captaincy_report(conn, [c.player_id for c in optimal.squad]) if optimal.squad else None
    optimal_gw1_xp = _xi_total(optimal_xi, optimal_cap_report.best if optimal_cap_report else None)
    efficiency_percent = round(gw1_xp / optimal_gw1_xp * 100, 1) if optimal_gw1_xp else 0.0

    template_ids = {t.player_id for t in get_template(conn)}
    squad_id_set = set(deduped_ids)
    differential_ids = [d.player_id for d in find_differentials(conn) if d.player_id in squad_id_set]
    trap_ids = [t.player_id for t in find_traps(conn) if t.player_id in squad_id_set]
    breakout_ids = [b.player_id for b in find_breakouts(conn) if b.player_id in squad_id_set]

    availability = list_availability(conn, unavailable_only=True)
    risks = [f"{a.web_name}: {a.classification}" for a in availability if a.player_id in squad_id_set]

    total_cost_tenths = sum(c.price_tenths for c in squad_candidates)
    rule_violations = _check_squad_legality(conn, squad_candidates, season)

    return SquadRating(
        squad_ids=squad_ids, invalid_ids=invalid_ids, duplicate_ids=duplicate_ids,
        total_cost_tenths=total_cost_tenths, bank_tenths=budget_tenths - total_cost_tenths,
        xi=xi, captain=captain, vice=vice,
        gw1_xp=gw1_xp, five_gw_xp=five_gw_xp,
        optimal_gw1_xp=optimal_gw1_xp, efficiency_percent=efficiency_percent,
        template_count=len(template_ids & squad_id_set),
        differential_ids=differential_ids, trap_ids=trap_ids, breakout_ids=breakout_ids,
        risks=risks, rule_violations=rule_violations,
    )
