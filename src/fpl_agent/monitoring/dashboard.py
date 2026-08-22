"""Local auto-refreshing HTML dashboard (2026-08-20, per the user asking
whether an always-fresh website is possible). Real, disclosed constraint
checked before building this: a published Artifact page cannot read this
project's local SQLite DB (no filesystem access from a sandboxed browser
page) and has no capability to autonomously fetch external data on a timer
without a viewer action - a genuinely "hosted, always-fresh, no-Claude-open"
public website is not reachable with this project's local-first,
free-resources-only architecture without a real hosting change (likely
paid, out of scope). What IS real and free: the Windows Task Scheduler
(registered this session, `fpl run-scheduled`) already refreshes the
database every 60 minutes with zero Claude session needed - this module
turns that into a local HTML file the user can open once and leave open,
auto-reloading itself to show whatever the last sync produced. `fpl
run-scheduled` regenerates it every cycle; `fpl dashboard` regenerates it
on demand.

Redesigned 2026-08-20 (visual overhaul, per direct user feedback that the
first version read as "plain"/"AI-generated" - a styled table dump, not
an FPL app). Palette/component choices follow the `dataviz` skill's
validated reference palette (categorical hues for position identity,
fixed status colors for OK/DEGRADED/MISSING, never color-alone - every
colored state also carries a text label). Four real panels: a visual
pitch layout for the squad (not a table), live in-play tracking (honest
about pre-kickoff/live/no-data states - never fabricates a score),
recent Tier 2-4 transfer news, and a compact system-health strip.
"""
import html
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.database.decisions import latest_decision_of_type
from fpl_agent.models.availability import list_availability
from fpl_agent.models.blend import clean_sheet_probability
from fpl_agent.optimization.captaincy import captaincy_report
from fpl_agent.models.expected_points import _fixture_goals_for
from fpl_agent.models.fixtures import live_or_reference_event, team_fixture_ticker
from fpl_agent.models.live_bonus import compute_live_bonus
from fpl_agent.models.live_rank import estimate_squad_live_points
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.models.team_outlook import squad_team_outlooks
from fpl_agent.models.team_news_risk import flag_squad_rotation_risk
from fpl_agent.ingestion.my_team import get_latest_squad, get_my_team_entry_id
from fpl_agent.ingestion.news_source import list_recent_news
from fpl_agent.ingestion.predicted_lineups_source import get_predicted_lineup_for_squad
from fpl_agent.monitoring.readiness import run_readiness_checks
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.optimization.build_team import generate_build_team_report
from fpl_agent.optimization.decision_engine import evaluate_locked_squad
from fpl_agent.optimization.locked_squad import get_locked_squad
from fpl_agent.optimization.rate_team import rate_team
from fpl_agent.optimization.squad import validate_starting_xi
from fpl_agent.optimization.chips import (
    bench_boost_value,
    eligible_chips,
    freehit_value,
    triple_captain_value,
    wildcard_value,
)

_REFRESH_SECONDS = 60  # client-side reload cadence - tightened 2026-08-20 (was 300) per direct
# user ask for near-real-time updates; the actual data freshness ceiling is however often
# fpl run-scheduled last ran (scheduler/adaptive.py now retightens that too, 15-360min by
# real deadline-proximity - see config/freshness.yaml), reloading the static HTML file
# itself is free, so there's no cost to checking far more often than that.
_CHANGE_EVENT_TYPES = (
    "new_player", "removed_player", "club_change", "status_change",
    # Real gap closed 2026-08-21 (locked-squad product architecture pass,
    # direct user request: "the dashboard is the primary notification
    # surface, not PowerShell popups"). These three event types have been
    # written to change_events since the live-gameweek layer (same day,
    # earlier) - already scoped to tracked_squad_ids at write time by their
    # own detectors, already deduplicated (each only fires on a genuine
    # diff against the prior snapshot, or once per real fixture for
    # kickoff_reminder - see ingestion/change_detection.py's own
    # docstrings) - but were never actually rendered anywhere on the
    # dashboard itself before this, only ever pushed as a toast/terminal
    # alert. price_change deliberately excluded here - it already has its
    # own dedicated `_price_changes_html` panel, showing it here too would
    # duplicate the same row.
    "predicted_lineup_change", "start_percent_change", "kickoff_reminder",
)
_POSITION_ORDER = ["GKP", "DEF", "MID", "FWD"]
# Fixed categorical order per the dataviz skill's validated palette (slots 1-4):
# assigning hues by the job they do (position identity) in the palette's own
# documented fixed order, never cycled/reassigned per-render.
_POSITION_ACCENT = {
    "GKP": ("#2a78d6", "#3987e5"),  # slot 1 blue
    "DEF": ("#eb6834", "#d95926"),  # slot 2 orange
    "MID": ("#1baf7a", "#199e70"),  # slot 3 aqua
    "FWD": ("#eda100", "#c98500"),  # slot 4 yellow
}
_CONFIDENCE_TIER = {"HIGH": ("STRONG", "strong"), "MEDIUM": ("GOOD", "good"), "LOW": ("WATCH", "watch")}
_LINEUP_STATUS_LABEL = {
    "starting": ("starting", "ok"), "bench": ("bench", "warn"),
    "doubt": ("doubt", "warn"), "out": ("out", "bad"), "banned": ("banned", "bad"),
}


def _official_shirt_url(team_code: int, is_gkp: bool, size: int = 110) -> str:
    """The REAL official FPL kit graphic (2026-08-21, replacing both the
    hand-drawn SVG jersey and the player-photo experiment earlier this
    session) - `fantasy.premierleague.com/dist/img/shirts/standard/
    shirt_{team_code}[_1]-{size}.webp`, confirmed live via this project's
    own browser network inspection of FPL's real `/statistics` page (which
    uses this exact asset for its own player list, not a photo). `_1`
    selects the goalkeeper kit variant. This is structurally immune to the
    per-player photo staleness problem the CDN photo had (Madueke shown in
    a real Chelsea kit weeks after his real Arsenal transfer, confirmed via
    the photo's own `Last-Modified: Feb 2025` header) - a shirt asset is
    keyed by TEAM, not player, so it's automatically correct for a
    transferred player the moment `players.team_id` updates on the next
    sync, no separate photo-refresh dependency at all. `team_code` is
    `teams.code` (confirmed live: Arsenal=3, Man Utd=1, Man City=43 -
    exactly matches the real asset filenames observed)."""
    suffix = "_1" if is_gkp else ""
    return f"https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_{team_code}{suffix}-{size}.webp"


def _source_freshness(conn: sqlite3.Connection, *source_names: str) -> str | None:
    """Real per-widget "updated Xs ago" (2026-08-21, third session, section
    19: "add a small data freshness system... ONLY if these timestamps
    actually exist"). Reads `source_health.last_success` - already-real,
    already-persisted per-source sync timestamps, no new tracking. Takes the
    MOST RECENT of the given sources (e.g. the 3 separate real news feeds)
    rather than fabricating one combined "freshness" that doesn't map to any
    single real sync. Returns None (never a fake "unknown") when none of the
    named sources have ever synced."""
    rows = get_source_health(conn)
    times = [r.last_success for r in rows if r.source_name in source_names and r.last_success]
    if not times:
        return None
    return _relative_time(max(times))


_FIXTURE_QUALITY_LABEL = {"ok": "Easy", "warn": "Average", "bad": "Hard"}


def _fixture_quality(conn: sqlite3.Connection, team_id: int, n_gw: int = 5) -> tuple[str, str, float] | None:
    """Real average fixture difficulty over the next n_gw real fixtures for
    one team - reuses `team_fixture_ticker`'s own already-computed
    `e.difficulty` values (the same real FPL strength-rating-derived number
    the Fixture Ticker itself renders), just averaged here for a compact
    one-word read. Returns None for a genuine blank stretch (no fixtures),
    never a fabricated "average" difficulty."""
    entries = team_fixture_ticker(conn, team_id, n_gw=n_gw)
    if not entries:
        return None
    avg = sum(e.difficulty for e in entries) / len(entries)
    cls = _fdr_class(round(avg))
    return cls, _FIXTURE_QUALITY_LABEL[cls], avg


def _captain_html(name: str, *, tag: str = "span") -> str:
    """Consistent captain visual language (2026-08-21, third session,
    section 10: "don't spam gold, make gold meaningful") - one shared
    helper so the exact same gold treatment appears everywhere a captain's
    NAME is shown as a value (hero, AI Decisions, comparison) - the pitch's
    own gold ring/armband is a separate, already-established treatment for
    the player CARD itself, not duplicated here."""
    return f"<{tag} class='captain-name'>{_esc(name)}</{tag}>"


def _official_badge_url(team_code: int, size: int = 70) -> str:
    """Real official PL club crest (2026-08-21, second session, per direct
    LiveFPL/fpl.page study). Same official asset family as
    `_official_shirt_url`, confirmed live: `resources.premierleague.com/
    premierleague/badges/{size}/t{team_code}.png` - keyed by the same
    `teams.code` field the shirt asset already uses (verified: t3=Arsenal,
    t1=Man Utd, matching the shirt CDN's own team_code values exactly).
    Real precedent checked before adding this: fpl.page (a real, paid
    commercial FPL tool) hotlinks this exact same CDN path directly for its
    own fixture/template-team tables - the same class of usage this project
    already accepted for the kit shirt and (briefly) player photos, not a
    new risk category. Supersedes CLAUDE.md's earlier "crests deliberately
    not used, no license" note from before this evidence existed - see the
    session write-up for the explicit reversal."""
    return f"https://resources.premierleague.com/premierleague/badges/{size}/t{team_code}.png"


def _esc(text) -> str:
    return html.escape(str(text))


def _relative_time(iso_ts: str | None) -> str:
    if not iso_ts:
        return "unknown"
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    seconds = delta.total_seconds()
    if seconds < 0:
        future = -seconds
        if future < 3600:
            return f"in {int(future // 60)}m"
        if future < 86400:
            return f"in {int(future // 3600)}h"
        return f"in {int(future // 86400)}d"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _format_kickoff(iso_ts: str | None) -> str:
    """Real bug fixed 2026-08-21 ("live tracking looks ugly and makes no
    sense"): Live Tracking's fixture list and "Next kickoff" line were both
    printing the raw ISO-8601 string straight from the DB
    (`2026-08-21T19:00:00Z`) with zero formatting - a real, confirmed gap,
    not a design choice. Real, human-readable UTC form instead
    ("Thu 21 Aug, 19:00 UTC") - the no-JS fallback text inside
    `_local_time_span` below, not the primary display."""
    if not iso_ts:
        return "TBC"
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return "TBC"
    return ts.strftime("%a %d %b, %H:%M UTC")


def _local_time_span(iso_ts: str | None, css_class: str = "") -> str:
    """Real fix, 2026-08-21: "kickoff time isnt correct" - checked against
    FPL's own live API first (`/api/fixtures/?event=1`) and confirmed the
    synced UTC timestamp was already byte-identical to the real official
    one - not a data bug. The real cause: the official FPL app renders
    kickoff times in the VIEWER's own local timezone (standard browser
    `Date` conversion), and this dashboard was showing raw UTC instead -
    correct data, wrong frame of reference, genuinely "wrong" from the
    user's seat. Fixed the general, honest way rather than guessing/
    hardcoding one timezone (this project has no server-side IANA tzdata
    available on Windows either - confirmed live, `zoneinfo` fails without
    the `tzdata` package): emit the real UTC instant in a `data-utc`
    attribute and let a small inline script convert it to the actual
    viewer's browser-local timezone on load - correct for ANY viewer,
    handles DST automatically, zero new dependency. `_format_kickoff`'s
    UTC string is left in the element as the pre-JS/no-JS fallback text,
    so nothing breaks if scripts are disabled."""
    if not iso_ts:
        return "TBC"
    cls = f" {css_class}" if css_class else ""
    return f"<span class='local-time{cls}' data-utc='{_esc(iso_ts)}'>{_esc(_format_kickoff(iso_ts))}</span>"


def _health_summary_html(conn: sqlite3.Connection) -> str:
    """2026-08-21 fix: real usability gap found by looking at the actual
    live dashboard, not just the code - `panel-health` renders ~35 chips
    (readiness + every synced source) in one big grid, nearly all reading
    "OK" - a wall of green noise that buries the one row that might
    actually matter. A one-line rollup ("34/35 healthy" or naming the real
    degraded ones) now sits above the grid; the full chip list moves
    behind a native `<details>` (no JS needed, real semantic HTML,
    consistent with this project's own "don't add a dependency for
    something the platform already does" posture) so the detail is one
    click away, never hidden entirely."""
    readiness = run_readiness_checks(conn)
    sources = get_source_health(conn)
    total = len(readiness) + len(sources)
    bad_names = [c.name for c in readiness if c.status != "OK"]
    bad_names += [s.source_name for s in sources if s.failure_count != 0]
    if not bad_names:
        return f"<div class='health-summary health-summary-ok'><span class='dot'></span>{total}/{total} healthy</div>"
    names = ", ".join(_esc(n) for n in bad_names[:4])
    more = f" (+{len(bad_names) - 4} more)" if len(bad_names) > 4 else ""
    return (
        f"<div class='health-summary health-summary-warn'><span class='dot'></span>"
        f"{total - len(bad_names)}/{total} healthy - flagged: {names}{more}</div>"
    )


def _readiness_chips(conn: sqlite3.Connection) -> str:
    css = {"OK": "ok", "DEGRADED": "warn", "MISSING": "bad"}
    chips = []
    for c in run_readiness_checks(conn):
        cls = css.get(c.status, "warn")
        detail = f"<span class='chip-detail'>{_esc(c.detail)}</span>" if c.status != "OK" else ""
        chips.append(
            f"<div class='chip chip-{cls}'><span class='dot'></span>"
            f"<span class='chip-name'>{_esc(c.name)}</span>"
            f"<span class='chip-status'>{_esc(c.status)}</span>{detail}</div>"
        )
    return "\n".join(chips)


def _source_chips(conn: sqlite3.Connection) -> str:
    chips = []
    for s in get_source_health(conn):
        ok = s.failure_count == 0
        cls = "ok" if ok else "bad"
        status = "OK" if ok else "DEGRADED"
        chips.append(
            f"<div class='chip chip-{cls}'><span class='dot'></span>"
            f"<span class='chip-name'>{_esc(s.source_name)}</span>"
            f"<span class='chip-status'>{status}</span>"
            f"<span class='chip-detail'>{_esc(_relative_time(s.last_success))}</span></div>"
        )
    return "\n".join(chips)


_AVAILABILITY_SEVERITY = {
    "CONFIRMED UNAVAILABLE": ("action", "Action required"),
    "LIKELY UNAVAILABLE": ("action", "Action required"),
    "DOUBTFUL": ("monitor", "Monitor"),
    "FIT BUT MONITORED": ("low", "Low risk"),
}


def _risk_monitor_html(conn: sqlite3.Connection, squad_ids: set[int]) -> str:
    """Risk monitor (2026-08-21, direct user request, section 15) -
    severity-tiered rows instead of a plain bulleted list. Severity is
    derived from data this project already computes honestly:
    `models/availability.py::classify()`'s real 4-level Tier 1
    classification for a confirmed/official status, `models/team_news_risk.py`'s
    keyword-matched rotation hedges (always MONITOR tier, never ACTION -
    it's a heuristic signal over scraped text, not a confirmed status, and
    this project's own honesty convention never overstates a heuristic's
    certainty)."""
    rows = []
    for r in list_availability(conn, unavailable_only=True):
        if r.player_id not in squad_ids:
            continue
        cls, label = _AVAILABILITY_SEVERITY.get(r.classification, ("monitor", "Monitor"))
        detail = f"{_esc(r.classification)}{' - ' + _esc(r.news) if r.news else ''} ({_esc(r.team)})"
        rows.append(f"""<div class="risk-row">
  <span class="risk-severity risk-severity-{cls}">{label}</span>
  <span class="risk-body"><strong>{_esc(r.web_name)}</strong> &middot; {detail}</span>
</div>""")

    # Real qualitative rotation-risk signal (2026-08-21) - see
    # models/team_news_risk.py's module docstring for the real evidence this
    # closed (Osula/Gyokeres/Dorgu, previously invisible to this panel).
    for f in flag_squad_rotation_risk(conn, list(squad_ids)):
        rows.append(f"""<div class="risk-row">
  <span class="risk-severity risk-severity-monitor">Monitor</span>
  <span class="risk-body"><strong>{_esc(f.web_name)}</strong> &middot; rotation risk: &ldquo;{_esc(f.snippet)}&rdquo;</span>
</div>""")

    if not rows:
        return (
            "<div class='risk-row'><span class='risk-severity risk-severity-low'>Low risk</span>"
            "<span class='risk-body'>No availability or rotation concerns in your squad.</span></div>"
        )
    return "\n".join(rows)


