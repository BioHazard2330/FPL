from fpl_agent.ingestion.workload import parse_physical


def _stat(key, value, total=None):
    st = {"value": value}
    if total is not None:
        st["total"] = total
    return {"key": key, "stat": st}


def test_physical_figures_are_read_per_player():
    payload = {"general": {"homeTeam": {"id": 1, "name": "Arsenal"}, "awayTeam": {"id": 2, "name": "Bayern"}},
               "content": {"playerStats": {
                   "10": {"id": 10, "name": "Bukayo Saka", "teamId": 1, "stats": [
                       {"key": "top_stats", "stats": {"Minutes played": _stat("minutes_played", 10)}},
                       {"key": "attack", "stats": {"Touches in opposition box": _stat("touches_opp_box", 2)}},
                       {"key": "physical_metrics", "stats": {"Distance covered": _stat("physical_metrics_distance_covered", 1210),
                                                             "Sprinting": _stat("physical_metrics_sprinting", 80, 1210),
                                                             "Number of sprints": _stat("physical_metrics_number_of_sprints", 4),
                                                             "Top speed": _stat("physical_metrics_topspeed", 33.2)}}]},
                   "11": {"id": 11, "name": "Unused Sub", "teamId": 1, "stats": [
                       {"key": "top_stats", "stats": {"Minutes played": _stat("minutes_played", 0)}}]},
               }}}
    rows = parse_physical(payload)
    assert len(rows) == 1
    r = rows[0]
    assert (r["team"], r["minutes"], r["distance_m"], r["sprint_m"], r["sprints"], r["top_speed"], r["touches_box"]) == ("Arsenal", 10, 1210, 80, 4, 33.2, 2)
