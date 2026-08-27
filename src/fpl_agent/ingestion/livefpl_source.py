"""LiveFPL real live-rank source (2026-08-27, direct user instruction: "if
you want to get my liverank, just use my team id and uses livefpl as the
main source to track my live rank always" - team 7378572). Real, free,
no-login, no-key public JSON endpoint - live-verified this session against
the real production site: `https://livefpl.net`'s own homepage advertises
"Enter your FPL ID to track your live rank" as its core free feature; its
own frontend calls exactly this endpoint (confirmed via a real browser
network-request capture, team id 7378572) to render that feature for an
anonymous, logged-out visitor - this connector calls the same public
endpoint directly rather than scraping the rendered page.

This supersedes this project's own self-built stratified-sample live-rank
estimator (`models/live_rank.py`) as the PRIMARY source: that module's own
docstring records the real research finding that drove its design - no
public LiveFPL/FPLForm API was found at the time, so this project built its
own approximation from public standings pages instead. That research gap is
now closed for the specific case of "my own team's live rank" (this
endpoint), though not for the general "any manager's rank" case the
self-built estimator's sampling machinery still uniquely covers - kept,
unchanged, as the fallback path when this endpoint is unreachable.

Real, disclosed limitations of this source:
- LiveFPL's own internal ranking/autosub/bonus methodology is proprietary
  and undocumented (the same real research gap `models/live_rank.py`
  already recorded) - this connector reports LiveFPL's own numbers
  verbatim, never re-derives or second-guesses them.
- `curgw`/`time` reflect whichever gameweek LiveFPL's own backend currently
  has live data for - between gameweeks this is the most recently completed
  one, not a fabricated "live" reading for a gameweek that hasn't started.
- Free, public, unauthenticated - same posture as this project's other
  third-party JSON sources (FotMob, Understat) - no SLA, can genuinely be
  unreachable, always fails soft (returns None, never raises past this
  module) rather than blocking any caller.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

_API_URL = "https://www.livefpl.net/livefplapi/{team_id}"
_TIMEOUT_SECONDS = 10
_HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-agent personal decision-support tool)"}
SOURCE_NAME = "livefpl"


class LiveFPLFetchError(Exception):
    pass


@dataclass(frozen=True)
class LiveFPLSnapshot:
    team_id: int
    name: str | None
    curgw: int | None
    gw_points: int | None
    gw_rank: int | None  # rank if scored purely on this gameweek's points ("GWrank")
    pre_subs_rank: int | None  # overall rank before autosubs are applied ("new")
    post_subs_rank: int | None  # overall rank after autosubs - the real headline live rank ("new_sim")
    old_rank: int | None  # the baseline rank this snapshot's change/gain is measured against ("old")
    rank_gain: int | None
    change_pct: float | None
    safety_score: float | None
    template_pct: float | None
    chip_played: str | None
    source_time: str | None  # LiveFPL's own real computation timestamp for this snapshot
    fetched_at: str


def _none_if_negative(v) -> int | None:
    # LiveFPL's own real sentinel for "not applicable/not computed yet" is
    # -1 on several integer fields (confirmed live: GWrank2 was -1 for a
    # team with no second-scenario chip active) - never displayed as a real
    # rank of -1.
    if v is None or (isinstance(v, (int, float)) and v < 0):
        return None
    return int(v)


def fetch_livefpl_snapshot(team_id: int) -> LiveFPLSnapshot:
    """Real HTTP GET, no key, no login - raises `LiveFPLFetchError` on any
    real network/HTTP/parse failure so the caller can decide how to log
    that (never silently swallowed here, matching `fotmob_source.py`'s own
    error-surfacing convention)."""
    url = _API_URL.format(team_id=team_id)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            message = f"livefpl request failed: HTTP {response.status_code} ({url})"
        else:
            message = f"livefpl request failed: request error ({url})"
        raise LiveFPLFetchError(message) from exc
    try:
        d = resp.json()
    except ValueError as exc:
        raise LiveFPLFetchError(f"livefpl returned non-JSON response ({url})") from exc
    if not isinstance(d, dict) or "id" not in d:
        raise LiveFPLFetchError(f"livefpl response missing expected 'id' field ({url})")

    return LiveFPLSnapshot(
        team_id=int(d.get("id", team_id)),
        name=d.get("name"),
        curgw=d.get("curgw"),
        gw_points=d.get("total"),
        gw_rank=_none_if_negative(d.get("GWrank")),
        pre_subs_rank=_none_if_negative(d.get("new")),
        post_subs_rank=_none_if_negative(d.get("new_sim")),
        old_rank=_none_if_negative(d.get("old")),
        rank_gain=d.get("rank_gain"),
        change_pct=d.get("change"),
        safety_score=d.get("safety_score"),
        template_pct=d.get("template"),
        chip_played=d.get("chip"),
        source_time=d.get("time"),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