def _player_card(
    c, *, is_captain: bool, is_vice: bool, lineup_info: dict | None = None, team_code: int | None = None,
    bench_order: int | None = None, next_fixture: tuple[str, bool, int] | None = None,
) -> str:
    light, dark = _POSITION_ACCENT.get(c.position, _POSITION_ACCENT["MID"])
    armband = ""
    if is_captain:
        armband = "<span class='armband cap' title='Captain'>C</span>"
    elif is_vice:
        armband = "<span class='armband vc' title='Vice-captain'>VC</span>"

    lineup_badge = ""
    lineup_tip_row = ""
    if lineup_info is not None:
        label, cls = _LINEUP_STATUS_LABEL.get(lineup_info["status"], ("?", "warn"))
        doubt = f" {lineup_info['doubt_percent']}%" if lineup_info.get("doubt_percent") is not None else ""
        # Real visual-noise fix (second polish pass): "starting" is the
        # overwhelming common case (nearly every card), so a saturated green
        # pill on every single card communicated nothing - reserved badge
        # treatment for the real exceptions (bench/doubt/out/banned) only.
        # "Starting" status is still always in the hover tooltip below.
        if lineup_info["status"] != "starting":
            lineup_badge = f"<span class='lineup-badge lineup-{cls}' title='predicted lineup'>{_esc(label)}{doubt}</span>"
        lineup_tip_row = f"<div class='player-tooltip-row'><span>Predicted</span><strong>{_esc(label)}{doubt}</strong></div>"

    # Real official FPL kit graphic (2026-08-21) - see _official_shirt_url's
    # own docstring for why this replaced both the hand-drawn SVG jersey and
    # the player-photo experiment earlier the same session: it's keyed by
    # TEAM (from live `players.team_id`), not by a per-player photo asset,
    # so it can never show a stale club after a transfer the way the photo
    # CDN did (confirmed real, live: Madueke's photo was still Chelsea,
    # `Last-Modified: Feb 2025`) - always genuinely current by construction.
    shirt_html = "<div class='shirt-fallback'></div>"
    if team_code is not None:
        shirt_url = _official_shirt_url(team_code, is_gkp=(c.position == "GKP"))
        shirt_html = f'<img class="player-shirt" src="{_esc(shirt_url)}" loading="lazy" alt="{_esc(c.team_short)} shirt">'

    bench_badge = f"<span class='bench-order'>{bench_order}</span>" if bench_order is not None else ""
    cap_class = " is-captain" if is_captain else ""

    # Hover/focus tooltip (2026-08-21 direct user request) - real data
    # already computed for this exact card (floor/median/ceiling/
    # confidence/expected_minutes are all real PlayerCandidate fields),
    # never a new query per card - would reintroduce the per-player N+1
    # query pattern this project already fixed once this session.
    # Real fixture-to-decision link (2026-08-21, fourth session, section
    # 11: "the user should understand their next fixture... without
    # manually hunting through another section") - the same real
    # opponent/difficulty data the Fixture Ticker itself renders, one
    # compact tooltip row, not a duplicated matrix.
    fixture_tip_row = ""
    if next_fixture is not None:
        opp, is_home, difficulty = next_fixture
        fdr_cls = _fdr_class(difficulty)
        fixture_tip_row = (
            "<div class='player-tooltip-row'><span>Next fixture</span>"
            f"<strong><span class='fdr-dot fdr-dot-{fdr_cls}'></span>{_esc(opp)} "
            f"{'(H)' if is_home else '(A)'} &middot; {_esc(_FIXTURE_QUALITY_LABEL[fdr_cls])}</strong></div>"
        )

    tooltip = f"""<div class="player-tooltip" role="tooltip">
    <div class="player-tooltip-row"><span>Price</span><strong>£{c.price_tenths / 10:.1f}m</strong></div>
    <div class="player-tooltip-row"><span>Floor &ndash; Ceiling</span><strong>{c.floor:.1f} &ndash; {c.ceiling:.1f}</strong></div>
    <div class="player-tooltip-row"><span>Confidence</span><strong>{_esc(c.confidence)}</strong></div>
    <div class="player-tooltip-row"><span>Exp. minutes</span><strong>{c.expected_minutes:.0f}&prime;</strong></div>
    {fixture_tip_row}
    {lineup_tip_row}
  </div>"""

    return f"""<div class="player-card{cap_class}" style="--accent-l:{light};--accent-d:{dark}" tabindex="0">
  {bench_badge}
  {armband}
  <div class="player-photo-wrap">
    {shirt_html}
  </div>
  <div class="player-name">{_esc(c.web_name)}</div>
  <div class="player-meta">{_esc(c.team_short)} &middot; £{c.price_tenths / 10:.1f}m</div>
  <div class="player-xp">{c.median:.1f} <span class="unit">xP</span></div>
  {lineup_badge}
  {tooltip}
</div>"""


def _pitch_html_from_xi(conn: sqlite3.Connection, xi, cap_id: int | None, vc_id: int | None) -> str:
    """Shared pitch renderer - takes a bare `StartingXI` + captain/vice ids so
    both the model's own recommendation (`_pitch_html`) and the user's REAL
    synced squad (`_real_team_pitch_html`, 2026-08-21) render identically
    rather than duplicating the card-layout logic per source."""
    if not xi.starting:
        return "<div class='empty-state'>No squad could be built from the current player pool.</div>"
    squad_ids = [c.player_id for c in xi.starting] + [c.player_id for c in xi.bench]
    lineup = get_predicted_lineup_for_squad(conn, squad_ids)
    team_codes = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM teams").fetchall()}

    # Per-team next-fixture cache (2026-08-21, fourth session) - a handful
    # of distinct teams across a 15-man squad, one `team_fixture_ticker`
    # call each (n_gw=1, the same real function the Fixture Ticker itself
    # uses), never one query per player.
    next_fixture_cache: dict[int, tuple[str, bool, int] | None] = {}

    def _next_fixture_for(team_id: int) -> tuple[str, bool, int] | None:
        if team_id not in next_fixture_cache:
            entries = team_fixture_ticker(conn, team_id, n_gw=1)
            next_fixture_cache[team_id] = (
                (entries[0].opponent_short, entries[0].is_home, entries[0].difficulty) if entries else None
            )
        return next_fixture_cache[team_id]

    by_position: dict[str, list] = {p: [] for p in _POSITION_ORDER}
    for c in xi.starting:
        by_position.setdefault(c.position, []).append(c)

    # Zone labels (2026-08-21 direct user request, section 9: "visually
    # separate GK/DEF/MID/FWD... use subtle positional labels") - real
    # position names, not decorative.
    _ZONE_LABEL = {"GKP": "Goalkeeper", "DEF": "Defence", "MID": "Midfield", "FWD": "Forwards"}

    rows = []
    for pos in _POSITION_ORDER:
        players = by_position.get(pos, [])
        if not players:
            continue
        cards = "\n".join(
            _player_card(c, is_captain=c.player_id == cap_id, is_vice=c.player_id == vc_id,
                         lineup_info=lineup.get(c.player_id), team_code=team_codes.get(c.team_id),
                         next_fixture=_next_fixture_for(c.team_id))
            for c in players
        )
        rows.append(
            f"<div class='pitch-zone'><div class='zone-label'>{_ZONE_LABEL[pos]}</div>"
            f"<div class='pitch-row' data-pos='{pos}'>{cards}</div></div>"
        )

    # Bench order (2026-08-21, section 10) - real, not fabricated: the
    # numbering reflects this project's own pick_starting_xi() fill order
    # (the actual order the model placed them in), not a guessed "official"
    # bench order (no real squad has one until a manager sets it).
    bench_cards = "\n".join(
        _player_card(c, is_captain=c.player_id == cap_id, is_vice=c.player_id == vc_id,
                     lineup_info=lineup.get(c.player_id), team_code=team_codes.get(c.team_id), bench_order=i + 1,
                     next_fixture=_next_fixture_for(c.team_id))
        for i, c in enumerate(xi.bench)
    )

    return f"""<div class="pitch">
{''.join(rows)}
</div>
<div class="bench-label">Bench</div>
<div class="pitch-row bench-row">{bench_cards}</div>"""


def _pitch_html(conn: sqlite3.Connection, report) -> str:
    if not report.structures or not report.structures[0].result.squad:
        return "<div class='empty-state'>No squad could be built from the current player pool.</div>"
    primary = report.structures[0]
    cap_id = report.captain.player_id if report.captain else None
    vc_id = report.vice.player_id if report.vice else None
    return _pitch_html_from_xi(conn, primary.xi, cap_id, vc_id)


def _real_team_html(conn: sqlite3.Connection, entry_id: int) -> str:
    """Real squad panel (2026-08-21) - the user's actual FPL team, fetched via
    `fpl my-team` from the real public entry API, never the model's own
    recommendation. Honest about the two real states this can be in:
    picks not fetched yet (pre-lock, or `fpl my-team` never run) vs a real
    synced squad, rated the same way `fpl rate-team`/`fpl my-team` do."""
    entry = conn.execute("SELECT manager_name, region_name FROM my_team_entry WHERE entry_id=?", (entry_id,)).fetchone()
    manager_line = f"<div class='real-team-manager'>{_esc(entry['manager_name'])} &middot; {_esc(entry['region_name'] or '')}</div>" if entry else ""

    history_rows = conn.execute(
        "SELECT season_name, total_points, rank, rank_percentage FROM my_team_season_history "
        "WHERE entry_id=? ORDER BY season_name DESC LIMIT 3", (entry_id,),
    ).fetchall()
    history_html = "".join(
        f"<div class='real-team-season'>{_esc(r['season_name'])}: {r['total_points']} pts, "
        f"rank {r['rank']:,} (top {_esc(r['rank_percentage'])}%)</div>" if r["rank"] is not None else ""
        for r in history_rows
    )

    latest = get_latest_squad(conn, entry_id)
    if latest is None:
        return (
            f"{manager_line}{history_html}"
            "<div class='empty-state'>Real squad not available yet - unlocks once your gameweek "
            "deadline passes and `fpl my-team` is re-run.</div>"
        )

    event, squad_ids = latest
    rating = rate_team(conn, squad_ids)
    pitch = _pitch_html_from_xi(conn, rating.xi, rating.captain.player_id if rating.captain else None,
                                 rating.vice.player_id if rating.vice else None)
    summary = conn.execute(
        "SELECT points, overall_rank, bank_tenths FROM my_team_gw_summary WHERE entry_id=? AND event=?",
        (entry_id, event),
    ).fetchone()
    stats = (
        f"<div class='real-team-stats'>GW{event} &middot; "
        f"{('real score: ' + str(summary['points']) + ' pts &middot; ') if summary and summary['points'] is not None else ''}"
        f"model xP: {rating.gw1_xp} &middot; {rating.efficiency_percent}% of best-achievable"
        "</div>"
    )
    return f"{manager_line}{history_html}{stats}{pitch}"


def _compare_panel_html(
    conn: sqlite3.Connection, entry_id: int, opt_xp: float, opt_value_m: float, opt_bank_m: float,
    opt_captain_name: str, opt_squad_ids: set[int],
) -> str:
    """"Your Team vs Optimized" (2026-08-21, direct user request, section
    11) - reorganizes real data that already existed in two separate,
    disconnected panels (the old standalone "My Real Team" panel and the
    stat-row's own optimized-squad numbers) into one real side-by-side
    comparison. Never fabricates a number for the side that isn't
    available yet - the real synced-squad metrics only appear once
    `fpl my-team` has real locked picks; until then, the real season-
    history numbers already available (manager identity, past-season
    points/rank) fill the "your team" side honestly, same empty-state
    posture `_real_team_html` already established."""
    entry = conn.execute("SELECT manager_name, region_name FROM my_team_entry WHERE entry_id=?", (entry_id,)).fetchone()
    manager_name = entry["manager_name"] if entry else f"Entry {entry_id}"

    latest_history = conn.execute(
        "SELECT season_name, total_points, rank, rank_percentage FROM my_team_season_history "
        "WHERE entry_id=? ORDER BY season_name DESC LIMIT 1", (entry_id,),
    ).fetchone()

    latest = get_latest_squad(conn, entry_id)
    your_metrics = []
    pitch_html = ""
    delta_html = ""
    if latest is not None:
        event, squad_ids = latest
        rating = rate_team(conn, squad_ids)
        your_metrics = [
            ("GW", f"{event}"),
            ("Real xP", f"{rating.gw1_xp}"),
            ("Efficiency", f"{rating.efficiency_percent}% of best"),
        ]
        pitch_html = (
            "<div class='bench-label' style='margin-top:18px'>Your real synced squad</div>"
            + _pitch_html_from_xi(conn, rating.xi, rating.captain.player_id if rating.captain else None,
                                   rating.vice.player_id if rating.vice else None)
        )
        # Real "what changes" delta strip (2026-08-21, third session,
        # section 13) - every figure here is a plain diff of two already-
        # computed real values (rating.gw1_xp vs opt_xp, a set difference of
        # two already-fetched squad id lists, a captain-name string
        # compare) - no new modelling, no fabricated metric.
        point_delta = opt_xp - rating.gw1_xp
        changed_players = len(set(squad_ids) - opt_squad_ids)
        your_cap_name = rating.captain.web_name if rating.captain else None
        captain_changed = your_cap_name is not None and your_cap_name != opt_captain_name
        delta_parts = [f"<span class='compare-delta-pt {'pos' if point_delta >= 0 else 'neg'}'>"
                       f"{'+' if point_delta >= 0 else ''}{point_delta:.1f} xP</span>"]
        if changed_players:
            delta_parts.append(f"{changed_players} player change{'s' if changed_players != 1 else ''}")
        if captain_changed:
            delta_parts.append(f"captain: {_esc(your_cap_name)} &rarr; {_captain_html(opt_captain_name)}")
        delta_html = f"<div class='compare-delta'>{' &middot; '.join(delta_parts)}</div>"
    elif latest_history is not None and latest_history["rank"] is not None:
        your_metrics = [
            (_esc(latest_history["season_name"]), f"{latest_history['total_points']} pts"),
            ("Rank", f"{latest_history['rank']:,} (top {_esc(latest_history['rank_percentage'])}%)"),
        ]

    if not your_metrics:
        your_side = "<div class='empty-state'>Real squad not available yet - unlocks once your gameweek deadline passes and `fpl my-team` is re-run.</div>"
    else:
        your_side = "".join(
            f"<div class='compare-metric'><span>{_esc(label)}</span>"
            f"<span class='compare-metric-value'>{_esc(value)}</span></div>"
            for label, value in your_metrics
        )

    optimized_side = "".join([
        f"<div class='compare-metric'><span>Projected xP</span><span class='compare-metric-value'>{opt_xp:.1f}</span></div>",
        f"<div class='compare-metric'><span>Captain</span><span class='compare-metric-value'>{_captain_html(opt_captain_name)}</span></div>",
        f"<div class='compare-metric'><span>Squad value</span><span class='compare-metric-value'>£{opt_value_m:.1f}m</span></div>",
        f"<div class='compare-metric'><span>Bank</span><span class='compare-metric-value'>£{opt_bank_m:.1f}m</span></div>",
    ])

    return f"""{delta_html}<div class="compare-grid">
  <div class="compare-side">
    <div class="compare-label">Your Team &middot; {_esc(manager_name)}</div>
    {your_side}
  </div>
  <div class="compare-vs">VS</div>
  <div class="compare-side compare-optimized">
    <div class="compare-label">Optimized Team</div>
    {optimized_side}
  </div>
</div>
{pitch_html}"""


@dataclass(frozen=True)
class _LiveWindow:
    state: str  # "pre" | "live" | "post" | "unknown"
    event: int | None
    next_kickoff: str | None
    fixtures_text: str


def _squad_live_window(conn: sqlite3.Connection, squad_ids: set[int]) -> _LiveWindow:
    event = live_or_reference_event(conn)
    if event is None:
        return _LiveWindow("unknown", None, None, "")

    team_rows = conn.execute(
        "SELECT DISTINCT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
        tuple(squad_ids),
    ).fetchall() if squad_ids else []
    team_ids = {r["team_id"] for r in team_rows}

    fixtures_raw = conn.execute(
        "SELECT f.id, f.kickoff_time, f.started, f.finished, th.short_name AS home, ta.short_name AS away, "
        "th.code AS home_code, ta.code AS away_code "
        "FROM fixtures f JOIN teams th ON th.id=f.team_h JOIN teams ta ON ta.id=f.team_a "
        "WHERE f.event=? AND (f.team_h IN ({ids}) OR f.team_a IN ({ids})) ORDER BY f.kickoff_time".format(
            ids=",".join("?" * len(team_ids)) if team_ids else "-1"
        ),
        (event, *team_ids, *team_ids) if team_ids else (event,),
    ).fetchall()

    if not fixtures_raw:
        return _LiveWindow("unknown", event, None, "")

    # Real gap found live 2026-08-21 (the actual Arsenal v Coventry match's
    # own real full-time): FPL's own `fixtures.finished` only updates on the
    # regular (15min-6h, deadline-aware) scheduler cadence - the whole point
    # of this session's live-match-poller pass was a FASTER real source
    # (FotMob via match_intelligence, ~25s). Without this override, "My
    # Live Score"/the hero state stayed stuck on LIVE for many real minutes
    # after the match had actually finished, purely waiting on the slower
    # source to catch up - confirmed live, not hypothetical. `finished` is
    # overridden to true only when match_intelligence has a real FULL_TIME
    # row for that exact fixture (via fpl_fixture_id) - never the reverse
    # (a stale/absent FotMob row never un-finishes a fixture FPL's own API
    # already confirmed finished).
    mi_full_time = {
        r["fpl_fixture_id"] for r in conn.execute(
            "SELECT fpl_fixture_id FROM match_intelligence WHERE status='FULL_TIME' AND fpl_fixture_id IS NOT NULL"
        ).fetchall()
    }
    fixtures = [
        {**dict(f), "finished": 1 if (f["finished"] or f["id"] in mi_full_time) else 0}
        for f in fixtures_raw
    ]

    any_live = any(f["started"] and not f["finished"] for f in fixtures)
    all_finished = all(f["finished"] for f in fixtures)
    state = "live" if any_live else ("post" if all_finished else "pre")

    # Real visual redesign, 2026-08-21 ("live tracking... so damn ugly") -
    # real match cards (team shirts, not a plain text row) instead of a flat
    # list, same official shirt asset the squad pitch already uses
    # (_official_shirt_url) so a squad member's actual club is instantly
    # recognizable here too, not just on their own player card.
    lines = []
    next_kickoff = None
    last_date = None
    for f in fixtures:
        if not f["started"] and next_kickoff is None:
            next_kickoff = f["kickoff_time"]
        if f["started"] and not f["finished"]:
            state_badge = "<span class='fx-badge fx-badge-live'><span class='pulse-dot small'></span>LIVE</span>"
        elif f["finished"]:
            state_badge = "<span class='fx-badge fx-badge-ft'>FT</span>"
        else:
            state_badge = _local_time_span(f["kickoff_time"], css_class="fx-badge fx-badge-pre")
        # Real date-group divider (2026-08-21, per fpl.page's own full-width
        # date-header rows) - GW1's real fixtures genuinely span multiple
        # days (Sat through Tue, confirmed live), so grouping by real
        # kickoff date turns a flat list into an actual schedule. Real bug
        # caught live while verifying this: grouping by the raw server-side
        # UTC date could disagree with the badge next to it (converted to
        # the viewer's own local timezone by the script below), producing
        # e.g. "MON 24 AUG" sitting directly above a "Tue, Aug 25" kickoff -
        # the exact class of bug already fixed once for kickoff times
        # itself. Fixed the same way: carry data-utc and let the same
        # client-side conversion correct the label to the viewer's real
        # local date, same as .local-time spans.
        this_date = _format_kickoff(f["kickoff_time"]).split(",")[0] if f["kickoff_time"] else None
        if this_date and this_date != last_date:
            lines.append(
                f"<div class='fx-date-divider' data-utc='{_esc(f['kickoff_time'])}'>{_esc(this_date)}</div>"
            )
            last_date = this_date
        # Real asset-language correction (2026-08-21, third session, section
        # 2: "use shirts for PLAYER identity, crests for CLUB identity").
        # This card represents two CLUBS in a fixture, not a specific
        # player - crests replace the shirt icons used here before.
        lines.append(f"""<div class="fx-card">
  <div class="fx-side"><img class="fx-crest" src="{_esc(_official_badge_url(f['home_code']))}" alt="">
    <span class="fx-code">{_esc(f['home'])}</span></div>
  <div class="fx-mid">{state_badge}</div>
  <div class="fx-side"><img class="fx-crest" src="{_esc(_official_badge_url(f['away_code']))}" alt="">
    <span class="fx-code">{_esc(f['away'])}</span></div>
</div>""")

    return _LiveWindow(state, event, next_kickoff, "\n".join(lines))


