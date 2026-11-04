from fpl_agent.ingestion import live_ticker as lt


def _e(code, elapsed=0, plus=-1, text="line", home=None, players=None, hl=False):
    return {"MessageId": f"{code}{elapsed}{text}", "IncidentCode": code, "Elapsed": elapsed, "ElapsedPlus": plus, "Description": text,
            "HometeamEvent": home, "Players": players, "IncludeInHighlight": hl}


FEED = {"LastUpdated": "t", "Events": [
    _e("post_match summary", text="report"),
    _e("YC", 90, 7, "late card", False, [{"Id": 5, "Name": "Late", "TeamId": 2}]),
    _e("OG", 64, text="own goal", home=False, players=[{"Id": 3, "Name": "Keeper", "TeamId": 1}]),
    _e("comment", 0, text="an aside"),
    _e("half_time summary", text="half"),
    _e("SI", 46, text="change", home=True, players=[{"Id": 1, "Name": "On", "TeamId": 1}, {"Id": 2, "Name": "Off", "TeamId": 1}]),
    _e("G", 16, text="goal", home=True, players=[{"Id": 4, "Name": "Scorer", "TeamId": 1}], hl=True),
    _e("comment", 3, text="early"),
    _e("team news", text="lineups"),
    _e("comment", 0, text="preview"),
]}


def test_rows_run_oldest_first_with_reports_and_team_news_set_apart():
    p = lt.parse_ticker(FEED)
    assert [e["text"] for e in p["events"]][:3] == ["preview", "early", "goal"]
    assert p["reports"] == {"full_time": "report", "half_time": "half"} and p["team_news"] == ["lineups"] and p["finished"]


def test_the_score_runs_and_an_own_goal_counts_for_the_side_it_benefits():
    p = lt.parse_ticker(FEED)
    assert [e["score"] for e in p["events"] if "score" in e] == [[1, 0], [1, 1]]


def test_a_row_with_no_minute_takes_the_one_before_it_and_stoppage_is_kept():
    rows = {e["text"]: e for e in lt.parse_ticker(FEED)["events"]}
    assert rows["preview"]["minute"] is None
    assert rows["an aside"]["minute"] == 46
    assert (rows["late card"]["minute"], rows["late card"]["stoppage"]) == (90, 7)


def test_incident_kinds_and_key_rows():
    rows = {e["text"]: e for e in lt.parse_ticker(FEED)["events"]}
    assert rows["goal"]["kind"] == "goal" and rows["own goal"]["kind"] == "own_goal" and rows["late card"]["kind"] == "yellow"
    assert rows["change"]["kind"] == "sub" and rows["change"]["players"][0]["name"] == "On"
    assert rows["early"]["key"] is False and rows["goal"]["key"] is True


def test_cache_keeps_the_last_good_copy_when_a_refresh_fails():
    lt._CACHE.clear()
    live = {"Events": [_e("comment", 3, text="x")]}
    assert lt.cached_ticker("m", now=0, fetch=lambda m: live)["events"]

    def broken(m):
        raise lt.TickerUnavailable("down")

    assert lt.cached_ticker("m", now=100, fetch=broken)["events"]


def test_a_match_with_no_file_is_none_and_not_refetched_inside_the_hour():
    lt._CACHE.clear()
    calls = []

    def missing(m):
        calls.append(m)
        raise lt.TickerUnavailable("none")

    assert lt.cached_ticker("n", now=0, fetch=missing) is None
    assert lt.cached_ticker("n", now=10, fetch=missing) is None
    assert len(calls) == 1


def _details(show=True, url="https://pub.fotmob.com/prod/news/api/law?matchid=x"):
    return {"content": {"superlive": {"superLiveUrl": url, "showSuperLive": show}},
            "header": {"teams": [{"name": "A", "score": 1}, {"name": "B", "score": 0}], "status": {"started": True, "finished": False, "liveTime": {"short": "52\u200e\u2019\u200e"}}}}


def test_the_live_pitch_is_offered_only_while_fotmob_shows_it():
    assert lt.parse_live_state(_details())["pitch_url"].startswith(lt.PITCH_HOST)
    assert lt.parse_live_state(_details(show=False))["pitch_url"] is None


def test_a_pitch_address_on_another_host_is_never_passed_to_the_frame():
    assert lt.parse_live_state(_details(url="https://evil.example/x"))["pitch_url"] is None


def test_live_state_reads_score_and_clock():
    s = lt.parse_live_state(_details())
    assert s["score"] == [1, 0] and s["minute"] == "52" and s["started"] and not s["finished"]


def test_live_state_is_cached_and_survives_a_failed_refresh():
    from fpl_agent.ingestion.fotmob_source import FotMobFetchError

    lt._LIVE_STATE.clear()
    assert lt.match_live("z", now=0, fetch=lambda m: _details())["score"] == [1, 0]

    def broken(m):
        raise FotMobFetchError("down")

    assert lt.match_live("z", now=5, fetch=broken)["score"] == [1, 0]
    assert lt.match_live("z", now=100, fetch=broken)["score"] == [1, 0]
