import json

from fpl_agent.models import judgements


def test_latest_reads_the_newest_gameweek_file(tmp_path):
    (tmp_path / "gw9.json").write_text(json.dumps({"event": 9, "clubs": {}, "players": {}}), encoding="utf-8")
    (tmp_path / "gw11.json").write_text(json.dumps({"event": 11, "clubs": {"ARS": {"verdict": "v", "fpl": "f"}}, "players": {"4": "call"}}), encoding="utf-8")
    data = judgements.latest(directory=tmp_path)
    assert data["event"] == 11
    assert judgements.for_club(data, "ARS")["verdict"] == "v" and judgements.for_club(data, "CHE") is None
    assert judgements.for_player(data, 4) == "call" and judgements.for_player(None, 4) is None
