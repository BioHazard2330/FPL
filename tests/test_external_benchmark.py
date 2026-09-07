from datetime import datetime, timezone

import fpl_agent.models.external_benchmark as bench_mod
from fpl_agent.models.expected_points import ComponentBreakdown, ExpectedPoints, TeamFixtureProjection
from fpl_agent.models.external_benchmark import (
    classify_divergence, compare_all_matched_players, compare_captain_pick,
    compare_components, compare_player, compare_team_outlooks, compare_transfer_target, latest_solio_snapshot,
    top_divergences,
)
from fpl_agent.optimization.captaincy import CaptainOption


# --- classify_divergence ---

def test_classify_divergence_agreement_within_ten_percent():
    assert classify_divergence(6.0, 6.4) == "AGREEMENT"


def test_classify_divergence_minor_band():
    assert classify_divergence(6.0, 6.8) == "MINOR_DIVERGENCE"


def test_classify_divergence_material_band():
    assert classify_divergence(4.0, 5.5) == "MATERIAL_DIVERGENCE"


def test_classify_divergence_major_outlier():
    assert classify_divergence(3.69, 7.19) == "MAJOR_OUTLIER"


def test_classify_divergence_ignores_tiny_values_below_absolute_floor():
    # 0.1 vs 0.2 is a 100% relative diff but both are noise-scale - must not
    # be flagged as an outlier over near-nothing.
    assert classify_divergence(0.1, 0.2) == "AGREEMENT"


# --- compare_components ---

def _components(**overrides):
    base = dict(appearance=1.0, goals=0.3, assists=0.2, bonus=0.5, clean_sheet=0.6, cards=-0.05, conceded=0.0, defcon=0.1)
    base.update(overrides)
    return ComponentBreakdown(**base)


class _FakeSolioRow(dict):
    """sqlite3.Row-alike: bracket access only, dict-backed for tests."""


def test_compare_components_finds_the_largest_real_driver():
    our = _components(goals=0.26, assists=0.41, bonus=0.87, defcon=0.11)
    solio_row = _FakeSolioRow(
        pr_points=7.19, pr_points_from_goals=1.94, pr_points_from_assists=1.85,
        pr_bonus_points=1.06, pr_defcon_points=None,
    )
    comparisons, largest_driver = compare_components(our, solio_row)
    assert largest_driver == "goals"  # 1.94-0.26=1.68, the largest of the published components
    goals_comp = next(c for c in comparisons if c.component == "goals")
    assert goals_comp.diff is not None and goals_comp.diff > 1.6


def test_compare_components_never_picks_the_other_bucket_as_driver():
    # 'other' has by far the largest real diff, but it's a residual, not a
    # like-for-like Solio figure - must never be reported as the driver.
    our = _components(appearance=0.5, clean_sheet=0.2, cards=0.0, conceded=0.0, goals=1.0, assists=1.0, bonus=0.1, defcon=0.0)
    solio_row = _FakeSolioRow(
        pr_points=10.0, pr_points_from_goals=1.05, pr_points_from_assists=1.05,
        pr_bonus_points=0.15, pr_defcon_points=None,
    )
    comparisons, largest_driver = compare_components(our, solio_row)
    assert largest_driver in {"goals", "assists", "bonus"}


# --- compare_player / compare_all_matched_players / top_divergences ---

def _fake_ep(median: float, components: ComponentBreakdown | None = None) -> ExpectedPoints:
    return ExpectedPoints(
        player_id=1, position="MID", floor=median * 0.5, median=median, ceiling=median * 1.8,
        confidence="MEDIUM", expected_minutes=90.0, model_version="test", components=components,
    )


def _seed_snapshot(conn) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO solio_snapshot (gameweek, generated_at, deadline_iso, source_url, retrieved_at) "
        "VALUES (2, ?, NULL, 'https://fpl.solioanalytics.com', ?)", (now, now),
    )
    conn.commit()
    return cur.lastrowid


def _seed_snapshot_and_player_row(conn, player_id, source_name, pr_points, extra=None, snapshot_id=None):
    """Convenience wrapper for single-player tests - seeds its own fresh
    snapshot when `snapshot_id` isn't given. Multi-player tests must pass a
    shared `snapshot_id` (from `_seed_snapshot`) so every player lands in
    the SAME real snapshot, matching how `store_snapshot` actually writes -
    a real test bug found live: calling this once per player without a
    shared snapshot_id silently split them across separate snapshots, so
    `latest_solio_snapshot` only ever saw the last one."""
    snapshot_id = snapshot_id if snapshot_id is not None else _seed_snapshot(conn)
    fields = dict(
        pr_points_from_goals=None, pr_points_from_assists=None, pr_bonus_points=None, pr_defcon_points=None,
        captain_proj_points=None, leverage=None, transfers_in=None, transfers_out=None, price=None, ownership=None,
        team_short=None, position=None,
    )
    if extra:
        fields.update(extra)
    conn.execute(
        "INSERT INTO solio_player_projection (snapshot_id, player_id, source_name, pr_points, categories, "
        "pr_points_from_goals, pr_points_from_assists, pr_bonus_points, pr_defcon_points, captain_proj_points, "
        "leverage, transfers_in, transfers_out, price, ownership, team_short, position) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (snapshot_id, player_id, source_name, pr_points, "topProjected", fields["pr_points_from_goals"],
         fields["pr_points_from_assists"], fields["pr_bonus_points"], fields["pr_defcon_points"],
         fields["captain_proj_points"], fields["leverage"], fields["transfers_in"], fields["transfers_out"],
         fields["price"], fields["ownership"], fields["team_short"], fields["position"]),
    )
    conn.commit()
    return snapshot_id


