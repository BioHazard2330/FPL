import pytest

import fpl_agent.ingestion.livefpl_source as livefpl_mod
from fpl_agent.ingestion.livefpl_source import LiveFPLFetchError, fetch_livefpl_snapshot

# Trimmed real shape (2026-08-27, live-verified against the real production
# endpoint for team 7378572 - see the module's own docstring for the real
# network-capture evidence) - only the fields this connector actually reads.
_REAL_SHAPE_PAYLOAD = {
    "id": 7378572, "name": "Pranav Nair", "curgw": 1, "total": 51,
    "GWrank": 4149531, "GWrank2": -1, "new": 3477519, "new_sim": 4088241,
    "old": 4000000, "rank_gain": -88241, "change": 2.21, "safety_score": 53,
    "template": 82.0, "chip": None, "time": "2026-08-24 23:01:25",
}


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, raise_for_status_exc=None):
        self._json_data = json_data
        self.status_code = status_code
        self._raise_for_status_exc = raise_for_status_exc

    def raise_for_status(self):
        if self._raise_for_status_exc is not None:
            raise self._raise_for_status_exc

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON")
        return self._json_data


def test_fetch_livefpl_snapshot_parses_the_real_field_shape(monkeypatch):
    monkeypatch.setattr(livefpl_mod.requests, "get", lambda *a, **k: _FakeResponse(_REAL_SHAPE_PAYLOAD))

    snap = fetch_livefpl_snapshot(7378572)

    assert snap.team_id == 7378572
    assert snap.name == "Pranav Nair"
    assert snap.curgw == 1
    assert snap.gw_points == 51
    assert snap.gw_rank == 4149531
    assert snap.pre_subs_rank == 3477519
    assert snap.post_subs_rank == 4088241
    assert snap.old_rank == 4000000
    assert snap.rank_gain == -88241
    assert snap.change_pct == 2.21
    assert snap.safety_score == 53
    assert snap.template_pct == 82.0
    assert snap.chip_played is None
    assert snap.source_time == "2026-08-24 23:01:25"


def test_fetch_livefpl_snapshot_treats_negative_sentinel_as_none(monkeypatch):
    # Real LiveFPL sentinel: -1 on an int field means "not applicable/not
    # computed" (confirmed live: GWrank2 was -1 for a team with no second
    # chip scenario active) - must never be surfaced as a literal rank -1.
    payload = dict(_REAL_SHAPE_PAYLOAD, new=-1, new_sim=-1)
    monkeypatch.setattr(livefpl_mod.requests, "get", lambda *a, **k: _FakeResponse(payload))

    snap = fetch_livefpl_snapshot(7378572)

    assert snap.pre_subs_rank is None
    assert snap.post_subs_rank is None


def test_fetch_livefpl_snapshot_raises_on_http_error(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(livefpl_mod.requests, "get", _boom)

    with pytest.raises(LiveFPLFetchError):
        fetch_livefpl_snapshot(7378572)


def test_fetch_livefpl_snapshot_raises_on_non_json_response(monkeypatch):
    monkeypatch.setattr(livefpl_mod.requests, "get", lambda *a, **k: _FakeResponse(json_data=None))

    with pytest.raises(LiveFPLFetchError):
        fetch_livefpl_snapshot(7378572)


def test_fetch_livefpl_snapshot_raises_on_unexpected_shape(monkeypatch):
    # Real defensive check - a payload missing the 'id' field (e.g. an
    # error page or a schema change on LiveFPL's own side) must never be
    # silently parsed into a fabricated-looking snapshot.
    monkeypatch.setattr(livefpl_mod.requests, "get", lambda *a, **k: _FakeResponse(json_data={"error": "not found"}))

    with pytest.raises(LiveFPLFetchError):
        fetch_livefpl_snapshot(7378572)