def _live_tracking_html(conn: sqlite3.Connection, squad_ids: set[int], live_payload: dict | None) -> str:
    window = _squad_live_window(conn, squad_ids)

    if window.state == "unknown":
        return "<div class='empty-state'>No fixtures found for your squad's teams in the reference gameweek yet.</div>"

    if window.state == "pre":
        return (
            "<div class='live-pending'><span class='pulse-dot'></span>"
            "Live tracking activates automatically once these matches kick off - "
            "goals, assists, and provisional bonus will appear here in real time.</div>"
            f"<div class='live-next'>Next kickoff: <strong>{_local_time_span(window.next_kickoff)}</strong></div>"
            f"<div class='fixture-grid'>{window.fixtures_text}</div>"
        )

    if window.state == "live" and live_payload:
        rows = compute_live_bonus(conn, live_payload)
        squad_rows = [r for r in rows if r.player_id in squad_ids]
        if not squad_rows:
            return "<div class='empty-state'>Match in progress - none of your squad have registered minutes yet.</div>"
        lines = []
        for r in squad_rows:
            confirmed = f"<span class='bonus-confirmed'>{r.confirmed_bonus} confirmed</span>" if r.confirmed_bonus is not None else "<span class='bonus-provisional'>provisional</span>"
            # DEFCON progress (2026-08-21, live-gameweek layer item 2/4) -
            # only rendered for a real eligible position (defcon_threshold
            # is None for GKP, and absent/0 for a player this source hasn't
            # covered) - never shown as a fabricated "0/10" for someone the
            # rule doesn't apply to.
            defcon_html = ""
            if r.defcon_threshold is not None:
                defcon_cls = "defcon-reached" if r.defcon_reached else "defcon-progress"
                defcon_label = "DEFCON +2" if r.defcon_reached else "DefCon"
                defcon_html = (
                    f"<span class='live-stat {defcon_cls}'>{_esc(defcon_label)} "
                    f"{r.defensive_contribution}/{r.defcon_threshold}</span>"
                )
            lines.append(
                f"<div class='live-row'><span class='pulse-dot small'></span>"
                f"<strong>{_esc(r.web_name)}</strong>"
                f"<span class='live-stat'>{r.minutes}&prime;</span>"
                f"<span class='live-stat'>{r.goals_scored}G {r.assists}A</span>"
                f"<span class='live-stat'>BPS {r.bps}</span>"
                f"{defcon_html}"
                f"<span class='bonus-badge'>+{r.provisional_bonus}</span>{confirmed}</div>"
            )
        return "<div class='live-active'>" + "\n".join(lines) + "</div>"

    if window.state == "live" and not live_payload:
        return "<div class='warn-state'>A match involving your squad is in progress, but live data could not be fetched this cycle - it will retry next refresh.</div>"

    return "<div class='empty-state'>Gameweek finished. Bonus points are confirmed by FPL a few hours after full-time - check back shortly.</div>"


_CHANGE_CATEGORY_LABEL = {
    "status_change": "availability", "new_player": "new", "removed_player": "removed", "club_change": "transfer",
    "predicted_lineup_change": "lineup", "start_percent_change": "start%", "kickoff_reminder": "kickoff",
}
_STATUS_LABELS = {"a": "available", "i": "injured", "s": "suspended", "u": "unavailable", "d": "doubtful"}
# Real severity rank (best -> worst) over the exact same status codes FPL's
# own API returns - used only to color the Activity feed's dot (a -> better,
# u -> worse), never a new classification: same real vocabulary
# models/availability.py already treats as a rank, just read here for a
# quiet visual direction indicator instead of _AVAILABILITY_SEVERITY's
# 4-tier action/monitor/low labeling.
_STATUS_RANK = {"a": 0, "d": 1, "i": 2, "s": 2, "u": 3}


def _status_change_dot_class(event_type: str, old_value, new_value) -> str:
    if event_type != "status_change":
        return "neutral"
    old_r, new_r = _STATUS_RANK.get(old_value), _STATUS_RANK.get(new_value)
    if old_r is None or new_r is None:
        return "neutral"
    if new_r < old_r:
        return "good"
    if new_r > old_r:
        return "bad"
    return "neutral"


def _describe_change_event(conn: sqlite3.Connection, event_type: str, entity_id: int, old_value, new_value) -> str:
    player = conn.execute("SELECT web_name FROM players WHERE id=?", (entity_id,)).fetchone()
    name = player["web_name"] if player else f"player #{entity_id}"

    if event_type == "new_player":
        return f"<strong>{_esc(name)}</strong> added to the FPL database"
    if event_type == "removed_player":
        return f"<strong>{_esc(name)}</strong> removed from the FPL database"
    if event_type == "club_change":
        old_team = conn.execute("SELECT short_name FROM teams WHERE id=?", (old_value,)).fetchone()
        new_team = conn.execute("SELECT short_name FROM teams WHERE id=?", (new_value,)).fetchone()
        old_t = old_team["short_name"] if old_team else "?"
        new_t = new_team["short_name"] if new_team else "?"
        return f"<strong>{_esc(name)}</strong> moved club: {_esc(old_t)} &rarr; {_esc(new_t)}"
    if event_type == "status_change":
        old_s = _STATUS_LABELS.get(old_value, old_value or "?")
        new_s = _STATUS_LABELS.get(new_value, new_value or "?")
        return f"<strong>{_esc(name)}</strong> status: {_esc(old_s)} &rarr; {_esc(new_s)}"
    if event_type == "predicted_lineup_change":
        old_s = old_value or "unknown"
        new_s = new_value or "dropped from lineup coverage"
        return f"<strong>{_esc(name)}</strong> predicted status: {_esc(old_s)} &rarr; {_esc(new_s)}"
    if event_type == "start_percent_change":
        return f"<strong>{_esc(name)}</strong> start probability: {_esc(str(old_value))}% &rarr; {_esc(str(new_value))}%"
    if event_type == "kickoff_reminder":
        fixture = conn.execute(
            "SELECT ht.short_name AS home, at.short_name AS away FROM fixtures f "
            "JOIN teams ht ON ht.id = f.team_h JOIN teams at ON at.id = f.team_a WHERE f.id=?",
            (entity_id,),
        ).fetchone()
        matchup = f"{fixture['home']} v {fixture['away']}" if fixture else f"fixture #{entity_id}"
        return f"<strong>{_esc(matchup)}</strong> kicks off soon ({_esc(_format_kickoff(new_value))})"
    return f"<strong>{_esc(name)}</strong> {_esc(event_type)}"


def _squad_changes_html(conn: sqlite3.Connection, limit: int = 10) -> str:
    """Tier 1 FACTS straight from the change-detection engine (not RSS news) -
    a player genuinely added to/removed from FPL's own database, moved club,
    or had their official availability status change. Real per-team squad
    churn, not a fabricated feed - only fires when `change_detection.py`
    actually recorded something, which only covers deltas since this
    project started polling (see CLAUDE.md's cross-competition/transfer-
    window sections for the honest caveat on pre-polling history)."""
    placeholders = ",".join("?" * len(_CHANGE_EVENT_TYPES))
    rows = conn.execute(
        f"SELECT event_type, entity_id, old_value, new_value, detected_at FROM change_events "
        f"WHERE event_type IN ({placeholders}) ORDER BY detected_at DESC LIMIT ?",
        (*_CHANGE_EVENT_TYPES, limit),
    ).fetchall()
    if not rows:
        return "<div class='empty-state'>No squad changes detected yet this session.</div>"
    lines = []
    for r in rows:
        desc = _describe_change_event(conn, r["event_type"], r["entity_id"], r["old_value"], r["new_value"])
        dot_cls = _status_change_dot_class(r["event_type"], r["old_value"], r["new_value"])
        # Real event-category tag (2026-08-21, third session, section 15:
        # "TIME / EVENT TYPE / ENTITY / CHANGE") - the real event_type this
        # row's own change_events row already carries, just labeled for a
        # human instead of shown only via the description sentence.
        category = _CHANGE_CATEGORY_LABEL.get(r["event_type"], r["event_type"])
        lines.append(
            f"<div class='change-item'><span class='change-dot change-dot-{dot_cls}' title='{dot_cls}'></span>"
            f"<span class='change-category'>{_esc(category)}</span>"
            f"<span class='change-desc'>{desc}</span>"
            f"<span class='change-time'>{_esc(_relative_time(r['detected_at']))}</span></div>"
        )
    return "\n".join(lines)