def _seed_player_row(conn, player_id, web_name="Test Player"):
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) "
        "VALUES (1, 100, 'Team', 'TM', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,?,?,1,1,'a','2026-01-01T00:00:00Z')",
        (player_id, 200 + player_id, web_name, "First", "Second"),
    )
    conn.commit()


def test_compare_player_returns_none_without_a_solio_row(db_conn, monkeypatch):
    _seed_player_row(db_conn, 1)
    snapshot = latest_solio_snapshot(db_conn)  # no snapshot exists yet
    assert snapshot is None


def test_compare_player_computes_real_diff_and_classification(db_conn, monkeypatch):
    _seed_player_row(db_conn, 1, web_name="Bruno")
    _seed_snapshot_and_player_row(db_conn, 1, "B.Fernandes", 7.19)
    snapshot = latest_solio_snapshot(db_conn)

    monkeypatch.setattr(bench_mod, "expected_points", lambda conn, pid, n_gw=1: _fake_ep(3.69))

    c = compare_player(db_conn, 1, snapshot)
    assert c is not None
    assert c.our_median == 3.69
    assert c.solio_pr_points == 7.19
    assert c.classification == "MAJOR_OUTLIER"


def test_compare_all_matched_players_computes_ranks_within_the_solio_universe(db_conn, monkeypatch):
    _seed_player_row(db_conn, 1, web_name="High")
    _seed_player_row(db_conn, 2, web_name="Low")
    snapshot_id = _seed_snapshot(db_conn)
    _seed_snapshot_and_player_row(db_conn, 1, "High", 5.0, snapshot_id=snapshot_id)
    _seed_snapshot_and_player_row(db_conn, 2, "Low", 8.0, snapshot_id=snapshot_id)
    snapshot = latest_solio_snapshot(db_conn)
    assert snapshot.snapshot_id == snapshot_id

    fake_medians = {1: 9.0, 2: 1.0}  # our model ranks them the OPPOSITE way to Solio
    monkeypatch.setattr(bench_mod, "expected_points", lambda conn, pid, n_gw=1: _fake_ep(fake_medians[pid]))

    comparisons = compare_all_matched_players(db_conn, snapshot=snapshot)
    by_name = {c.web_name: c for c in comparisons}
    assert by_name["High"].our_rank == 1 and by_name["High"].solio_rank == 2
    assert by_name["Low"].our_rank == 2 and by_name["Low"].solio_rank == 1
    assert by_name["High"].rank_diff == 1  # solio_rank - our_rank = 2 - 1
    assert by_name["Low"].rank_diff == -1


def test_top_divergences_filters_and_sorts_by_absolute_diff(db_conn, monkeypatch):
    _seed_player_row(db_conn, 1, web_name="Agree")
    _seed_player_row(db_conn, 2, web_name="BigGap")
    _seed_player_row(db_conn, 3, web_name="SmallGap")
    snapshot_id = _seed_snapshot(db_conn)
    _seed_snapshot_and_player_row(db_conn, 1, "Agree", 5.0, snapshot_id=snapshot_id)
    _seed_snapshot_and_player_row(db_conn, 2, "BigGap", 10.0, snapshot_id=snapshot_id)
    _seed_snapshot_and_player_row(db_conn, 3, "SmallGap", 6.0, snapshot_id=snapshot_id)
    snapshot = latest_solio_snapshot(db_conn)

    fake_medians = {1: 5.0, 2: 2.0, 3: 5.0}
    monkeypatch.setattr(bench_mod, "expected_points", lambda conn, pid, n_gw=1: _fake_ep(fake_medians[pid]))

    top = top_divergences(db_conn, n=5, min_classification="MINOR_DIVERGENCE", snapshot=snapshot)
    names = [c.web_name for c in top]
    assert "Agree" not in names  # AGREEMENT, filtered out
    assert names[0] == "BigGap"  # largest absolute diff first


# --- compare_team_outlooks ---

