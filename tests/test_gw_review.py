from fpl_agent.models.gw_review import automatic_subs, autosub_watch


def _sq():
    def p(pid, pos, slot):
        return {"player_id": pid, "position": pos, "starting": slot <= 11, "slot": slot, "minutes": 90}
    xi = [p(1, "GKP", 1), p(2, "DEF", 2), p(3, "DEF", 3), p(4, "DEF", 4), p(5, "MID", 5), p(6, "MID", 6), p(7, "MID", 7),
          p(8, "MID", 8), p(9, "MID", 9), p(10, "FWD", 10), p(11, "FWD", 11)]
    bench = [p(12, "GKP", 12), p(13, "DEF", 13), p(14, "FWD", 14), p(15, "DEF", 15)]
    return xi + bench


def test_automatic_subs_follow_bench_order_and_keep_the_formation():
    sq = _sq()
    for x in sq:
        if x["player_id"] in (11, 13):
            x["minutes"] = 0
    # forward out: first bench outfielder who played and keeps a legal shape is 14 (13 did not play)
    assert automatic_subs(sq) == [(11, 14)]
    sq = _sq()
    sq[3]["minutes"] = 0  # a third defender out: only a defender keeps three at the back
    assert automatic_subs(sq) == [(4, 13)]
    sq = _sq()
    sq[0]["minutes"] = 0  # goalkeeper only for goalkeeper
    assert automatic_subs(sq) == [(1, 12)]


def test_autosub_watch_separates_made_from_standby():
    sq = _sq()
    minutes = {x["player_id"]: 90 for x in sq}
    minutes[11] = 0
    minutes[5] = 0
    done = {x["player_id"]: True for x in sq}
    done[5] = False  # his match is still to finish
    w = {r["out"]: r for r in autosub_watch(sq, minutes, done)}
    assert w[11] == {"out": 11, "into": 13, "status": "made"}
    assert w[5]["status"] == "standby" and w[5]["into"] == 13


def test_gameweek_review_reads_a_week_back(db_conn, monkeypatch):
    import json

    from fpl_agent.models import gw_review, rules

    monkeypatch.setattr(rules, "current_season", lambda conn: "2026-27")
    monkeypatch.setattr("fpl_agent.models.captain_autopsy.captain_autopsy", lambda conn, entry: [])
    c = db_conn
    c.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t0')")
    for et, short in ((1, "GKP"), (2, "DEF"), (3, "MID"), (4, "FWD")):
        c.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (?,?,?,?, 't0')", (et, short, short, short))
    for ev, dl in ((7, "2026-10-16T17:30:00Z"), (8, "2026-10-23T17:30:00Z")):
        c.execute("INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,average_entry_score,highest_score,updated_at) "
                  "VALUES (?, ?, ?, 1, 1, 0, 0, 0, 45, 120, 't')", (ev, f"GW{ev}", dl))
    shape = [1, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 1, 2, 4, 2]
    points = [2, 1, 5, 14, 2, -1, 1, 0, 10, 8, 0, 9, 2, 2, 1]
    minutes = [90] * 10 + [0] + [90, 90, 90, 90]
    for i, (et, pts, mins) in enumerate(zip(shape, points, minutes), start=1):
        c.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,?,'a',0,'t0')", (i, i, f"P{i}", et))
        c.execute("INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, is_captain, is_vice_captain, active_chip, retrieved_at) "
                  "VALUES (99, 8, ?, ?, ?, ?, ?, NULL, 't')", (i, i, (2 if i == 10 else 1) if i <= 11 else 0, int(i == 10), int(i == 9)))
        c.execute("INSERT INTO player_gw_stats (player_id, event, season, minutes, starts, goals, assists, clean_sheets, goals_conceded, own_goals, "
                  "penalties_missed, penalties_saved, yellow_cards, red_cards, saves, bonus, bps, defensive_contribution, xg, xa, xgc, total_points, fixtures, retrieved_at) "
                  "VALUES (?, 8, '2026-27', ?, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ?, 1, 't')", (i, mins, pts))
    c.execute("INSERT INTO player_sample_ownership_history (player_id, event, season, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
              "VALUES (4, 8, '2026-27', 100, 50, 0, 50, 50, 't')")
    for ev, pts, total, rank in ((7, 77, 474, 1235835), (8, 52, 526, 1022596)):
        c.execute("INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, event_transfers, event_transfers_cost, points_on_bench, retrieved_at) "
                  "VALUES (99, ?, ?, ?, ?, 0, 0, 12, 't')", (ev, pts, total, rank))
    plan = {"event": 8, "free_transfers": 1, "moves": [], "lineup_after": {"starting": [{"player_id": i} for i in range(1, 12)], "captain_id": 4, "vice_id": 9}}
    c.execute("INSERT INTO decisions (decision_type, summary, detail, model_version, confidence, created_at) VALUES ('week_plan', 's', ?, 'v', 'x', '2026-10-23T17:00:00+00:00')", (json.dumps(plan),))
    r = gw_review.gameweek_review(c, 99, 8)
    assert r["points"] == 52 and r["counted"] == 52
    assert r["subs"] == [{"out": "P11", "into": "P13"}]  # first bench player in order who keeps a legal shape
    assert r["plan"]["score"] == 42 + 14  # its eleven (P11 on 0) and Konsa-like P4 doubled
    assert r["previous_rank"] == 1235835 and r["top10k_field"] == 7.0
    swings = {g["player_id"]: g["swing"] for g in r["gains"]}
    assert swings[10] == 16.0  # the captain, owned by nobody in the sample
    assert swings[4] == 7.0  # 14 points, yours once, half the sample owns him