def _price_changes_html(conn: sqlite3.Connection, limit: int = 8) -> str:
    """Real, already-tracked price moves (player_price_history's own
    valid_from/valid_until change-tracking, no new schema) - each player's
    most recently-superseded price row paired with their current one,
    ordered by when the change actually happened. Direct answer to "we get
    new data on every batch, show me what changed" (2026-08-20) - a real
    per-sync delta feed, not just a static snapshot."""
    rows = conn.execute(
        "SELECT old.player_id, old.value_tenths AS old_value, cur.value_tenths AS new_value, "
        "old.valid_until AS changed_at, p.web_name, t.short_name AS team "
        "FROM player_price_history old "
        "JOIN player_price_history cur ON cur.player_id = old.player_id AND cur.valid_until IS NULL "
        "JOIN players p ON p.id = old.player_id "
        "JOIN teams t ON t.id = p.team_id "
        "WHERE old.valid_until IS NOT NULL AND old.value_tenths != cur.value_tenths "
        "ORDER BY old.valid_until DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "<div class='empty-state'>No price changes yet this preseason - the honest state, not a gap.</div>"
    lines = []
    for r in rows:
        rose = r["new_value"] > r["old_value"]
        arrow = "&#9650;" if rose else "&#9660;"
        cls = "price-up" if rose else "price-down"
        lines.append(
            f"<div class='price-item'><span class='{cls}'>{arrow}</span> "
            f"<strong>{_esc(r['web_name'])}</strong> <span class='fx-teams'>{_esc(r['team'])}</span> "
            f"£{r['old_value']/10:.1f}m &rarr; £{r['new_value']/10:.1f}m"
            f"<span class='change-time'>{_esc(_relative_time(r['changed_at']))}</span></div>"
        )
    return "\n".join(lines)


def _news_html(conn: sqlite3.Connection, squad_ids: set[int], limit: int = 6) -> str:
    """Editorial-feed emphasis (2026-08-21, third session, section 14):
    "important news subtle emphasis, normal news quiet - do NOT give every
    article equal visual weight." "Important" is derived, not fabricated -
    an item this project's own name-matching already linked to a player or
    team actually IN the squad (checked by substring against the real
    web_name/short_name values already fetched for the pitch, same
    real-world matching this project already uses elsewhere, e.g.
    team_news_risk.py) - never a guessed relevance score."""
    items = list_recent_news(conn, limit=limit)
    if not items:
        return "<div class='empty-state'>No recent news synced yet - run <code>fpl sync-news</code>.</div>"

    squad_web_names: set[str] = set()
    squad_team_shorts: set[str] = set()
    if squad_ids:
        for row in conn.execute(
            "SELECT p.web_name, t.short_name FROM players p JOIN teams t ON t.id = p.team_id "
            "WHERE p.id IN ({})".format(",".join("?" * len(squad_ids))),
            tuple(squad_ids),
        ).fetchall():
            squad_web_names.add(row["web_name"])
            squad_team_shorts.add(row["short_name"])

    lines = []
    for n in items:
        tags = []
        if n.get("players"):
            tags.append(f"<span class='tag'>{_esc(n['players'])}</span>")
        if n.get("teams"):
            tags.append(f"<span class='tag tag-team'>{_esc(n['teams'])}</span>")
        players_str = n.get("players") or ""
        teams_str = n.get("teams") or ""
        is_relevant = (
            any(name in players_str for name in squad_web_names)
            or any(short in teams_str.split(", ") for short in squad_team_shorts)
        )
        item_cls = "news-item news-item-relevant" if is_relevant else "news-item"
        relevance_tag = "<span class='news-relevance'>your squad</span>" if is_relevant else ""
        lines.append(
            f"<div class='{item_cls}'>"
            f"<div class='news-title'><a href='{_esc(n['link'])}' target='_blank' rel='noopener'>{_esc(n['title'])}</a></div>"
            f"<div class='news-meta'><span class='source-tag'>{_esc(n['source_tier'] or 'news')}</span>"
            f"<span class='news-time'>{_esc(_relative_time(n['published_at']))}</span>{relevance_tag}{''.join(tags)}</div>"
            f"</div>"
        )
    return "\n".join(lines)


def _truncate(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _team_outlook_html(conn: sqlite3.Connection, squad_ids: set[int]) -> str:
    """The "automatic football pundit" panel (2026-08-21) - real squad churn,
    predicted formation, corroborated manager-change signal, and the latest
    team-news paragraph for every club represented in the squad. Every field
    traces to a DB row already synced - see models/team_outlook.py."""
    if not squad_ids:
        return "<div class='empty-state'>No squad to build an outlook for yet.</div>"
    outlooks = squad_team_outlooks(conn, list(squad_ids))
    if not outlooks:
        return "<div class='empty-state'>No team outlook data yet.</div>"

    churn_cls = lambda ratio: "bad" if (ratio or 0) >= 0.15 else ("warn" if (ratio or 0) >= 0.07 else "ok")
    team_codes = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM teams").fetchall()}
    cards = []
    for o in outlooks:
        churn_dot_cls = churn_cls(o.churn_ratio) if o.churn_ratio is not None else "warn"
        extras = []
        if o.formation:
            extras.append(f"<span class='outlook-chip'>{_esc(o.formation)}</span>")
        if o.manager_change:
            extras.append(f"<span class='outlook-chip outlook-alert'>manager change signal</span>")
        if o.qualitative and o.qualitative.current_tactical_signal:
            extras.append(f"<span class='outlook-chip'>{_esc(o.qualitative.current_tactical_signal)}</span>")
        # Real fixture-quality signal (2026-08-21, third session, section
        # 16: "team outlook should feel like an intelligence layer over the
        # fixture ticker") - the same real avg-difficulty read the ticker
        # itself is built from, not a separate metric.
        quality = _fixture_quality(conn, o.team_id)
        quality_html = (
            f"<div class='outlook-fixtures'><span class='dot dot-{quality[0]}'></span>"
            f"Next 5: {_esc(quality[1])} run</div>"
        ) if quality else ""
        badge_url = _official_badge_url(team_codes.get(o.team_id, 0))
        # Real, structurally-derived tactical pattern (manager_intelligence.py,
        # 2026-08-22) - only rendered once >=2 real matches exist to say
        # anything honest about it (o.tactics.note is None in that case).
        tactics_html = (
            f"<div class='outlook-fixtures'><span class='dot dot-ok'></span>"
            f"Typically {_esc(o.tactics.most_common_formation or '?')}, "
            f"rotation {o.tactics.starting_xi_rotation_rate}</div>"
        ) if o.tactics and o.tactics.note is None else ""
        cards.append(f"""<div class="outlook-card">
  <div class="outlook-head"><img class="outlook-badge" src="{_esc(badge_url)}" alt="">
    <strong>{_esc(o.team_name)}</strong>{''.join(extras)}</div>
  <div class="outlook-churn"><span class="dot dot-{churn_dot_cls}"></span>{_esc(o.churn_label)}</div>
  {quality_html}
  {tactics_html}
  {"<div class='outlook-news'>" + _esc(_truncate(o.lineup_news)) + "</div>" if o.lineup_news else ""}
</div>""")
    return "\n".join(cards)


_FDR_TICKS = 5  # real FPL Copilot default - matches the "5 matches" the user actually meant


def _fdr_class(difficulty: int) -> str:
    if difficulty <= 2:
        return "ok"
    if difficulty == 3:
        return "warn"
    return "bad"


def _cached_fixture_goals_for(conn: sqlite3.Connection, fixture_row, team_id: int, cache: dict) -> tuple[float, float]:
    """Per-render memoization keyed on fixture_id (2026-08-21 perf fix - see
    CLAUDE.md "Dashboard regen performance" continuation item). The ticker
    calls this twice for every real fixture (once from each involved team's
    own row), and `_fixture_goals_for`/`_blended_fixture_goals` does the
    exact same Dixon-Coles-fit-lookup + odds-devig work both times - only the
    (team, opponent) vs (opponent, team) output ORDERING differs, not the
    underlying computation. Caches the true (home_goals, away_goals) once per
    fixture_id and re-orients from that cached pair for the second team,
    instead of recomputing. Local to one `_fixture_ticker_html` call (a plain
    dict, not the module-level `(id(conn), ...)`-keyed caches elsewhere in
    this project) - the ticker is the only caller, and a fixture's blended
    goals estimate can legitimately change between renders (a fresh odds
    sync, a fresh Dixon-Coles fit), so nothing here should outlive one
    render."""
    fixture_id = fixture_row["id"]
    if fixture_id not in cache:
        home_team_id = fixture_row["team_h"]
        cache[fixture_id] = _fixture_goals_for(conn, fixture_row, home_team_id)
    home_goals, away_goals = cache[fixture_id]
    if team_id == fixture_row["team_h"]:
        return home_goals, away_goals
    return away_goals, home_goals


_LIVE_STALENESS_SECONDS = 90  # while a match is LIVE/HALFTIME, data older than this reads as delayed, not fresh


def _seconds_since(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(int((datetime.now(timezone.utc) - ts).total_seconds()), 0)


def _match_feed_html(conn: sqlite3.Connection, match_id: int, limit: int = 15) -> str:
    """Real match incidents (migration 0025, live-match-feed pass) - never
    LLM-authored, straight from FotMob's own structured event/shot data
    (see models/match_intelligence.py::parse_match_events's own docstring
    for exactly what is and isn't available). Most recent first - standard
    live-ticker convention."""
    rows = conn.execute(
        "SELECT me.minute, me.event_type, me.description, p.web_name AS player_web_name "
        "FROM match_events me LEFT JOIN players p ON p.id = me.player_id "
        "WHERE me.match_id=? ORDER BY me.minute DESC, me.id DESC LIMIT ?",
        (match_id, limit),
    ).fetchall()
    if not rows:
        return "<div class='empty-state'>No match events recorded yet.</div>"
    items = []
    for r in rows:
        minute_label = f"{_esc(str(r['minute']))}&prime;" if r["minute"] is not None else "&mdash;"
        items.append(
            f"<div class='match-feed-item'><span class='match-feed-minute'>{minute_label}</span>"
            f"<span class='match-feed-type'>{_esc(r['event_type'])}</span>"
            f"<span class='match-feed-desc'>{_esc(r['description'])}</span></div>"
        )
    return "<div class='match-feed'>" + "\n".join(items) + "</div>"


def _match_your_players_html(conn: sqlite3.Connection, match_id: int, home_team_id: int | None,
                              away_team_id: int | None, squad_ids: set[int]) -> str:
    """Real per-match FotMob state (minutes/goals/assists/rating) for locked-
    squad members involved in THIS match - deliberately separate from the
    Live Tracking panel's own FPL-official BPS/DEFCON/provisional-bonus
    numbers (a different real source, see fpl live-bonus) - section 10's
    ownership split: raw football state here, fantasy-scoring state there."""
    team_ids = [t for t in (home_team_id, away_team_id) if t is not None]
    if not squad_ids or not team_ids:
        return "<div class='empty-state'>No locked-squad players in this match.</div>"
    placeholders = ",".join("?" * len(squad_ids))
    team_placeholders = ",".join("?" * len(team_ids))
    rows = conn.execute(
        f"SELECT p.web_name, pms.minutes, pms.goals, pms.assists, pms.rating, pms.started "
        f"FROM players p LEFT JOIN player_match_state pms ON pms.player_id = p.id AND pms.match_id=? "
        f"WHERE p.id IN ({placeholders}) AND p.team_id IN ({team_placeholders})",
        (match_id, *squad_ids, *team_ids),
    ).fetchall()
    if not rows:
        return "<div class='empty-state'>No locked-squad players in this match.</div>"
    items = []
    for r in rows:
        # Real gap in the underlying per-match state, not fabricated around:
        # `minutes` can be None while a match is genuinely LIVE even for a
        # real starter (FotMob's own live minutes field isn't always
        # populated mid-match) - `started` is the honest signal for
        # "is this player actually playing right now", checked first.
        if r["started"]:
            bits = []
            if r["minutes"] is not None:
                bits.append(f"{_esc(str(r['minutes']))}&prime;")
            if r["goals"]:
                bits.append(f"{r['goals']}G")
            if r["assists"]:
                bits.append(f"{r['assists']}A")
            if r["rating"] is not None:
                bits.append(f"rating {r['rating']:.1f}")
            detail = " &middot; ".join(bits) if bits else "on the pitch"
        elif r["started"] == 0:
            detail = f"{_esc(str(r['minutes']))}&prime; (sub)" if r["minutes"] else "unused sub"
        else:
            detail = "no data for this match yet"
        items.append(f"<div class='match-feed-item'><span class='match-feed-desc'><strong>{_esc(r['web_name'])}</strong> {detail}</span></div>")
    return "<div class='match-feed'>" + "\n".join(items) + "</div>"


def _squad_play_status_counts(conn: sqlite3.Connection, player_ids, event: int | None) -> dict[str, int]:
    """Real per-player played/live/yet-to-play classification for a squad
    (dashboard-state pass, 2026-08-21) - one of the primary LIVE-state
    questions ("how much of my team is still exposed to the remaining
    fixtures"). A player with 2+ fixtures this event (a real double
    gameweek) is "live" if ANY of them is in progress, "played" only once
    ALL of them are finished - never fabricated for a blank-gameweek player
    (fixture_count=0 - correctly "yet to play", nothing to contradict that
    reading)."""
    counts = {"played": 0, "live": 0, "yet_to_play": 0}
    if not player_ids or event is None:
        counts["yet_to_play"] = len(player_ids or [])
        return counts
    placeholders = ",".join("?" * len(player_ids))
    rows = conn.execute(
        f"SELECT p.id AS player_id, "
        f"MAX(CASE WHEN f.started=1 AND f.finished=0 THEN 1 ELSE 0 END) AS any_live, "
        f"MIN(COALESCE(f.finished, 0)) AS all_finished, COUNT(f.id) AS fixture_count "
        f"FROM players p LEFT JOIN fixtures f ON (f.team_h = p.team_id OR f.team_a = p.team_id) AND f.event=? "
        f"WHERE p.id IN ({placeholders}) GROUP BY p.id",
        (event, *player_ids),
    ).fetchall()
    for r in rows:
        if r["fixture_count"] == 0:
            counts["yet_to_play"] += 1
        elif r["any_live"]:
            counts["live"] += 1
        elif r["all_finished"]:
            counts["played"] += 1
        else:
            counts["yet_to_play"] += 1
    return counts


@dataclass(frozen=True)
class _MyLiveScore:
    points: float
    captain_points: float | None
    captain_name: str | None
    played: int
    live: int
    yet_to_play: int
    bench: int


def _compute_my_live_score(conn: sqlite3.Connection, locked, live_payload: dict | None, event: int | None) -> "_MyLiveScore | None":
    """Real "My Live Score" (dashboard-state pass, 2026-08-21) - the single
    most-requested LiveFPL/FPL.page-style metric this project didn't have.
    `estimate_squad_live_points` already exists (built for `fpl live-rank`)
    and reads FPL's own already-computed live `total_points` per element
    (provisional bonus included) - reused, not reimplemented. Real
    multipliers preferred from the actual synced squad (`source==
    "synced_real"`, ground truth incl. any real chip) - the locked_decision
    fallback (no real sync yet) approximates captain=2x/starters=1x/bench=0x
    and is labeled as a projection, never presented as the real score."""
    if locked is None or live_payload is None:
        return None
    if locked.source == "synced_real":
        entry_id = None
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key='my_team_entry_id'"
        ).fetchone()
        entry_id = int(row["value"]) if row else None
        if entry_id is None:
            return None
        picks_rows = conn.execute(
            "SELECT player_id, multiplier FROM my_team_picks WHERE entry_id=? AND event=?",
            (entry_id, locked.event),
        ).fetchall()
        picks = [(r["player_id"], r["multiplier"]) for r in picks_rows]
    else:
        starter_ids = {c.player_id for c in locked.xi.starting}
        cap_id = locked.xi.captain.player_id if locked.xi.captain else None
        picks = [(pid, 2 if pid == cap_id else 1) for pid in starter_ids]

    points = estimate_squad_live_points(picks, live_payload)
    stats_by_id = {e["id"]: e.get("stats", {}) for e in live_payload.get("elements", []) if "id" in e}
    cap = locked.xi.captain
    cap_points = None
    if cap is not None:
        cap_stats = stats_by_id.get(cap.player_id)
        if cap_stats is not None:
            multiplier = next((m for pid, m in picks if pid == cap.player_id), 2)
            cap_points = cap_stats.get("total_points", 0) * multiplier

    all_ids = [c.player_id for c in locked.xi.starting]
    status = _squad_play_status_counts(conn, all_ids, event)
    return _MyLiveScore(
        points=points, captain_points=cap_points, captain_name=cap.web_name if cap else None,
        played=status["played"], live=status["live"], yet_to_play=status["yet_to_play"],
        bench=len(locked.xi.bench),
    )


def _dashboard_state(squad_window_state: str) -> str:
    """The one real signal driving the dashboard's three product states
    (2026-08-21, dashboard-state pass) - reuses `_squad_live_window`'s
    already-real pre/live/post/unknown classification (no new detection
    logic, no second source of truth). "unknown" (no fixtures resolvable
    for the squad's own teams at all) reads as PRE_DEADLINE - the honest
    default when there's nothing live to report."""
    return {"live": "LIVE", "post": "POST_MATCH"}.get(squad_window_state, "PRE_DEADLINE")


def _match_intelligence_html(conn: sqlite3.Connection, squad_ids: set[int]) -> str:
    """Match Intelligence Core (Pillar 4 Slice A, 2026-08-21) - additive panel,
    shown only when at least one `match_intelligence` row involves a squad
    team. Reads only what's already persisted (`fpl sync-match`/the
    match-intelligence-analysis skill write these tables) - never computes or
    fabricates anything itself.

    Match Centre extension (2026-08-21, live-match-feed pass) - for a LIVE/
    HALFTIME match, the card also shows a real score/minute header, the raw
    match feed (_match_feed_html), and locked-squad players' real per-match
    state (_match_your_players_html) - all real, persisted data, never
    computed here. Freshness is checked against the real `retrieved_at`
    timestamp - "Live data delayed" replaces the live badge rather than
    silently presenting stale data as current (section 14 of the live-
    match-feed spec)."""
    if not squad_ids:
        return "<div class='empty-state'>No squad to scope match intelligence to yet.</div>"
    team_ids = {r["team_id"] for r in conn.execute(
        "SELECT DISTINCT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
        list(squad_ids),
    ).fetchall()}
    if not team_ids:
        return "<div class='empty-state'>No squad to scope match intelligence to yet.</div>"

    placeholders = ",".join("?" * len(team_ids))
    matches = conn.execute(
        f"SELECT * FROM match_intelligence WHERE home_team_id IN ({placeholders}) "
        f"OR away_team_id IN ({placeholders}) ORDER BY kickoff_utc DESC LIMIT 5",
        list(team_ids) * 2,
    ).fetchall()
    if not matches:
        return "<div class='empty-state'>No match intelligence synced yet - run `fpl sync-match`.</div>"

    cards = []
    for m in matches:
        obs_count = conn.execute(
            "SELECT COUNT(*) c FROM match_observations WHERE match_id=?", (m["id"],)
        ).fetchone()["c"]
        impl_rows = conn.execute(
            "SELECT * FROM player_fpl_implications WHERE match_id=? LIMIT 5", (m["id"],)
        ).fetchall()
        # Slice A2: prefer a real analysis headline (FULL_TIME first, else the
        # latest phase available) over the generic "N observation(s)" line -
        # PROVISIONAL badge for anything short of FULL_TIME (spec section 7).
        summary = conn.execute(
            "SELECT * FROM match_analysis_summary WHERE match_id=? ORDER BY (phase='FULL_TIME') DESC, generated_at DESC LIMIT 1",
            (m["id"],),
        ).fetchone()
        if summary and summary["headline"]:
            provisional = "" if summary["phase"] == "FULL_TIME" else "<span class='outlook-chip outlook-alert'>PROVISIONAL</span>"
            verdict = f"{provisional}{_esc(summary['headline'])}"
        elif obs_count == 0:
            verdict = _esc("not yet analyzed - run the match-intelligence-analysis skill")
        else:
            verdict = _esc(f"{obs_count} observation(s) recorded")
        impl_html = "".join(
            f"<div class='outlook-news'><span class='outlook-chip'>{_esc(i['direction'])}/{_esc(i['signal'])}</span> "
            f"{_esc(i['reason'] or '')}</div>"
            for i in impl_rows
        ) or "<div class='outlook-news'>no FPL implications recorded yet</div>"
        score = f"{m['home_score'] if m['home_score'] is not None else '-'}-{m['away_score'] if m['away_score'] is not None else '-'}"

        match_centre_html = ""
        if m["status"] in ("LIVE", "HALFTIME"):
            home_name = conn.execute("SELECT short_name FROM teams WHERE id=?", (m["home_team_id"],)).fetchone()
            away_name = conn.execute("SELECT short_name FROM teams WHERE id=?", (m["away_team_id"],)).fetchone()
            home_short = home_name["short_name"] if home_name else "?"
            away_short = away_name["short_name"] if away_name else "?"
            minute_label = _esc(m["live_minute"]) if m["live_minute"] else ("HT" if m["status"] == "HALFTIME" else "")
            stale_seconds = _seconds_since(m["retrieved_at"])
            if stale_seconds is not None and stale_seconds > _LIVE_STALENESS_SECONDS:
                live_badge = f"<span class='outlook-chip outlook-alert'>Live data delayed &middot; last update {_esc(_relative_time(m['retrieved_at']))}</span>"
            else:
                live_badge = f"<span class='outlook-chip live-now-tag'>LIVE DATA &middot; {stale_seconds if stale_seconds is not None else '?'}s ago</span>"
            match_centre_html = f"""
  <div class="outlook-head" style="margin-top:10px">
    <strong>{_esc(home_short)} {m['home_score'] if m['home_score'] is not None else 0} &ndash; {m['away_score'] if m['away_score'] is not None else 0} {_esc(away_short)}</strong>
    <span class="outlook-chip">{minute_label}</span>{live_badge}
  </div>
  <div class="bench-label" style="margin-top:8px">Match Feed</div>
  {_match_feed_html(conn, m["id"])}
  <div class="bench-label" style="margin-top:8px">Your Players</div>
  {_match_your_players_html(conn, m["id"], m["home_team_id"], m["away_team_id"], squad_ids)}"""

        cards.append(f"""<div class="outlook-card">
  <div class="outlook-head"><strong>{_esc(m['competition'] or '')}</strong>
    <span class="outlook-chip">{_esc(m['status'])}</span><span class="outlook-chip">score {_esc(score)}</span></div>
  <div class="outlook-churn">{verdict}</div>
  {impl_html}
  {match_centre_html}
  <div class="outlook-news">source={_esc(m['source'])} retrieved_at={_esc(m['retrieved_at'])}</div>
</div>""")
    return "\n".join(cards)


def _fixture_ticker_html(conn: sqlite3.Connection, squad_ids: set[int]) -> str:
    """Real fixture-difficulty ticker (2026-08-21, extended same day per
    direct user pushback: "doesnt show all teams, doesnt show clean sheet %
    and doesnt show projected goals scored"). Per-gameweek colored cells
    (green=easy/1-2, grey=neutral/3, red=hard/4-5), the real FPL Copilot/
    Fantasy Football Scout convention - NOT a single number blended across
    several games. Now covers all real 20 clubs (not just squad-linked -
    real competitor tickers are always league-wide, scoped-to-squad was
    this project's own narrower first cut), squad clubs highlighted for
    quick scanning. Each cell also carries real projected goals FOR
    (`expected_points.py::_fixture_goals_for`, the same Dixon-Coles/odds-
    blended number the live xP model itself uses - not a separate,
    diverging metric) and real clean-sheet probability
    (`models/blend.py::clean_sheet_probability`, same Poisson-zero
    treatment the scoring model already uses for clean sheet points).
    Fixture-goals lookups are memoized per fixture_id for this render
    (`_cached_fixture_goals_for`) - every real fixture is asked about twice
    (once per involved team's own ticker row), and the underlying Dixon-
    Coles/odds computation doesn't depend on which side is asking."""
    goals_cache: dict[int, tuple[float, float]] = {}
    team_rows = conn.execute("SELECT id, short_name, code FROM teams ORDER BY short_name").fetchall()
    if not team_rows:
        return "<div class='empty-state'>No team data synced yet.</div>"
    squad_team_ids = set()
    if squad_ids:
        squad_team_ids = {
            r["team_id"] for r in conn.execute(
                "SELECT DISTINCT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
                tuple(squad_ids),
            ).fetchall()
        }

    rows_html = []
    for r in team_rows:
        entries = team_fixture_ticker(conn, r["id"], n_gw=_FDR_TICKS)
        cells = []
        for e in entries:
            fixture_row = conn.execute("SELECT * FROM fixtures WHERE id=?", (e.fixture_id,)).fetchone()
            goals_for, goals_against = _cached_fixture_goals_for(conn, fixture_row, r["id"], goals_cache)
            cs_pct = round(clean_sheet_probability(goals_against) * 100)
            fdr_cls = _fdr_class(e.difficulty)
            venue_word = "at home" if e.is_home else "away"
            # Real, fuller title text (2026-08-21, third session, section 8:
            # ""ARS - COV (H) - EASY" without needing to interpret a tiny
            # dense rectangle") - a hover/screen-reader sentence built from
            # the exact same real difficulty/venue data the cell's own color
            # already encodes, not a second visual element competing for
            # space in an already-dense cell.
            cells.append(
                f"<div class='fdr-cell fdr-{fdr_cls}' "
                f"title='GW{e.event}: {_esc(r['short_name'])} vs {_esc(e.opponent_short)} {venue_word} - "
                f"{_esc(_FIXTURE_QUALITY_LABEL[fdr_cls])} (xGF {goals_for:.1f}, CS {cs_pct}%)'>"
                f"<div class='fdr-opp'>{_esc(e.opponent_short)}{'(H)' if e.is_home else '(A)'}</div>"
                f"<div class='fdr-stat'>xGF {goals_for:.1f}</div>"
                f"<div class='fdr-stat'>CS {cs_pct}%</div>"
                f"</div>"
            )
        blanks = _FDR_TICKS - len(entries)
        cells.append("<div class='fdr-cell fdr-blank'>-</div>" * blanks)
        row_cls = "fdr-row fdr-row-squad" if r["id"] in squad_team_ids else "fdr-row"
        # avg-fdr / team-name data attributes back the client-side sort
        # toggle below (real principle from fpl.page's own "Sort by
        # Rotation"/"Easiest" controls) - pure re-ordering of already-
        # rendered rows, no new computation, real average of the same
        # e.difficulty values already rendered in each cell.
        avg_fdr = sum(e.difficulty for e in entries) / len(entries) if entries else 5.0
        badge_url = _official_badge_url(r["code"])
        rows_html.append(f"""<div class="{row_cls}" data-avg-fdr="{avg_fdr:.2f}" data-team-name="{_esc(r['short_name'])}">
  <div class="fdr-team"><img class="fdr-badge" src="{_esc(badge_url)}" loading="lazy" alt="">{_esc(r['short_name'])}</div>
  <div class="fdr-cells">{''.join(cells)}</div>
</div>""")
    return "\n".join(rows_html)


def _decision_center_html(conn: sqlite3.Connection, report, squad_ids: set[int], decision=None) -> str:
    """"AI Decisions" (2026-08-21, direct user request, section 14) -
    "the place where I look and immediately know what should I actually
    do." Explicitly a REORGANIZATION per the user's own instruction ("if
    the application already has these concepts elsewhere, reorganize them
    rather than duplicating them") - every card below reads a value this
    project already computes elsewhere (captaincy.py's CaptainOption,
    the decisions journal's own transfer/chip entries, build_team.py's own
    risks list), nothing new is calculated here.

    `decision` (2026-08-21, locked-squad product architecture pass) - an
    optional `optimization.decision_engine.SquadDecision`, passed only when
    a real squad is locked. When present, Captain/Transfer Watch become
    real KEEP-vs-CHANGE deltas against the LOCKED squad's own captain/
    players (the optimizer as a decision layer, not an independent squad
    generator) instead of a flat "best pick" fact with no comparison to
    what's actually owned. `decision=None` (the default, and every existing
    caller before this pass) reproduces the exact prior Mode-A behavior -
    a bare best-captain-fact card and the last manually-logged transfer, if
    any - unchanged."""
    cards = []

    if decision is not None:
        ca = decision.captain_action
        if ca.kind == "unavailable":
            cards.append("""<div class="decision-card">
  <div class="decision-kicker">Captain <span class="decision-action">N/A</span></div>
  <div class="decision-detail">No real captaincy evidence available for the locked squad yet.</div>
</div>""")
        elif ca.kind == "keep":
            cur = ca.current
            # Decision Fusion FYI (2026-08-22, spec section 27) - only ever
            # additive, never changes the KEEP verdict above it.
            qual_bit = (
                f"<div class='decision-detail decision-fusion-note'>Football Intelligence: {_esc(ca.qualitative_note)}</div>"
                if ca.qualitative_note else ""
            )
            cards.append(f"""<div class="decision-card decision-positive">
  <div class="decision-kicker">Captain <span class="decision-action">KEEP</span></div>
  <div class="decision-headline">{_captain_html(cur.web_name)}</div>
  <div class="decision-detail">Remains the preferred captain &middot; median {cur.median:.1f} xP &middot;
    {_esc(cur.confidence)} confidence</div>
  {qual_bit}
</div>""")
        else:  # "change"
            cur, sug = ca.current, ca.suggested
            cur_bit = f"{_esc(cur.web_name)} &rarr; " if cur is not None else ""
            delta_bit = f" (+{ca.delta:.1f} xP)" if ca.delta is not None else ""
            qual_bit = (
                f"<div class='decision-detail decision-fusion-note'>Football Intelligence: {_esc(ca.qualitative_note)}</div>"
                if ca.qualitative_note else ""
            )
            cards.append(f"""<div class="decision-card decision-alert">
  <div class="decision-kicker">Captain <span class="decision-action">CHANGE</span></div>
  <div class="decision-headline">{cur_bit}{_captain_html(sug.web_name)}</div>
  <div class="decision-detail">Real median gain{delta_bit} &middot; {_esc(sug.confidence)} confidence</div>
  {qual_bit}
</div>""")

        ta = decision.transfer_action
        if ta.kind == "keep":
            cards.append("""<div class="decision-card decision-positive">
  <div class="decision-kicker">Transfer Watch <span class="decision-action">KEEP</span></div>
  <div class="decision-detail">Current squad remains the preferred configuration - no realistic swap
    clears enough real marginal value to justify a change.</div>
</div>""")
        else:  # "transfer"
            c = ta.candidate
            cards.append(f"""<div class="decision-card decision-alert">
  <div class="decision-kicker">Transfer Watch <span class="decision-action">TRANSFER</span></div>
  <div class="decision-headline">{_esc(c.player_out_name)} &rarr; {_esc(c.player_in_name)}</div>
  <div class="decision-detail">Real net gain <span class="decision-metric">+{ta.delta:.1f} xP</span>
    over 3 GW (hit-cost aware)</div>
</div>""")

        risks_for_card = decision.risks
    elif report.captain:
        cap = report.captain
        fixture_bit = ""
        if cap.opponent_short:
            venue = "(H)" if cap.is_home else "(A)" if cap.is_home is False else ""
            fixture_bit = f" vs {_esc(cap.opponent_short)}{venue}"

        # Real explainability (2026-08-21, third session, section 12: "a
        # major differentiator... it should communicate WHY"). Every bullet
        # below is a real field `captaincy_report` already computes for
        # exactly this reason - `second` (the runner-up captain option) was
        # already being thrown away by `report.captain` (= cap_report.best
        # alone) before this. Re-running `captaincy_report` here is a cheap
        # read (same squad, no new modelling) - not duplicating the
        # calculation, surfacing data that already existed but was buried.
        cap_report = captaincy_report(conn, list(squad_ids)) if squad_ids else None
        reasons = []
        if cap_report and cap_report.second and cap_report.second.player_id != cap.player_id:
            delta = cap.median - cap_report.second.median
            reasons.append(f"+{delta:.1f} xP vs next best ({_esc(cap_report.second.web_name)})")
        if cap.expected_minutes >= 80:
            reasons.append(f"{cap.expected_minutes:.0f}&prime; expected minutes")
        if cap.is_penalty_taker:
            reasons.append("primary penalty taker")
        if cap_report and cap_report.differential_captain_note:
            reasons.append("real rank-differential armband")
        # Real "why" framing (2026-08-21, fourth session, section 5: "make
        # that reasoning feel like the output of an optimization engine
        # rather than explanatory text beneath a card") - same real bullets
        # as before, just given an explicit "why this pick" header instead
        # of trailing silently under the metric line.
        reasons_html = (
            f"<div class='decision-reasons-label'>Why {_esc(cap.web_name)}?</div>"
            "<ul class='decision-reasons'>" + "".join(f"<li>{r}</li>" for r in reasons) + "</ul>"
        ) if reasons else ""

        # Real confidence-tier language (2026-08-21, fourth session, section
        # 4) - a direct, honest relabeling of the model's own real
        # HIGH/MEDIUM/LOW confidence field (models/expected_minutes.py),
        # never a fabricated new score. Right now every player is genuinely
        # LOW (real preseason data limitation, not a bug) - this badge is
        # designed to upgrade to STRONG/GOOD automatically the moment real
        # in-season minutes data raises the model's own confidence, with
        # zero further code change needed.
        tier_label, tier_cls = _CONFIDENCE_TIER.get(cap.confidence, ("WATCH", "watch"))

        cards.append(f"""<div class="decision-card decision-positive">
  <div class="decision-kicker">Captain <span class="decision-tier decision-tier-{tier_cls}">{tier_label}</span>
    <span class="decision-action">KEEP</span></div>
  <div class="decision-headline">{_captain_html(cap.web_name)}</div>
  <div class="decision-detail">Median <span class="decision-metric">{cap.median:.1f} xP</span>{fixture_bit} &middot;
    floor {cap.floor:.1f} / ceiling {cap.ceiling:.1f} &middot; {_esc(cap.confidence)} confidence</div>
  {reasons_html}
</div>""")

        # Real "no action" state (2026-08-21, fourth session, section 9: "a
        # sophisticated optimizer sometimes says 'do nothing' - represent that
        # confidently") - the card used to simply not render at all when no
        # transfer decision had ever been logged, which reads as a missing
        # feature, not an analytical conclusion. Honest distinction kept: this
        # is "no analysis has been run yet", NOT a fabricated "the optimizer
        # concluded no transfer is worth making" (that claim would need a real
        # logged decision saying so, which this branch explicitly doesn't have).
        transfer_decision = latest_decision_of_type(conn, "transfer")
        if transfer_decision is not None:
            cards.append(f"""<div class="decision-card">
  <div class="decision-kicker">Transfer Watch &middot; {_esc(_relative_time(transfer_decision.created_at))}
    <span class="decision-action">REVIEW</span></div>
  <div class="decision-detail">{_esc(transfer_decision.summary)}</div>
</div>""")
        else:
            cards.append("""<div class="decision-card">
  <div class="decision-kicker">Transfer Watch <span class="decision-action">N/A</span></div>
  <div class="decision-detail">No transfer analysis logged yet - run <code>fpl transfers --search</code>.</div>
</div>""")
        risks_for_card = report.risks
    else:
        risks_for_card = report.risks

    risk_count = len(risks_for_card)
    risk_cls = "decision-alert" if risk_count else "decision-positive"
    risk_action = "REVIEW" if risk_count else "OK"
    risk_detail = _esc(risks_for_card[0]) if risks_for_card else "No availability or rotation concerns flagged."
    cards.append(f"""<div class="decision-card {risk_cls}">
  <div class="decision-kicker">Risks <span class="decision-action">{risk_action}</span></div>
  <div class="decision-headline">{risk_count} player{'s' if risk_count != 1 else ''} flagged</div>
  <div class="decision-detail">{risk_detail}</div>
</div>""")

    chip_line = "No action recommended - hold every chip until a real blank/double GW is visible."
    chip_cls = "decision-card"
    chip_action = "HOLD"
    if squad_ids:
        squad_list = list(squad_ids)
        windows = eligible_chips(conn)
        eligible_now = {w.name for w in windows if w.eligible_now}
        best_name, best_value = None, 0.0
        if "bboost" in eligible_now:
            v = bench_boost_value(conn, squad_list)
            if v > best_value:
                best_name, best_value = "Bench Boost", v
        if "3xc" in eligible_now:
            v = triple_captain_value(conn, squad_list)
            if v > best_value:
                best_name, best_value = "Triple Captain", v
        if best_name and best_value > 2.0:  # a real, modest bar - not "any positive number"
            chip_line = f"{best_name} would add ~{best_value:.1f} xP this GW if played now."
            chip_cls = "decision-card decision-positive"
            chip_action = "CONSIDER"
    cards.append(f"""<div class="{chip_cls}">
  <div class="decision-kicker">Chip <span class="decision-action">{chip_action}</span></div>
  <div class="decision-detail">{_esc(chip_line)}</div>
</div>""")

    return f'<div class="decision-grid">{"".join(cards)}</div>'


def _chip_strategy_html(conn: sqlite3.Connection, squad_ids: set[int]) -> str:
    """Real chip-window eligibility + current single-decision-point value.
    bench_boost_value/triple_captain_value are cheap reads (no full resolve)
    and computed live, every regen. wildcard/free-hit are NOT computed live
    here - both re-solve the full ~600-player ILP (measured: well over a
    minute per solve on this project's real data, see CLAUDE.md's 2026-08-21
    forensic-audit entry) and this panel regenerates on every scheduled sync
    cycle - baking a minutes-long solve into that would be the wrong
    tradeoff. Instead reads the most recent value `fpl chips`/`fpl
    season-sim` already computed and logged to the decision journal
    (`latest_decision_of_type`) - a real number with a real "as of" age, not
    a live recompute, same FACTS-vs-DERIVED-vs-live-compute layering this
    project already uses elsewhere (e.g. predicted lineups). Falls back to a
    plain "run `fpl chips`" prompt only when nothing has ever been logged.
    Addresses the 2026-08-21 ask directly: many managers reach for Bench
    Boost early on social pressure alone - this panel states the real
    eligibility window (GW1-19 for bboost/3xc per this season's real
    chip_windows) plainly next to the actual value, so "everyone else is
    doing it" has a real number to be checked against instead of just vibes."""
    if not squad_ids:
        return "<div class='empty-state'>No squad to evaluate chips for yet.</div>"
    squad_list = list(squad_ids)
    windows = eligible_chips(conn)
    if not windows:
        return "<div class='empty-state'>No chip window data synced yet.</div>"

    bboost = bench_boost_value(conn, squad_list)
    tc = triple_captain_value(conn, squad_list)
    value_by_type: dict[str, float] = {"bboost": bboost, "3xc": tc}
    age_by_type: dict[str, str] = {}

    logged = latest_decision_of_type(conn, "chip")
    if logged is not None:
        age = _relative_time(logged.created_at)
        for chip_name, detail_key in (("wildcard", "wildcard_5gw"), ("freehit", "free_hit")):
            if detail_key in logged.detail:
                value_by_type[chip_name] = logged.detail[detail_key]
                age_by_type[chip_name] = age

    rows = []
    for w in windows:
        if not w.eligible_now:
            continue
        value = value_by_type.get(w.name)
        if value is not None:
            age_suffix = f" <span class='chip-value-age'>as of {_esc(age_by_type[w.name])}</span>" if w.name in age_by_type else ""
            value_html = f"<span class='chip-value'>{value:.1f} xP</span>{age_suffix}"
        else:
            value_html = "<span class='chip-value chip-value-muted'>run `fpl chips` for value</span>"
        rows.append(f"""<div class="chip-strategy-row">
  <span class="chip-strategy-name">{_esc(w.name)}</span>
  <span class="chip-strategy-window">GW{w.start_event}-{w.stop_event} eligible</span>
  {value_html}
</div>""")
    if not rows:
        return "<div class='empty-state'>No chips currently eligible.</div>"
    advisory = (
        "<div class='chip-advisory'>No blank/double gameweek visible yet this window - standard advice is to "
        "hold every chip until one appears, regardless of how many other managers use theirs early.</div>"
    )
    return "\n".join(rows) + advisory


def generate_dashboard_html(
    conn: sqlite3.Connection, live_payload: dict | None = None,
    gw_window: int = 1, must_include_ids: set[int] | None = None, must_start_ids: set[int] | None = None,
    exclude_ids: set[int] | None = None,
) -> str:
    """Pure function of current DB state (plus an optional already-fetched live
    payload) - no network calls of its own, safe to call as often as wanted.
    `live_payload` is the raw dict from `fetch_event_live()`, fetched by the
    caller (only when a squad fixture is genuinely in progress - see
    `cli/main.py::_maybe_fetch_live_payload`) so this function stays a pure,
    fully-testable read of already-known state. `gw_window`/`must_include_ids`
    (2026-08-21) pass straight through to `generate_build_team_report` -
    default unchanged (GW1, no forced picks) so the scheduled/unattended
    regeneration path (`fpl run-scheduled`) is untouched; `fpl dashboard`'s
    own CLI flags let a manual regen reflect the same real preferences
    `fpl build-team --gw-window/--must-include` already does.

    Locked-squad product architecture (2026-08-21): a bare call (no explicit
    override args - the scheduled-regen/no-flags-manual signature) checks
    `optimization.locked_squad.get_locked_squad()` first. When something is
    genuinely locked (a real synced FPL squad, or a locked `fpl build-team
    --must-include ...` decision), the main pitch renders THAT squad, never
    a freshly re-solved one - the optimizer becomes a decision layer over it
    (`optimization.decision_engine.evaluate_locked_squad`) instead of an
    independent squad generator competing with it. An explicit override
    call (any of gw_window/must_include_ids/must_start_ids/exclude_ids set)
    is treated as a deliberate Mode-A "what if" exploration and always shows
    the freshly-built optimizer squad, unchanged from prior behavior."""
    default_call = (
        gw_window == 1 and must_include_ids is None and must_start_ids is None and exclude_ids is None
    )
    locked = get_locked_squad(conn) if default_call else None
    decision = evaluate_locked_squad(conn, locked) if locked is not None else None

    report = generate_build_team_report(
        conn, gw_window=gw_window, must_include_ids=must_include_ids, must_start_ids=must_start_ids,
        exclude_ids=exclude_ids,
    )
    now = datetime.now(timezone.utc).isoformat()

    primary = report.structures[0] if report.structures else None

    my_team_entry_id = get_my_team_entry_id(conn)

    squad_error_html = ""
    if locked is not None:
        squad_ids = set(locked.squad_ids)
        display_xi = locked.xi
        cap_id = locked.xi.captain.player_id if locked.xi.captain else None
        vc_id = locked.xi.vice_captain.player_id if locked.xi.vice_captain else None
        captain_name = locked.xi.captain.web_name if locked.xi.captain else "n/a"
        vice_name = locked.xi.vice_captain.web_name if locked.xi.vice_captain else "n/a"
        risks_list = decision.risks if decision is not None else []
        headline_xp = sum(c.median for c in locked.xi.starting) + (locked.xi.captain.median if locked.xi.captain else 0.0)
        squad_value_m = locked.squad_value_tenths / 10
        if locked.bank_tenths is not None:
            bank_m = locked.bank_tenths / 10
        else:
            season = current_season(conn)
            budget_tenths = get_rule(conn, season, "rules.squad_total_spend", 1000) if season else 1000
            bank_m = (budget_tenths - locked.squad_value_tenths) / 10
        pitch_heading = "My Locked Squad"
        pitch_html = ""
        validation_problems = validate_starting_xi(display_xi)
        if validation_problems:
            squad_error_html = (
                "<div class='empty-state'>SYSTEM ERROR: locked squad failed validation - "
                + "; ".join(_esc(p) for p in validation_problems) + "</div>"
            )
        else:
            pitch_html = _pitch_html_from_xi(conn, display_xi, cap_id, vc_id)
    else:
        squad_ids = {c.player_id for c in primary.result.squad} if primary and primary.result.squad else set()
        captain_name = report.captain.web_name if report.captain else "n/a"
        vice_name = report.vice.web_name if report.vice else "n/a"
        risks_list = report.risks
        headline_xp = 0.0
        squad_value_m = 0.0
        bank_m = 0.0
        if primary and primary.result.squad:
            headline_xp = sum(c.median for c in primary.xi.starting) + (primary.xi.captain.median if primary.xi.captain else 0.0)
            season = current_season(conn)
            budget_tenths = get_rule(conn, season, "rules.squad_total_spend", 1000) if season else 1000
            squad_value_m = primary.result.total_cost_tenths / 10
            bank_m = (budget_tenths - primary.result.total_cost_tenths) / 10
        pitch_heading = "Optimizer Recommendation"
        pitch_html = _pitch_html(conn, report)

    compare_panel = ""
    if my_team_entry_id is not None:
        compare_panel = f"""
  <section class="panel panel-compare" id="compare">
    <h2>Your Team vs Optimized</h2>
    {_compare_panel_html(conn, my_team_entry_id, headline_xp, squad_value_m, bank_m, captain_name, squad_ids)}
  </section>"""

    reference_event = live_or_reference_event(conn)
    gw_label = f"GW{reference_event}" if reference_event is not None else "GW?"
    xp_label = "Projected xP" if gw_window == 1 else f"{gw_window}-GW Projected xP"

    # Real Gameweek Command Strip (2026-08-21, third session, section 4) -
    # a single inline status band, not more rounded tiles: risk count
    # (already computed for AI Decisions, reused not recalculated), a
    # live-or-next-kickoff read (reuses the exact same _squad_live_window
    # this project's Live Tracking panel already computes - one extra cheap
    # call, not a new data source), and an honest "optimizer status" derived
    # straight from whether this run actually produced a squad.
    live_window = _squad_live_window(conn, squad_ids)
    if live_window.state == "live":
        kickoff_html = "<span class='status-live'><span class='pulse-dot small'></span>LIVE NOW</span>"
    elif live_window.state == "pre" and live_window.next_kickoff:
        kickoff_html = f"<span id='hero-kickoff-countdown' data-utc='{_esc(live_window.next_kickoff)}'>&hellip;</span>"
    elif live_window.state == "post":
        kickoff_html = "Finished"
    else:
        kickoff_html = "No fixtures"
    optimizer_status = "READY" if primary and primary.result.squad else "NO SQUAD"
    optimizer_status_cls = "status-ok" if optimizer_status == "READY" else "status-bad"

    # Real live-rank headline (2026-08-22) - same cheap-read-of-already-
    # logged-state pattern as Chip Strategy above: `fpl live-rank` samples
    # ~750 real managers per run (the heaviest network call in this
    # project), far too expensive to trigger from every dashboard regen -
    # this only ever reads the last real result `fpl live-rank` itself
    # already logged to the decision journal. `None` (nothing shown) when
    # it's never been run - never a fabricated placeholder rank.
    live_rank_decision = latest_decision_of_type(conn, "live_rank")
    live_rank_html = ""
    if live_rank_decision is not None:
        live_rank_html = (
            f'<div class="hero-strip-item"><span class="hero-strip-label">Live rank (est.)</span>'
            f'<span class="hero-strip-value">{_esc(live_rank_decision.summary)} '
            f'&middot; {_esc(_relative_time(live_rank_decision.created_at))}</span></div>'
        )

    # Dashboard-state architecture (2026-08-21) - one real signal
    # (_squad_live_window, already computed above) drives which of the
    # three product states (PRE_DEADLINE/LIVE/POST_MATCH) this render is
    # in. Same components throughout - state only changes emphasis (a body
    # CSS class + which hero metrics show), never a second dashboard.
    dash_state = _dashboard_state(live_window.state)
    my_live_score = _compute_my_live_score(conn, locked, live_payload, live_window.event)
    # Real consistency fix (2026-08-21, found live): a real squad spans many
    # different kickoff times across a whole gameweek, so `dash_state` can
    # honestly read PRE_DEADLINE (no fixture live right now, not everything
    # finished either) in the real gap between two of a squad's own
    # matches - but `my_live_score` (gated on `live_payload` being fetchable
    # at all this event, not on the 3-way state split) stays populated and
    # correctly still glows. The label must agree with the number it's
    # sitting next to, not the coarser 3-state model alone - both are driven
    # by the same `my_live_score is not None` condition now.
    if my_live_score is not None:
        hero_state_label = "FINAL" if dash_state == "POST_MATCH" else "LIVE"
    else:
        hero_state_label = xp_label

    # Real state-aware panel ordering (dashboard-state pass, 2026-08-21) -
    # these five sections are plain block-level <section> elements (no
    # shared flex/grid parent), so a CSS `order` property alone would be
    # dead code - genuine reordering happens here, by choosing which
    # already-built string comes first, never by duplicating markup.
    # PRE_DEADLINE reproduces the exact original document order (squad,
    # decisions, risks, compare, live) byte-for-byte - zero risk to every
    # existing test/behavior that predates this pass.
    squad_section_html = f"""<section class="panel panel-team" id="squad">
  <h2>{_esc(pitch_heading)}
    <span class="panel-subtitle">{headline_xp:.1f} projected xP &middot; £{squad_value_m:.1f}m &middot;
      {_captain_html(captain_name)} captain</span></h2>
  {squad_error_html}{pitch_html}
</section>"""
    decisions_section_html = f"""<section class="panel panel-decisions" id="decisions">
  <h2>AI Decisions <span class="panel-subtitle">what should you actually do</span></h2>
  {_decision_center_html(conn, report, squad_ids, decision=decision)}
</section>"""
    risks_section_html = f"""<section class="panel panel-risks" id="risks">
  <h2>Risk Monitor <span class="panel-subtitle">what could go wrong</span></h2>
  <div class="risk-monitor">
{_risk_monitor_html(conn, squad_ids)}
  </div>
</section>"""
    live_section_html = f"""<section class="panel panel-live{' panel-live-emphasis' if dash_state == 'LIVE' else ''}" id="live">
  <h2>Live Tracking</h2>
  {_live_tracking_html(conn, squad_ids, live_payload)}
</section>"""

    if dash_state == "LIVE":
        panel_order = [live_section_html, decisions_section_html, squad_section_html, risks_section_html, compare_panel]
    elif dash_state == "POST_MATCH":
        panel_order = [live_section_html, squad_section_html, decisions_section_html, risks_section_html, compare_panel]
    else:
        panel_order = [squad_section_html, decisions_section_html, risks_section_html, compare_panel, live_section_html]
    ordered_panels_html = "\n\n".join(p for p in panel_order if p)

    fixtures_fresh = _source_freshness(conn, "fpl_api_fixtures")
    fixtures_fresh_html = f"<span class='freshness-tag'>Updated {_esc(fixtures_fresh)}</span>" if fixtures_fresh else ""
    news_fresh = _source_freshness(conn, "bbc_sport_rss", "bbc_sport_football_all_rss", "sky_sports_rss")
    news_fresh_html = f"<span class='panel-subtitle freshness-tag'>Updated {_esc(news_fresh)}</span>" if news_fresh else ""

    # Real, state-aware browser reload cadence (2026-08-22, tonight's-matches
    # pass) - `fpl live-match-poll` now regenerates this file roughly every
    # `interval` seconds while a match is genuinely LIVE (see its own
    # docstring), so a flat 60s client reload was slower than the data
    # backing it actually refreshes. POST_MATCH/PRE_DEADLINE keep the
    # original 60s - nothing regenerates faster than that outside a live
    # match anyway (the 30min run-scheduled cadence dominates instead).
    refresh_seconds = 20 if dash_state == "LIVE" else _REFRESH_SECONDS

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh_seconds}">
<title>fpl-agent dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Titillium+Web:wght@600;700;900&display=swap" rel="stylesheet">
<style>
{_CSS}
</style>
</head>
<body class="state-{_esc(dash_state.lower())}">
<header class="topbar">
  <div class="topbar-brand-block">
    <div class="brand">FPL Agent</div>
    <div class="brand-sub">Personal FPL Optimization Engine</div>
  </div>
  <div class="topbar-right">
    <span class="gw-badge">{_esc(gw_label)}</span>
    <div class="refresh-indicator">
      <span class="pulse-dot small"></span>
      snapshot {_esc(_relative_time(now))} &middot; next in <span id="refresh-countdown">{refresh_seconds}s</span>
    </div>
    <a class="btn-refresh" href="" title="Reload now">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3.05-6.77"/><path d="M21 3v6h-6"/></svg>
      Refresh
    </a>
  </div>
</header>

<nav class="site-nav" aria-label="Section navigation">
  <a href="#overview">Overview</a>
  <a href="#squad">Squad</a>
  <a href="#fixtures">Fixtures</a>
  <a href="#live">Live</a>
  <a href="#intelligence">Intelligence</a>
  <a href="#system">System</a>
</nav>

<section class="hero" id="overview">
  <div class="hero-primary">
    <div class="hero-gw">{_esc(gw_label)} &middot; {_esc(hero_state_label)}</div>
    {f'<div class="hero-xp hero-xp-live">{my_live_score.points:.0f}<span class="unit">pts</span></div>' if my_live_score is not None else f'<div class="hero-xp">{headline_xp:.1f}<span class="unit">xP</span></div>'}
  </div>
  <div class="hero-support">
    <div class="hero-metric">
      <div class="hero-metric-label">Captain</div>
      <div class="hero-metric-value">{_captain_html(captain_name)}{f" &middot; {my_live_score.captain_points:.0f} pts" if my_live_score is not None and my_live_score.captain_points is not None else ""}</div>
    </div>
    <div class="hero-metric">
      <div class="hero-metric-label">Vice Captain</div>
      <div class="hero-metric-value">{_esc(vice_name)}</div>
    </div>
    {f'''<div class="hero-metric">
      <div class="hero-metric-label">Played / Live / To Play</div>
      <div class="hero-metric-value">{my_live_score.played} / {my_live_score.live} / {my_live_score.yet_to_play}</div>
    </div>
    <div class="hero-metric">
      <div class="hero-metric-label">Projected xP</div>
      <div class="hero-metric-value">{headline_xp:.1f}</div>
    </div>''' if my_live_score is not None else f'''<div class="hero-metric">
      <div class="hero-metric-label">Squad Value</div>
      <div class="hero-metric-value">£{squad_value_m:.1f}m</div>
    </div>
    <div class="hero-metric">
      <div class="hero-metric-label">In the Bank</div>
      <div class="hero-metric-value">£{bank_m:.1f}m</div>
    </div>'''}
  </div>
  <div class="hero-strip">
    <div class="hero-strip-item"><span class="hero-strip-label">Risks</span><span class="hero-strip-value">{len(risks_list)}</span></div>
    <div class="hero-strip-item"><span class="hero-strip-label">Next kickoff</span><span class="hero-strip-value">{kickoff_html}</span></div>
    <div class="hero-strip-item"><span class="hero-strip-label">Optimizer</span><span class="hero-strip-value {optimizer_status_cls}">{_esc(optimizer_status)}</span></div>
    {live_rank_html}
  </div>
</section>

{ordered_panels_html}

<section class="panel panel-ticker" id="fixtures">
  <h2>Fixture Ticker <span class="panel-subtitle">next {_FDR_TICKS} - green easy, red hard, real FPL strength ratings</span></h2>
  <div class="fdr-sort" role="group" aria-label="Sort fixture ticker">
    <span class="fdr-sort-label">Sort</span>
    <button type="button" class="fdr-sort-btn is-active" data-sort="fdr">Easiest first</button>
    <button type="button" class="fdr-sort-btn" data-sort="fdr-desc">Hardest first</button>
    <button type="button" class="fdr-sort-btn" data-sort="squad">My squad first</button>
    <button type="button" class="fdr-sort-btn" data-sort="az">A&ndash;Z</button>
    {fixtures_fresh_html}
  </div>
  <div class="fdr-grid" id="fdr-grid">
{_fixture_ticker_html(conn, squad_ids)}
  </div>
</section>

<div class="panel-grid" id="intelligence">
  <section class="panel panel-outlook">
    <h2>Team Outlook <span class="panel-subtitle">churn, manager news, formation - Tier 1 + 2-4</span></h2>
    <div class="outlook-grid">
{_team_outlook_html(conn, squad_ids)}
    </div>
  </section>

  <section class="panel panel-chips">
    <h2>Chip Strategy</h2>
    <div class="chip-strategy-list">
{_chip_strategy_html(conn, squad_ids)}
    </div>
  </section>

  <section class="panel panel-activity">
    <h2>Activity <span class="panel-subtitle">squad changes + price moves, Tier 1</span></h2>
    <div class="activity-group-label">Squad changes</div>
    <div class="change-list">
{_squad_changes_html(conn)}
    </div>
    <div class="activity-group-label">Price moves</div>
    <div class="price-list">
{_price_changes_html(conn)}
    </div>
  </section>

  <section class="panel panel-news">
    <h2>Transfer News <span class="panel-subtitle">journalism, Tier 2-4</span>{news_fresh_html}</h2>
    <div class="news-list">
{_news_html(conn, squad_ids)}
    </div>
  </section>

  <section class="panel panel-match-intelligence">
    <h2>Match Intelligence <span class="panel-subtitle">FotMob, structured observed/inferred/FPL layers</span></h2>
    <div class="outlook-grid">
{_match_intelligence_html(conn, squad_ids)}
    </div>
  </section>
</div>

<section class="panel panel-health" id="system">
  <h2>System health</h2>
{_health_summary_html(conn)}
  <details class="health-details">
    <summary>show all checks</summary>
    <div class="chip-grid">
{_readiness_chips(conn)}
{_source_chips(conn)}
    </div>
  </details>
</section>

<script>
// Real fix, 2026-08-21 ("kickoff time isnt correct") - converts every
// server-rendered UTC kickoff time into the viewer's own real browser
// timezone. The UTC text already in the element (from _format_kickoff)
// is the fallback if this script doesn't run for any reason - nothing
// breaks either way.
(function() {{
  document.querySelectorAll('.local-time[data-utc]').forEach(function(el) {{
    var d = new Date(el.getAttribute('data-utc'));
    if (isNaN(d.getTime())) return;
    el.textContent = d.toLocaleString(undefined, {{
      weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
    }});
  }});
  // Live Tracking's date-group dividers (real bug fix, same session): must
  // use the exact same local-timezone conversion as the kickoff badges
  // above, or a late UTC kickoff can land under the wrong day's header.
  // Dedupe guard: two dividers can legitimately collapse onto the same
  // real local date once converted (a UTC-day boundary that isn't also a
  // local-day boundary for this viewer) - hide the redundant repeat rather
  // than show the same day twice in a row.
  var lastDividerText = null;
  document.querySelectorAll('.fx-date-divider[data-utc]').forEach(function(el) {{
    var d = new Date(el.getAttribute('data-utc'));
    if (isNaN(d.getTime())) return;
    var text = d.toLocaleDateString(undefined, {{ weekday: 'short', day: '2-digit', month: 'short' }});
    if (text === lastDividerText) {{
      el.style.display = 'none';
      return;
    }}
    el.textContent = text;
    lastDividerText = text;
  }});
}})();

// Real live countdown to the next auto-refresh (2026-08-21, per LiveFPL/
// fpl.page study - a literal ticking number makes "live" a checkable fact,
// not just a pulsing dot). Honest: the page really does reload via
// <meta http-equiv="refresh"> at this exact interval, this is not a
// decorative fake timer.
(function() {{
  var el = document.getElementById('refresh-countdown');
  if (!el) return;
  var remaining = {refresh_seconds};
  setInterval(function() {{
    remaining = remaining > 0 ? remaining - 1 : 0;
    el.textContent = remaining + 's';
  }}, 1000);
}})();

// Real client-side fixture-ticker sort toggle (2026-08-21, extended third
// session with Hardest-first/My-squad-first - per fpl.page's own
// "Sort by Rotation"/"Easiest" controls) - reorders the already-rendered
// .fdr-row elements in the DOM using data already computed server-side
// (data-avg-fdr / data-team-name / the existing fdr-row-squad class), no
// new data, no network call.
(function() {{
  var grid = document.getElementById('fdr-grid');
  var buttons = document.querySelectorAll('.fdr-sort-btn');
  if (!grid || !buttons.length) return;
  buttons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      buttons.forEach(function(b) {{ b.classList.remove('is-active'); }});
      btn.classList.add('is-active');
      var rows = Array.prototype.slice.call(grid.querySelectorAll('.fdr-row'));
      var mode = btn.getAttribute('data-sort');
      rows.sort(function(a, b) {{
        if (mode === 'az') {{
          return a.getAttribute('data-team-name').localeCompare(b.getAttribute('data-team-name'));
        }}
        if (mode === 'fdr-desc') {{
          return parseFloat(b.getAttribute('data-avg-fdr')) - parseFloat(a.getAttribute('data-avg-fdr'));
        }}
        if (mode === 'squad') {{
          var aSquad = a.classList.contains('fdr-row-squad') ? 0 : 1;
          var bSquad = b.classList.contains('fdr-row-squad') ? 0 : 1;
          if (aSquad !== bSquad) return aSquad - bSquad;
          return parseFloat(a.getAttribute('data-avg-fdr')) - parseFloat(b.getAttribute('data-avg-fdr'));
        }}
        return parseFloat(a.getAttribute('data-avg-fdr')) - parseFloat(b.getAttribute('data-avg-fdr'));
      }});
      rows.forEach(function(row) {{ grid.appendChild(row); }});
    }});
  }});
}})();