def test_compare_team_outlooks_classifies_cs_prob_divergence(db_conn, monkeypatch):
    _seed_team_only(db_conn, team_id=1, name="Arsenal")
    now = datetime.now(timezone.utc).isoformat()
    cur = db_conn.execute(
        "INSERT INTO solio_snapshot (gameweek, generated_at, deadline_iso, source_url, retrieved_at) "
        "VALUES (2, ?, NULL, 'https://fpl.solioanalytics.com', ?)", (now, now),
    )
    snapshot_id = cur.lastrowid
    db_conn.execute(
        "INSERT INTO solio_team_projection (snapshot_id, team_id, team_name, pr_goals_for, pr_goals_against, "
        "cs_prob, categories) VALUES (?, 1, 'Arsenal', 2.0, 0.5, 0.60, 'bestCleanSheets')",
        (snapshot_id,),
    )
    db_conn.commit()
    snapshot = latest_solio_snapshot(db_conn)

    fake_proj = TeamFixtureProjection(team_id=1, fixture_id=1, event=1, goals_for=2.0, goals_against=1.5, cs_prob=0.25)
    monkeypatch.setattr(bench_mod, "team_next_fixture_projection", lambda conn, team_id: fake_proj)

    results = compare_team_outlooks(db_conn, snapshot)
    assert len(results) == 1
    assert results[0].classification == "MATERIAL_DIVERGENCE"  # |0.60 - 0.25| = 0.35


def _seed_team_only(conn, team_id, name, short=None):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'2026-01-01T00:00:00Z')",
        (team_id, 100 + team_id, name, short or name[:3].upper()),
    )
    conn.commit()


# --- decision cross-checks (captain / transfer target) never re-derive the decision ---

def test_compare_captain_pick_agreement(db_conn, monkeypatch):
    _seed_player_row(db_conn, 1, web_name="Haaland")
    snapshot_id = _seed_snapshot_and_player_row(db_conn, 1, "Haaland", 6.0, extra={"captain_proj_points": 12.0})
    snapshot = latest_solio_snapshot(db_conn)

    our_pick = CaptainOption(
        player_id=1, web_name="Haaland", position="FWD", floor=3.0, median=6.5, ceiling=10.0,
        confidence="HIGH", expected_minutes=90.0, is_penalty_taker=True, opponent_short="CRY",
        is_home=False, selected_by_percent=60.0, effective_ownership_percent=70.0, eo_source="sampled",
    )
    monkeypatch.setattr(
        "fpl_agent.optimization.captaincy.evaluate_captaincy", lambda conn, squad_ids: [our_pick]
    )

    result = compare_captain_pick(db_conn, [1], snapshot)
    assert result.verdict == "AGREEMENT"
    assert result.our_pick_name == "Haaland"


def test_compare_captain_pick_divergence_never_overrides_our_pick(db_conn, monkeypatch):
    _seed_player_row(db_conn, 1, web_name="Mbeumo")
    _seed_player_row(db_conn, 2, web_name="B.Fernandes")
    _seed_snapshot_and_player_row(db_conn, 2, "B.Fernandes", 7.19, extra={"captain_proj_points": 14.37})
    snapshot = latest_solio_snapshot(db_conn)

    our_pick = CaptainOption(
        player_id=1, web_name="Mbeumo", position="MID", floor=3.0, median=5.98, ceiling=9.0,
        confidence="HIGH", expected_minutes=90.0, is_penalty_taker=False, opponent_short="NFO",
        is_home=True, selected_by_percent=30.0, effective_ownership_percent=35.0, eo_source="sampled",
    )
    monkeypatch.setattr(
        "fpl_agent.optimization.captaincy.evaluate_captaincy", lambda conn, squad_ids: [our_pick]
    )

    result = compare_captain_pick(db_conn, [1, 2], snapshot)
    assert result.verdict == "DIVERGENCE"
    assert result.our_pick_name == "Mbeumo"  # unchanged - this function never picks a winner
    assert result.solio_pick_name == "B.Fernandes"


def test_compare_transfer_target_agreement_when_solio_also_lists_it(db_conn):
    _seed_player_row(db_conn, 1, web_name="Tavernier")
    _seed_snapshot_and_player_row(db_conn, 1, "Tavernier", 4.75)
    snapshot = latest_solio_snapshot(db_conn)

    result = compare_transfer_target(db_conn, 1, "Tavernier", snapshot)
    assert result.verdict == "AGREEMENT"


def test_compare_transfer_target_divergence_when_solio_never_lists_it(db_conn):
    _seed_player_row(db_conn, 1, web_name="ObscurePlayer")
    _seed_player_row(db_conn, 2, web_name="OtherPlayer")
    _seed_snapshot_and_player_row(db_conn, 2, "OtherPlayer", 4.0)  # snapshot exists, but not for player 1
    snapshot = latest_solio_snapshot(db_conn)

    result = compare_transfer_target(db_conn, 1, "ObscurePlayer", snapshot)
    assert result.verdict == "DIVERGENCE"


def test_compare_transfer_target_insufficient_evidence_with_no_snapshot(db_conn):
    result = compare_transfer_target(db_conn, 1, "Whoever", snapshot=None)
    assert result.verdict == "INSUFFICIENT_EVIDENCE"