// Real hero "next kickoff" countdown (2026-08-21, third session, section 5)
// - ticks down to the actual next real squad fixture's kickoff instant
// (the same data-utc timestamp _local_time_span already carries elsewhere),
// switches to a plain "Kicking off..." only once the real clock passes it -
// never fabricates a live state the server-rendered LIVE/Finished/No
// fixtures branches above don't already cover.
(function() {{
  var el = document.getElementById('hero-kickoff-countdown');
  if (!el) return;
  var target = new Date(el.getAttribute('data-utc')).getTime();
  if (isNaN(target)) return;
  function tick() {{
    var diff = target - Date.now();
    if (diff <= 0) {{
      el.textContent = 'Kicking off...';
      return;
    }}
    var h = Math.floor(diff / 3600000);
    var m = Math.floor((diff % 3600000) / 60000);
    var s = Math.floor((diff % 60000) / 1000);
    var pad = function(n) {{ return n < 10 ? '0' + n : '' + n; }};
    el.textContent = (h > 0 ? h + ':' : '') + pad(m) + ':' + pad(s);
  }}
  tick();
  setInterval(tick, 1000);
}})();
</script>
</body>
</html>
"""


_CSS = """
  /* Official FPL brand palette (2026-08-21 full visual revamp, direct user
     request: "i need official fpl visualizations, features and
     characteristics"). Real FPL brand colors, not an invented palette:
     #37003c is FPL's own signature deep purple (their nav/header/hero
     color across the real site and app), #00ff87 is their real
     "GW live"/positive-state green (the exact color their own live
     bonus/rank indicators use), #e90052 is their real magenta/pink accent
     (used across their captaincy and highlight UI). Status colors
     (ok/warn/bad below) are UNCHANGED from the dataviz-skill-validated
     palette this project already ran through the colorblind-safety
     checker - only the BRAND accent colors and background hue changed, so
     nothing here needs re-validating against that check. Dark-first
     (matches both the real FPL app's own dark-mode-friendly hero regions
     and this project's own prior visual pass) - a light override exists
     for a real light-mode preference. */
  :root {
    --bg: #0e0616; --surface: #1a0f26; --surface-2: #241732;
    --fg: #ffffff; --muted: #beb3cc; --faint: #8c7fa3;
    --border: rgba(255,255,255,0.12); --gridline: #33223f;
    --ok: #22c55e; --warn: #fbbf24; --bad: #f0555a;
    --ok-text: #34d67f; --accent: #963cff; --accent-2: #00ff87;
    --fpl-purple: #37003c; --fpl-pink: #e90052;
    --pitch-1: #0d3320; --pitch-2: #114228;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f7f5fa; --surface: #ffffff; --surface-2: #f1ecf7;
      --fg: #150022; --muted: #524564; --faint: #8a7d9c;
      --border: rgba(55,0,60,0.12); --gridline: #e6dcf0;
      --ok: #0ca30c; --warn: #c98500; --bad: #d03b3b;
      --ok-text: #006300; --accent: #7b1fd6; --accent-2: #00b368;
      --fpl-purple: #37003c; --fpl-pink: #e90052;
      --pitch-1: #14532d; --pitch-2: #166534;
    }
  }
  * { box-sizing: border-box; }
  body {
    background:
      radial-gradient(1200px 600px at 15% -10%, color-mix(in srgb, var(--fpl-purple) 55%, transparent), transparent),
      radial-gradient(900px 500px at 100% 30%, color-mix(in srgb, var(--accent-2) 10%, transparent), transparent),
      var(--bg);
    color: var(--fg);
    font-family: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
    margin: 0; padding: 20px 24px 48px; max-width: 1240px; margin-inline: auto;
  }
  h2 { font-family: "Titillium Web", system-ui, sans-serif; font-size: 0.95rem; font-weight: 800;
       text-transform: uppercase; letter-spacing: 0.04em;
       color: var(--fg); margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
  h2::before { content: ""; width: 9px; height: 9px; border-radius: 3px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2)); flex-shrink: 0; }
  .panel > h2 { position: relative; padding-bottom: 12px; margin-bottom: 14px; }
  .panel > h2::after { content: ""; position: absolute; left: 0; bottom: 0; width: 42px; height: 3px;
    border-radius: 3px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); }
  .panel-subtitle { font-size: 0.68rem; font-weight: 500; text-transform: none; letter-spacing: normal;
    color: var(--faint); margin-left: 6px; }
  code { background: var(--surface-2); padding: 1px 5px; border-radius: 4px; font-size: 0.85em; }

  /* --- Header (2026-08-21 command-centre revamp) --- */
  .topbar { position: relative; display: flex; align-items: center; justify-content: space-between;
    padding: 18px 22px; margin: -20px -24px 18px; border-radius: 0 0 18px 18px;
    background:
      radial-gradient(700px 260px at 8% 0%, color-mix(in srgb, var(--accent) 30%, transparent), transparent),
      linear-gradient(120deg, var(--fpl-purple), #1c0620 65%); overflow: hidden; }
  .topbar-brand-block { position: relative; z-index: 1; }
  .brand { font-family: "Titillium Web", Impact, "Arial Narrow Bold", sans-serif; font-size: 1.7rem;
    font-weight: 900; letter-spacing: 0.01em; text-transform: uppercase; color: #fff; line-height: 1.1; }
  .brand-sub { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent-2); margin-top: 2px; }
  .topbar-right { position: relative; z-index: 1; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .gw-badge { font-family: "Titillium Web", sans-serif; font-size: 0.78rem; font-weight: 800;
    color: #fff; background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.22);
    padding: 6px 12px; border-radius: 999px; letter-spacing: 0.03em; }
  .refresh-indicator { display: flex; align-items: center; gap: 8px; font-size: 0.78rem; color: rgba(255,255,255,0.85);
    background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.16); padding: 6px 12px; border-radius: 999px; }
  .btn-refresh { display: inline-flex; align-items: center; gap: 6px; font-size: 0.78rem; font-weight: 700;
    color: #fff; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.22);
    padding: 6px 13px; border-radius: 999px; text-decoration: none; transition: background 0.15s ease, transform 0.15s ease; }
  .btn-refresh:hover { background: rgba(255,255,255,0.2); transform: translateY(-1px); }
  .btn-refresh svg { width: 13px; height: 13px; }

  /* --- Sticky section nav --- */
  .site-nav { position: sticky; top: 0; z-index: 20; display: flex; gap: 4px; overflow-x: auto;
    background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(10px);
    border: 1px solid var(--border); border-radius: 12px; padding: 6px; margin-bottom: 18px; }
  .site-nav a { flex-shrink: 0; font-size: 0.74rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--muted); text-decoration: none; padding: 7px 13px; border-radius: 8px;
    transition: background 0.15s ease, color 0.15s ease; }
  .site-nav a:hover { color: var(--fg); background: var(--surface-2); }

  .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); flex-shrink: 0;
    box-shadow: 0 0 0 0 rgba(12,163,12,0.5); animation: pulse 2s infinite; }
  .pulse-dot.small { width: 6px; height: 6px; }
  @keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(12,163,12,0.45); }
    70% { box-shadow: 0 0 0 6px rgba(12,163,12,0); }
    100% { box-shadow: 0 0 0 0 rgba(12,163,12,0); }
  }

  /* --- Hero / Gameweek Command Bar (2026-08-21) - the projected xP number
     is the single visual focal point, everything else is a supporting
     metric, not equal-weighted stat tiles. --- */
  .hero { display: grid; grid-template-columns: 1.1fr 2fr; gap: 14px; margin-bottom: 18px; }
  .hero-primary { position: relative; overflow: hidden; border-radius: 18px; padding: 22px 24px;
    background: linear-gradient(135deg, var(--fpl-purple), var(--accent) 70%, var(--accent-2));
    box-shadow: 0 10px 30px -10px color-mix(in srgb, var(--accent) 55%, transparent);
    display: flex; flex-direction: column; justify-content: center; }
  .hero-primary::after { content: ""; position: absolute; right: -30px; top: -30px; width: 160px; height: 160px;
    border-radius: 50%; background: radial-gradient(circle, rgba(255,255,255,0.16), transparent 70%); }
  .hero-gw { font-family: "Titillium Web", sans-serif; font-size: 0.78rem; font-weight: 800; letter-spacing: 0.08em;
    text-transform: uppercase; color: rgba(255,255,255,0.85); }
  .hero-xp { font-family: "Titillium Web", sans-serif; font-size: 3.1rem; font-weight: 900; color: #fff;
    line-height: 1.05; font-variant-numeric: proportional-nums; letter-spacing: -0.01em; }
  .hero-xp .unit { font-size: 1.3rem; font-weight: 700; opacity: 0.8; margin-left: 4px; }
  .hero-support { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
  .hero-metric { background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
    padding: 13px 15px; box-shadow: 0 4px 16px -10px rgba(0,0,0,0.5); }
  .hero-metric-label { font-size: 0.68rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em;
    margin-bottom: 5px; font-weight: 700; }
  .hero-metric-value { font-family: "Titillium Web", system-ui, sans-serif; font-size: 1.25rem; font-weight: 800;
    font-variant-numeric: proportional-nums; }
  .hero-metric-value.accent-green { color: var(--accent-2); }
  .hero-metric-value.accent-pink { color: var(--fpl-pink); }
  /* Real Gameweek Command Strip (2026-08-21, third session, section 4) - a
     single inline status band under the tiles, not a 5th/6th/7th rounded
     card. Real, quiet, ticker-style: label:value pairs separated by
     dividers. Spans both hero-primary/hero-support columns. */
  .hero-strip { grid-column: 1 / -1; display: flex; align-items: center; gap: 0;
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 9px 16px; font-size: 0.8rem; }
  .hero-strip-item { display: flex; align-items: center; gap: 6px; padding: 0 16px;
    border-right: 1px solid var(--gridline); }
  .hero-strip-item:last-child { border-right: none; }
  .hero-strip-item:first-child { padding-left: 0; }
  .hero-strip-label { color: var(--faint); text-transform: uppercase; font-size: 0.66rem; font-weight: 700; letter-spacing: 0.04em; }
  .hero-strip-value { font-weight: 800; font-variant-numeric: tabular-nums; }
  .hero-strip-value.status-ok { color: var(--ok-text); }
  .hero-strip-value.status-bad { color: var(--bad); }
  .status-live { display: inline-flex; align-items: center; gap: 5px; color: var(--fpl-pink); font-weight: 800; }
  /* Consistent captain gold treatment (2026-08-21, third session, section
     10) - the ONE shared color used everywhere a captain's name appears as
     a value (hero, AI Decisions, comparison); the pitch's own gold ring is
     a separate, already-established card-level treatment, not duplicated
     here. Deliberately just color + weight, no icon - restrained. */
  .captain-name { color: #e9a400; font-weight: 800; }
  @media (max-width: 1024px) { .hero { grid-template-columns: 1fr; } .hero-support { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 640px) { .hero-strip { flex-wrap: wrap; gap: 8px 0; } .hero-strip-item { border-right: none; padding: 0 12px 0 0; } }
  @media (max-width: 480px) { .hero-support { grid-template-columns: 1fr 1fr; } .hero-xp { font-size: 2.3rem; } }

  .panel-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; margin-bottom: 14px; }
  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 18px 20px;
    box-shadow: 0 4px 18px -10px rgba(0,0,0,0.5); }
  /* The squad pitch is this dashboard's hero content - real user complaint
     fixed 2026-08-21 ("the squad module looks so squeezed"): both "My Real
     Team" and "Recommended Squad" used to share one 2-col grid row
     (grid-column: span 1 each), squeezing the pitch into ~55% of the page
     width. Both now take the FULL row - stacked vertically instead of
     squeezed side-by-side. */
  .panel-team, .panel-decisions, .panel-compare, .panel-risks { grid-column: 1 / -1; }
  .panel-live { grid-column: span 1; }
  .panel:hover { border-color: color-mix(in srgb, var(--accent) 30%, var(--border)); }
  @media (max-width: 1024px) { .panel-grid { grid-template-columns: 1fr; } }
  @media (max-width: 640px) {
    body { padding: 14px 12px 40px; }
    .topbar { margin: -14px -12px 14px; padding: 14px 16px; flex-wrap: wrap; gap: 10px; }
    .panel { padding: 15px 16px; }
    .panel-subtitle { display: block; margin-left: 0; margin-top: 3px; }
  }

  /* --- My Team pitch (2026-08-21 full revamp) - real pitch markings
     (halfway line + center circle, drawn as layered backgrounds - no new
     markup needed), bigger/less-cramped player cards, real depth. Direct
     user feedback addressed: "the squad module looks lackluster... looks
     so squeezed". */
  .pitch { position: relative; border-radius: 18px; padding: 30px 18px 22px;
    display: flex; flex-direction: column; gap: 22px;
    border: 2px solid rgba(255,255,255,0.18);
    box-shadow: inset 0 0 80px rgba(0,0,0,0.4), 0 12px 34px -14px rgba(0,0,0,0.65);
    background:
      /* goal boxes (top + bottom edges) */
      linear-gradient(rgba(255,255,255,0.22), rgba(255,255,255,0.22)) 50% 44px / 46% 2px no-repeat,
      linear-gradient(rgba(255,255,255,0.22), rgba(255,255,255,0.22)) 50% calc(100% - 44px) / 46% 2px no-repeat,
      /* centre circle + spot + halfway line */
      radial-gradient(circle at 50% 50%, transparent 70px, rgba(255,255,255,0.30) 70px, rgba(255,255,255,0.30) 72px, transparent 72px),
      radial-gradient(circle at 50% 50%, rgba(255,255,255,0.30) 2.5px, transparent 2.5px),
      linear-gradient(rgba(255,255,255,0.28), rgba(255,255,255,0.28)) center / 100% 2px no-repeat,
      /* outer boundary */
      linear-gradient(transparent, transparent) padding-box,
      repeating-linear-gradient(180deg, var(--pitch-1), var(--pitch-1) 46px, var(--pitch-2) 46px, var(--pitch-2) 92px); }
  .pitch-zone { position: relative; z-index: 1; }
  .zone-label { text-align: center; font-family: "Titillium Web", sans-serif; font-size: 0.66rem; font-weight: 800;
    letter-spacing: 0.16em; text-transform: uppercase; color: rgba(255,255,255,0.55); margin-bottom: 8px; }
  .pitch-row { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; position: relative; z-index: 1; }
  .bench-label { font-size: 0.74rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em;
    font-weight: 700; margin: 16px 0 8px; display: flex; align-items: center; gap: 8px; }
  .bench-label::after { content: ""; flex: 1; height: 1px; background: var(--gridline); }
  .bench-row { background: linear-gradient(180deg, var(--surface-2), var(--bg)); border-radius: 14px;
    padding: 14px; border: 1px solid var(--border); }
  .bench-row .player-card { min-width: 116px; padding: 9px 9px 8px; }
  .bench-row .player-photo-wrap { width: 52px; height: 52px; }
  .bench-row .player-shirt { width: 52px; height: 52px; }
  .bench-row .player-name { font-size: 0.88rem; max-width: 130px; }
  .bench-order { position: absolute; top: -8px; left: -8px; width: 20px; height: 20px; border-radius: 50%;
    background: var(--surface-2); border: 2px solid var(--bg); color: var(--muted); font-size: 0.62rem;
    font-weight: 800; display: flex; align-items: center; justify-content: center; z-index: 2; }

  .player-card { position: relative; background: linear-gradient(180deg, #ffffff, #f4f2f8); color: #14161a;
    border-radius: 14px; padding: 12px 12px 11px; min-width: 148px; text-align: center;
    box-shadow: 0 5px 16px -5px rgba(0,0,0,0.5), 0 1px 3px rgba(0,0,0,0.3);
    border-top: 4px solid var(--accent-l); transition: transform 0.15s ease, box-shadow 0.15s ease;
    cursor: default; }
  .player-card:hover { transform: translateY(-4px) scale(1.02); box-shadow: 0 12px 26px -8px rgba(0,0,0,0.6), 0 1px 3px rgba(0,0,0,0.3);
    z-index: 5; }
  .player-card:focus-within { outline: 2px solid var(--accent-2); outline-offset: 2px; }
  .player-card.is-captain { box-shadow: 0 0 0 2px #e9a400, 0 6px 22px -6px rgba(233,164,0,0.55); }
  @media (prefers-color-scheme: dark) { .player-card { border-top-color: var(--accent-d); } }
  .player-photo-wrap { position: relative; width: 68px; height: 68px; margin: 0 auto 4px;
    display: flex; align-items: center; justify-content: center; }
  .player-shirt { width: 68px; height: 68px; object-fit: contain; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4)); }
  .shirt-fallback { width: 52px; height: 46px; border-radius: 6px; background: var(--accent-d); opacity: 0.35; }
  .player-name { font-weight: 800; font-size: 1.01rem; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; max-width: 170px; letter-spacing: -0.01em; }
  .player-meta { font-size: 0.78rem; color: #5a5964; margin-top: 2px; font-weight: 600; }
  .player-xp { font-size: 0.94rem; font-weight: 800; color: #146c3a; margin-top: 5px; }
  .player-xp .unit { font-weight: 600; color: #706f7a; font-size: 0.72rem; }
  .armband { position: absolute; top: -10px; right: -8px; width: 24px; height: 24px; border-radius: 50%;
    font-size: 0.66rem; font-weight: 900; display: flex; align-items: center; justify-content: center;
    border: 2.5px solid #fff; z-index: 2; box-shadow: 0 2px 6px rgba(0,0,0,0.4); }
  .armband.cap { background: linear-gradient(135deg, #ffd873, #e9a400); color: #3a2400; }
  .armband.vc { background: linear-gradient(135deg, #ece9de, #c3c2b7); color: #2a2a24; }
  .lineup-badge { display: inline-block; margin-top: 5px; font-size: 0.62rem; font-weight: 800;
    text-transform: uppercase; letter-spacing: 0.03em; border-radius: 999px; padding: 2px 8px; }
  .lineup-ok { background: rgba(0,255,135,0.18); color: #0a7d0a; }
  .lineup-warn { background: rgba(250,178,25,0.2); color: #8a5c00; }
  .lineup-bad { background: rgba(233,0,82,0.16); color: #a0093a; }

  /* Hover tooltip (2026-08-21) - real data only (floor/median/ceiling,
     confidence, expected minutes) already computed for this card, no new
     query. Pure CSS reveal, no JS - keeps every other card's hover cheap. */
  .player-tooltip { position: absolute; left: 50%; bottom: calc(100% + 10px); transform: translateX(-50%) translateY(4px);
    width: 190px; background: #17101f; color: #fff; border: 1px solid rgba(255,255,255,0.14);
    border-radius: 10px; padding: 10px 12px; font-size: 0.74rem; line-height: 1.5; text-align: left;
    box-shadow: 0 10px 26px -8px rgba(0,0,0,0.7); opacity: 0; pointer-events: none;
    transition: opacity 0.15s ease, transform 0.15s ease; z-index: 10; }
  .player-tooltip::after { content: ""; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
    border: 6px solid transparent; border-top-color: #17101f; }
  .player-card:hover .player-tooltip, .player-card:focus-within .player-tooltip {
    opacity: 1; transform: translateX(-50%) translateY(0); }
  .player-tooltip-row { display: flex; justify-content: space-between; gap: 10px; color: rgba(255,255,255,0.75); }
  .player-tooltip-row strong { color: #fff; font-weight: 700; }
  /* Real fixture-difficulty dot inside the tooltip's "Next fixture" row -
     same real ok/warn/bad classes the Fixture Ticker cells already use. */
  .fdr-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 4px; }
  .fdr-dot-ok { background: var(--ok); }
  .fdr-dot-warn { background: var(--warn); }
  .fdr-dot-bad { background: var(--bad); }

  /* --- Team Outlook --- */
  /* --- Fixture Ticker sort toggle (2026-08-21, per fpl.page's own
     per-widget sort controls) - real interactivity, not decoration: every
     serious analytical tool lets you re-order its own tables. --- */
  .fdr-sort { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
  .freshness-tag { font-size: 0.66rem; color: var(--faint); margin-left: auto; white-space: nowrap; }
  .fdr-sort-label { font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--faint); margin-right: 2px; }
  .fdr-sort-btn { font-size: 0.72rem; font-weight: 600; color: var(--muted); background: var(--surface-2);
    border: 1px solid var(--border); border-radius: 999px; padding: 4px 11px; cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease; }
  .fdr-sort-btn:hover { color: var(--fg); }
  .fdr-sort-btn.is-active { background: color-mix(in srgb, var(--accent) 22%, var(--surface-2));
    color: var(--fg); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
  #refresh-countdown { font-variant-numeric: tabular-nums; font-weight: 700; }
  /* --- Fixture Ticker --- */
  .panel-ticker { grid-column: 1 / -1; }  /* full width - 20 teams x rich cells needs real room */
  .fdr-grid { display: flex; flex-direction: column; gap: 5px; max-height: 480px; overflow-y: auto;
    overflow-x: auto; border-radius: 10px; }
  .fdr-row { display: flex; align-items: stretch; gap: 8px; min-width: 588px; border-radius: 8px;
    transition: background 0.12s ease; }
  .fdr-row:hover { background: var(--surface-2); }
  .fdr-row-squad { background: color-mix(in srgb, var(--accent) 12%, transparent); }
  .fdr-row-squad:hover { background: color-mix(in srgb, var(--accent) 18%, transparent); }
  /* Sticky team column (2026-08-21) - a real, functional fix: the whole
     row used to scroll horizontally as one unit, so the team name
     scrolled off-screen with the fixtures on a wide 20-team x N-GW grid,
     making it impossible to tell which row you were reading once
     scrolled. Now pinned to the left edge of the scroll container. */
  .fdr-team { position: sticky; left: 0; z-index: 2; width: 74px; flex-shrink: 0; font-weight: 800;
    font-size: 0.74rem; display: flex; align-items: center; gap: 6px; background: var(--surface);
    padding-left: 4px; border-radius: 8px 0 0 8px; }
  /* Real club crest (2026-08-21, per LiveFPL/fpl.page study) - same official
     PL asset domain family this project already uses for kit shirts, real
     confirmed precedent (fpl.page hotlinks the identical CDN path). The
     single cheapest, highest-leverage "this looks official" signal found -
     replaces a bare 3-letter code with real team identity. */
  .fdr-badge { width: 18px; height: 18px; object-fit: contain; flex-shrink: 0; }
  .fdr-row-squad .fdr-team { background: color-mix(in srgb, var(--accent) 45%, var(--surface)); color: #fff; }
  .fdr-cells { display: flex; gap: 4px; flex: 1; }
  .fdr-cell { flex: 1; text-align: center; padding: 4px 2px; border-radius: 5px; font-size: 0.62rem;
    font-weight: 700; color: #14161a; white-space: nowrap; position: relative; transition: transform 0.12s ease; }
  .fdr-cell:hover { transform: scale(1.06); z-index: 3; }
  .fdr-opp { font-size: 0.68rem; margin-bottom: 1px; }
  .fdr-stat { font-weight: 500; font-size: 0.6rem; opacity: 0.85; }
  /* Heatmap gradient scale (2026-08-21) instead of flat solid blocks -
     each difficulty tier gets its own gradient so the ticker reads as a
     real intensity heatmap, not five identical color chips. */
  .fdr-ok { background: linear-gradient(155deg, #1fb866, var(--ok)); }
  .fdr-warn { background: linear-gradient(155deg, #f7b733, var(--warn)); }
  .fdr-bad { background: linear-gradient(155deg, var(--bad), #c23a4a); color: #fff; }
  .fdr-blank { background: var(--surface-2); color: var(--faint); font-weight: 400; display: flex;
    align-items: center; justify-content: center; }

  .outlook-grid { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto; }
  .outlook-card { background: var(--surface-2); border-radius: 8px; padding: 8px 10px; font-size: 0.8rem; }
  .outlook-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 3px; }
  .outlook-badge { width: 18px; height: 18px; object-fit: contain; flex-shrink: 0; }
  .outlook-fixtures { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 0.76rem; margin-top: 2px; }
  .outlook-fixtures .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .outlook-chip { font-size: 0.65rem; font-weight: 600; color: var(--muted); background: var(--surface);
    border: 1px solid var(--border); border-radius: 999px; padding: 1px 7px; }
  .outlook-alert { color: var(--bad); border-color: var(--bad); }
  .outlook-churn { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 0.76rem; }
  .outlook-churn .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .dot-ok { background: var(--ok); }
  .dot-warn { background: var(--warn); }
  .dot-bad { background: var(--bad); }
  .outlook-news { margin-top: 4px; color: var(--muted); font-size: 0.76rem; line-height: 1.35; }

  /* --- Chip Strategy --- */
  .chip-strategy-list { display: flex; flex-direction: column; gap: 6px; }
  .chip-strategy-row { display: flex; align-items: center; justify-content: space-between; gap: 8px;
    font-size: 0.82rem; padding: 7px 10px; background: var(--surface-2); border-radius: 8px; }
  .chip-strategy-name { font-weight: 700; text-transform: capitalize; }
  .chip-strategy-window { color: var(--faint); font-size: 0.72rem; }
  .chip-value { font-weight: 700; color: var(--ok-text); font-size: 0.78rem; }
  .chip-value-age { color: var(--faint); font-weight: 500; font-size: 0.68rem; margin-left: 4px; }
  .chip-value-muted { color: var(--faint); font-weight: 500; font-size: 0.7rem; }
  .chip-advisory { margin-top: 4px; font-size: 0.76rem; color: var(--muted); font-style: italic; }

  /* --- Live tracking (real visual redesign 2026-08-21) --- */
  .live-pending { display: flex; align-items: flex-start; gap: 10px; font-size: 0.88rem; color: var(--muted); line-height: 1.4; }
  .live-next { margin: 10px 0 12px; font-size: 0.85rem; }
  .fixture-grid { display: flex; flex-direction: column; gap: 6px; }
  /* Real date-group divider (2026-08-21, per fpl.page's own date-header
     rows) - quiet by design (this project's own restraint standard), a
     label + rule rather than a loud colored bar. */
  .fx-date-divider { display: flex; align-items: center; gap: 8px; font-size: 0.66rem; font-weight: 800;
    text-transform: uppercase; letter-spacing: 0.06em; color: var(--faint); margin: 10px 0 2px; }
  .fx-date-divider:first-child { margin-top: 0; }
  .fx-date-divider::after { content: ""; flex: 1; height: 1px; background: var(--gridline); }
  .fx-card { display: flex; align-items: center; justify-content: space-between; gap: 6px;
    padding: 8px 10px; background: var(--surface-2); border-radius: 10px; }
  .fx-side { display: flex; align-items: center; gap: 6px; flex: 1; }
  .fx-side:last-child { flex-direction: row-reverse; text-align: right; }
  .fx-shirt { width: 26px; height: 26px; object-fit: contain; flex-shrink: 0; }
  .fx-crest { width: 22px; height: 22px; object-fit: contain; flex-shrink: 0; }
  .fx-code { font-weight: 700; font-size: 0.78rem; }
  .fx-mid { flex-shrink: 0; min-width: 84px; text-align: center; }
  .fx-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 0.68rem; font-weight: 700;
    padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
  .fx-badge-pre { background: var(--surface); color: var(--muted); border: 1px solid var(--border); }
  .fx-badge-live { background: var(--fpl-pink); color: #fff; }
  .fx-badge-ft { background: var(--faint); color: #fff; opacity: 0.7; }
  .live-now-tag { display: inline-flex; align-items: center; gap: 6px; font-family: "Titillium Web", sans-serif;
    font-size: 0.7rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent-2);
    margin-bottom: 8px; }
  .live-now-tag .pulse-dot { background: var(--accent-2); box-shadow: 0 0 0 0 rgba(0,255,135,0.5); }
  .live-row { display: flex; align-items: center; gap: 8px; font-size: 0.82rem; padding: 6px 8px;
    background: var(--surface-2); border-radius: 6px; margin-bottom: 4px; flex-wrap: wrap; }
  .live-stat { color: var(--muted); }
  .bonus-badge { background: var(--ok); color: #fff; font-weight: 700; border-radius: 999px; padding: 1px 7px; font-size: 0.72rem; }
  .bonus-provisional { color: var(--warn); font-size: 0.7rem; }
  .bonus-confirmed { color: var(--ok-text); font-size: 0.7rem; font-weight: 600; }
  .defcon-progress { color: var(--muted); font-size: 0.72rem; }
  .defcon-reached { background: var(--accent-2); color: #fff; font-weight: 700; border-radius: 999px;
    padding: 1px 7px; font-size: 0.72rem; }
  .warn-state { color: var(--warn); font-size: 0.85rem; }

  .empty-state { color: var(--faint); font-size: 0.85rem; font-style: italic; }

  .real-team-manager { font-weight: 700; font-size: 0.9rem; margin-bottom: 2px; }
  .real-team-season { color: var(--faint); font-size: 0.78rem; }
  .real-team-stats { color: var(--accent-2); font-weight: 600; font-size: 0.8rem; margin: 6px 0 10px; }

  /* --- Your Team vs Optimized comparison (2026-08-21) --- */
  /* Real "what changes" delta strip (2026-08-21, third session, section
     13) - sits above the two side-by-side panels, plain diffed values. */
  .compare-delta { display: flex; flex-wrap: wrap; gap: 4px 6px; align-items: center; font-size: 0.82rem;
    color: var(--muted); margin-bottom: 12px; }
  .compare-delta-pt { font-weight: 800; font-family: "Titillium Web", sans-serif; }
  .compare-delta-pt.pos { color: var(--ok-text); }
  .compare-delta-pt.neg { color: var(--bad); }
  .compare-grid { display: grid; grid-template-columns: 1fr auto 1fr; gap: 16px; align-items: center; }
  .compare-side { background: var(--surface-2); border-radius: 14px; padding: 16px 18px; border: 1px solid var(--border); }
  .compare-side.compare-optimized { border-color: color-mix(in srgb, var(--accent-2) 40%, var(--border)); }
  .compare-label { font-family: "Titillium Web", sans-serif; font-size: 0.7rem; font-weight: 800;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 10px; }
  .compare-vs { font-family: "Titillium Web", sans-serif; font-weight: 900; font-size: 0.85rem;
    color: var(--faint); text-align: center; }
  .compare-metric { display: flex; justify-content: space-between; align-items: baseline; padding: 4px 0;
    font-size: 0.85rem; border-bottom: 1px solid var(--gridline); }
  .compare-metric:last-child { border-bottom: none; }
  .compare-metric-value { font-weight: 800; font-variant-numeric: proportional-nums; }
  @media (max-width: 640px) { .compare-grid { grid-template-columns: 1fr; } .compare-vs { padding: 2px 0; } }

  /* --- Decision Center (2026-08-21) - reorganizes existing computed data
     (captain choice, latest transfer decision, risk count, chip
     eligibility) into one "what should I actually do" panel - no new
     computation, real data only. --- */
  .decision-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
  /* Captain is always the first card and the single most-scanned decision on
     this panel - real visual dominance (span, bigger type), not equal-weight
     with Transfer/Risk/Chip (spec section 8: "make recommendations visually
     decisive"). Harmless no-op on a narrow viewport - auto-fit already
     collapses to one column there. */
  .decision-grid .decision-card:first-child { grid-column: span 2; }
  .decision-grid .decision-card:first-child .decision-headline { font-size: 1.4rem; }
  /* Real bug (second polish pass, confirmed via computed styles, not
     guessed): auto-fit/minmax(220px,1fr) has a genuine edge case around
     ~318-370px container widths where it computes a second column far BELOW
     its own 220px minimum (measured live: "220px 98.8px") instead of
     collapsing to one - crushing the Risks/Transfer cards unreadably
     narrow. Forcing a single column below 640px sidesteps the edge case
     entirely. Placed AFTER the base .decision-grid rule on purpose - an
     earlier copy of this same override silently lost the cascade (equal
     specificity, later unconditional rule wins over an earlier
     media-scoped one), caught by re-measuring rendered card widths after
     the first attempt rather than trusting the diff alone. */
  @media (max-width: 640px) {
    .decision-grid { grid-template-columns: 1fr; }
    .decision-grid .decision-card:first-child { grid-column: 1; }
  }
  .decision-card { background: var(--surface-2); border-radius: 14px; padding: 14px 16px; border: 1px solid var(--border);
    border-left: 3px solid var(--accent); }
  .decision-card.decision-alert { border-left-color: var(--fpl-pink); }
  .decision-card.decision-positive { border-left-color: var(--accent-2); }
  .decision-kicker { font-family: "Titillium Web", sans-serif; font-size: 0.65rem; font-weight: 800;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 6px;
    display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .decision-headline { font-weight: 800; font-size: 1rem; margin-bottom: 4px; }
  .decision-detail { font-size: 0.8rem; color: var(--muted); line-height: 1.4; }
  .decision-metric { font-family: "Titillium Web", sans-serif; font-weight: 800; color: var(--accent-2); font-size: 0.88rem; }
  /* Real action language (2026-08-21, third session, section 11: "these
     are your actions" not "information about decisions") - a quiet text
     tag, never a fake clickable button (this project has no capability to
     act on it - section 83, recommend only). */
  .decision-action { font-size: 0.62rem; font-weight: 800; letter-spacing: 0.04em; color: var(--faint);
    background: var(--surface); border: 1px solid var(--border); border-radius: 5px; padding: 2px 6px; }
  /* Real confidence-tier badge (2026-08-21, fourth session, section 4) - a
     direct relabeling of the model's own real HIGH/MEDIUM/LOW confidence
     field, never a fabricated score. */
  .decision-tier { font-size: 0.6rem; font-weight: 800; letter-spacing: 0.05em; border-radius: 999px;
    padding: 2px 8px; }
  .decision-tier-strong { background: rgba(0,255,135,0.16); color: var(--ok-text); }
  .decision-tier-good { background: rgba(251,191,36,0.16); color: #d4a017; }
  .decision-tier-watch { background: rgba(255,255,255,0.08); color: var(--faint); }
  /* Real explainability bullets (2026-08-21, third session, section 12) -
     compact, quiet, real data only (delta vs next-best captain, penalty
     duty, expected minutes, differential note) - never a new card. */
  .decision-reasons-label { font-size: 0.66rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--faint); margin: 10px 0 4px; }
  .decision-reasons { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 3px; }
  .decision-reasons li { font-size: 0.76rem; color: var(--muted); padding-left: 13px; position: relative; }
  .decision-reasons li::before { content: "+"; position: absolute; left: 0; color: var(--accent-2); font-weight: 800; }

  /* --- Risk monitor (2026-08-21) - severity-tiered rows replacing a
     plain bulleted list. --- */
  .risk-monitor { display: flex; flex-direction: column; gap: 6px; }
  .risk-row { display: flex; align-items: center; gap: 10px; padding: 9px 11px; background: var(--surface-2);
    border-radius: 10px; font-size: 0.84rem; }
  .risk-severity { flex-shrink: 0; font-family: "Titillium Web", sans-serif; font-size: 0.62rem; font-weight: 800;
    letter-spacing: 0.03em; text-transform: uppercase; padding: 3px 9px; border-radius: 999px; white-space: nowrap; }
  .risk-severity-low { background: rgba(34,197,94,0.16); color: var(--ok-text); }
  .risk-severity-monitor { background: rgba(251,191,36,0.18); color: #b8860b; }
  .risk-severity-action { background: rgba(233,0,82,0.18); color: #ff6b9d; }
  .risk-body strong { color: var(--fg); }
  .risk-body { color: var(--muted); }
  .risk-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: 0.85rem; }
  .risk-list li { display: flex; align-items: flex-start; gap: 8px; }
  .risk-list .dot { width: 7px; height: 7px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
  .ok-line .dot { background: var(--ok); }
  .warn-line .dot { background: var(--warn); }

  .news-list { display: flex; flex-direction: column; gap: 10px; }
  .news-item { padding-bottom: 10px; border-bottom: 1px solid var(--gridline); }
  .news-item:last-child { border-bottom: none; padding-bottom: 0; }
  /* Editorial emphasis (2026-08-21, third session, section 14) - real,
     derived relevance (name-matched to the actual squad), not equal
     weight for every article. Quiet by design: a left accent bar + one
     small tag, not a colored background wash. */
  .news-item-relevant { border-left: 2px solid var(--accent-2); padding-left: 10px; margin-left: -12px; }
  .news-relevance { font-size: 0.66rem; font-weight: 700; color: var(--accent-2); text-transform: uppercase;
    letter-spacing: 0.03em; }
  .news-title a { color: var(--fg); text-decoration: none; font-size: 0.88rem; font-weight: 600; }
  .news-title a:hover { color: var(--accent); }
  .news-meta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 4px; }
  /* Quieted (second polish pass) - every synced item currently shares the
     same real source tier, so a loud accent-colored badge repeated on every
     row communicated nothing; kept as plain metadata text instead, same
     weight class as change-time/chip-value-age elsewhere on this page. */
  .source-tag { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.03em; color: var(--faint);
    font-weight: 600; }
  .news-time { font-size: 0.72rem; color: var(--faint); }
  .tag { font-size: 0.7rem; background: var(--surface-2); color: var(--muted); border-radius: 999px; padding: 1px 8px; }
  .tag-team { color: var(--accent); }

  /* Squad Changes + Price Moves merged into one Activity panel (2026-08-21
     second pass, spec section 22 "card reduction" - two separate Tier-1
     event-feed cards collapsed into one, real data unchanged, just fewer
     cards competing for attention in the intelligence grid). */
  .activity-group-label { font-size: 0.68rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--faint); margin: 12px 0 6px; }
  .activity-group-label:first-of-type { margin-top: 0; }
  .change-list { display: flex; flex-direction: column; gap: 4px; max-height: 200px; overflow-y: auto; }
  .change-item { display: flex; align-items: center; gap: 8px;
    font-size: 0.82rem; padding: 6px 8px; background: var(--surface-2); border-radius: 6px; }
  /* Real event-direction indicator (second polish pass) - a status change
     TOWARD availability reads calmly positive, one AWAY from it reads as a
     real warning, purely quiet dots (never re-coloring the whole row) so
     the feed stays scannable rather than turning into a wall of color. */
  .change-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .change-dot-good { background: var(--ok); }
  .change-dot-bad { background: var(--bad); }
  .change-dot-neutral { background: var(--faint); }
  /* Real event-category tag (2026-08-21, third session, section 15) - the
     actual change_events.event_type this row already carries, labeled. */
  .change-category { font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em;
    color: var(--faint); background: var(--surface); border-radius: 4px; padding: 1px 6px; flex-shrink: 0; }
  .change-desc { color: var(--fg); flex: 1; }
  .change-time { font-size: 0.72rem; color: var(--faint); flex-shrink: 0; }

  /* --- Match Feed (live-match-feed pass, 2026-08-21) - a real
     minute/type/description ticker, never fabricated - compact rows, not
     a card wall (section 9 of the spec: "extremely scannable"). --- */
  .match-feed { display: flex; flex-direction: column; gap: 3px; max-height: 260px; overflow-y: auto; }
  .match-feed-item { display: flex; align-items: baseline; gap: 8px; font-size: 0.86rem;
    padding: 6px 8px; background: var(--surface-2); border-radius: 6px; }
  .match-feed-minute { font-family: "Titillium Web", sans-serif; font-weight: 800; font-size: 0.9rem;
    color: var(--accent); flex-shrink: 0; min-width: 2.6em; }
  .match-feed-type { font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em;
    color: var(--faint); background: var(--surface); border-radius: 4px; padding: 1px 6px; flex-shrink: 0; }
  .match-feed-desc { color: var(--fg); flex: 1; }

  /* --- Dashboard-state architecture (2026-08-21): one real signal
     (dash_state, computed in generate_dashboard_html) reorders the SAME
     panels by choosing which already-built section string renders first -
     never a second dashboard, never duplicated markup (see
     "ordered_panels_html" in dashboard.py - real DOM reordering, not a
     CSS `order` property, since these sections have no shared flex/grid
     parent for `order` to act on). This block is purely the visual
     emphasis half: the LIVE state's promoted Live Tracking panel gets a
     real glowing accent border so it reads as "this is what matters right
     now", not just a change in position. --- */
  .hero-xp-live { color: var(--accent-2); text-shadow: 0 0 24px color-mix(in srgb, var(--accent-2) 45%, transparent); }
  .panel-live-emphasis { border-color: var(--accent-2);
    box-shadow: 0 0 0 1px var(--accent-2), 0 12px 34px -14px color-mix(in srgb, var(--accent-2) 35%, transparent); }

  .price-list { display: flex; flex-direction: column; gap: 4px; }
  .price-item { display: flex; align-items: center; gap: 8px; font-size: 0.82rem; padding: 6px 8px;
    background: var(--surface-2); border-radius: 6px; }
  .price-up { color: var(--ok); font-weight: 700; }
  .price-down { color: var(--bad); font-weight: 700; }

  /* --- System health chips --- */
  .chip-grid { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { display: flex; align-items: center; gap: 6px; font-size: 0.76rem; background: var(--surface-2);
    border-radius: 999px; padding: 5px 10px 5px 8px; }
  .chip .dot { width: 7px; height: 7px; border-radius: 50%; }
  .chip-ok .dot { background: var(--ok); }
  .chip-warn .dot { background: var(--warn); }
  .chip-bad .dot { background: var(--bad); }
  .chip-name { font-weight: 600; }
  .chip-status { color: var(--muted); }
  .chip-detail { color: var(--faint); }

  .health-summary { display: flex; align-items: center; gap: 8px; font-size: 0.9rem;
    font-weight: 600; padding: 4px 0 10px; }
  .health-summary .dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
  .health-summary-ok { color: var(--ok-text); }
  .health-summary-ok .dot { background: var(--ok); }
  .health-summary-warn { color: var(--warn); }
  .health-summary-warn .dot { background: var(--warn); }
  .health-details summary { cursor: pointer; color: var(--muted); font-size: 0.82rem;
    padding: 4px 0; list-style: none; }
  .health-details summary::-webkit-details-marker { display: none; }
  .health-details summary::before { content: "▸ "; }
  .health-details[open] summary::before { content: "▾ "; }
  .health-details .chip-grid { margin-top: 8px; }

  /* --- Motion, focus, accessibility (2026-08-21) --- */
  .panel, .hero-primary, .hero-metric { animation: fade-slide-in 0.35s ease both; }
  @keyframes fade-slide-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
  a:focus-visible, button:focus-visible, summary:focus-visible, .btn-refresh:focus-visible,
  .site-nav a:focus-visible { outline: 2px solid var(--accent-2); outline-offset: 2px; border-radius: 4px; }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.001ms !important; animation-iteration-count: 1 !important;
      transition-duration: 0.001ms !important; scroll-behavior: auto !important; }
  }
  /* Real mobile pitch fix (second polish pass, measured not guessed):
     .player-card's 148px min-width leaves a 375px phone with only 278px of
     real row width after the pitch/panel/body padding stack - two cards
     need 308px (148*2 + 12 gap), so every row was silently forced to one
     card each, turning the pitch into one long single-file scroll instead
     of a real formation shape. Shrinks the card (and its shirt/text) just
     enough for 2 per row at real phone widths - not a blanket font-size
     cut, a genuine width fix. */
  @media (max-width: 480px) {
    .pitch { padding: 26px 8px 16px; }
    .pitch-row { gap: 8px; }
    .player-card { min-width: 112px; padding: 9px 8px 8px; }
    .player-photo-wrap { width: 52px; height: 52px; }
    .player-shirt { width: 52px; height: 52px; }
    .player-name { font-size: 0.85rem; max-width: 108px; }
    .player-meta { font-size: 0.67rem; }
    .player-xp { font-size: 0.82rem; }
  }
  html { scroll-behavior: smooth; }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--surface-2); border-radius: 999px; border: 2px solid var(--bg); }
  ::-webkit-scrollbar-thumb:hover { background: var(--accent); }
"""
