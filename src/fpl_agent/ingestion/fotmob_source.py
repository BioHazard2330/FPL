"""FotMob match-intelligence source (Pillar 4 Slice A). Public JSON endpoints,
no auth/key required - live-verified 2026-08-21 (see docs/superpowers/specs/
2026-08-21-match-intelligence-core-design.md). Real match ids are always
resolved via the date-scoped fixture list, never hardcoded."""
from datetime import date as date_cls
from datetime import datetime, timezone

import requests

from fpl_agent.events.bus import Event, bus as _event_bus
from fpl_agent.events.types import EventType
from fpl_agent.ingestion.analysis_queue import enqueue_analysis_job
from fpl_agent.ingestion.market_identity import (
    COMMON_TEAM_NAME_ALIASES,
    get_or_create_market_team,
    normalize_common_team_name,
)
from fpl_agent.ingestion.predicted_lineups_source import match_player_in_team
from fpl_agent.ingestion.raw_store import save_raw
from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.models.match_intelligence import (
    FULL_TIME,
    HALFTIME,
    LIVE,
    PRE_MATCH,
    parse_match,
    parse_match_events,
    parse_momentum,
    parse_player_states,
    parse_shot_map,
    parse_team_states,
)

_MATCHES_URL = "https://www.fotmob.com/api/data/matches"
_MATCH_DETAILS_URL = "https://www.fotmob.com/api/data/matchDetails"
_TIMEOUT_SECONDS = 15
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_SOURCE_NAME = "fotmob"


class FotMobFetchError(Exception):
    pass


def _get(url: str, params: dict) -> dict:
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            message = f"fotmob request failed: HTTP {response.status_code} ({url})"
        else:
            message = f"fotmob request failed: request error ({url})"
        raise FotMobFetchError(message) from exc
    try:
        return resp.json()
    except ValueError as exc:
        raise FotMobFetchError(f"fotmob returned non-JSON response ({url})") from exc


def fetch_matches_for_date(day: date_cls) -> dict:
    return _get(_MATCHES_URL, {"date": day.strftime("%Y%m%d")})


# Reverse of the project's own long-form->FPL-short-form alias table
# (market_identity.py) - built once at import time. Real, live gap found
# 2026-08-22 (the first time this project actually tried to auto-discover
# a real fixture involving a club whose FPL short name isn't a substring
# match of FotMob's own longer name either way): "Nott'm Forest" vs FotMob's
# "Nottingham Forest" share no common substring run despite being the same
# club - `find_match`'s existing loose bidirectional substring check can't
# bridge that gap on its own, unlike e.g. "Coventry"/"Coventry City" which
# genuinely are substrings of each other. This reverse map lets `find_match`
# also try the long form FotMob is more likely to use whenever the caller's
# own name happens to be a known FPL-short-form alias target.
# A list per short form, not a single value - real gap found live
# 2026-08-22: "Man Utd" has TWO known long-form aliases in the source dict
# ("manchester united" and "man united", the latter being football-data.
# co.uk's own short form) and FotMob's real listing uses neither exactly
# ("Man United") - only trying the first alias (a single-value dict would
# have picked "manchester united" and missed the one that actually
# substring-matches FotMob's real name) silently failed to find a real,
# live Hull vs Man United fixture.
_REVERSE_TEAM_NAME_ALIASES: dict[str, list[str]] = {}
for _long, _short in COMMON_TEAM_NAME_ALIASES.items():
    _REVERSE_TEAM_NAME_ALIASES.setdefault(_short.strip().lower(), []).append(_long)


def _strip_punctuation(name: str) -> str:
    # Real, live gap found 2026-08-22: FPL's "Nott'm Forest" vs FotMob's own
    # "Nottm Forest" - same club, differ only by an apostrophe. Stripping
    # apostrophes/periods before comparison is a general fix (any future
    # club-name punctuation mismatch, not just this one), not a Forest-
    # specific special case.
    return name.replace("'", "").replace(".", "")


def _name_candidates(team_name: str) -> list[str]:
    lower = team_name.strip().lower()
    candidates = {lower, _strip_punctuation(lower)}
    for alt in _REVERSE_TEAM_NAME_ALIASES.get(lower, []):
        candidates.add(alt)
        candidates.add(_strip_punctuation(alt))
    return list(candidates)


def find_match(day: date_cls, home_team_name: str, away_team_name: str) -> str | None:
    """Searches every league FotMob returns for that date for a case-insensitive
    substring match on both team names - real fixture names sometimes carry a
    club suffix FPL's own short name doesn't (e.g. FotMob's "Coventry City" vs
    FPL's "Coventry"), so this is intentionally loose in both directions
    rather than an exact-equality match. Also tries each name's known
    long-form alias (see `_REVERSE_TEAM_NAME_ALIASES` above) for the real
    cases where the two names share no substring at all (e.g. "Nott'm
    Forest" vs "Nottingham Forest"). Returns the first match found; raises
    nothing - `None` means genuinely not found, caller decides what to do."""
    payload = fetch_matches_for_date(day)
    home_candidates = _name_candidates(home_team_name)
    away_candidates = _name_candidates(away_team_name)
    for league in payload.get("leagues", []):
        for match in league.get("matches", []):
            match_home = _strip_punctuation((match.get("home", {}).get("name") or "").lower())
            match_away = _strip_punctuation((match.get("away", {}).get("name") or "").lower())
            home_hit = any(c in match_home or match_home in c for c in home_candidates)
            away_hit = any(c in match_away or match_away in c for c in away_candidates)
            if home_hit and away_hit:
                return str(match["id"])
    return None


def fetch_match_details(fotmob_match_id: str) -> dict:
    return _get(_MATCH_DETAILS_URL, {"matchId": fotmob_match_id})


def _resolve_fpl_team_id(conn, team_name: str) -> int | None:
    market_id = get_or_create_market_team(conn, _SOURCE_NAME, normalize_common_team_name(team_name))
    row = conn.execute("SELECT fpl_team_id FROM market_teams WHERE id=?", (market_id,)).fetchone()
    return row["fpl_team_id"] if row and row["fpl_team_id"] is not None else None


def _resolve_fpl_fixture_id(conn, home_team_id: int | None, away_team_id: int | None, kickoff_utc: str | None) -> int | None:
    if home_team_id is None or away_team_id is None:
        return None
    row = conn.execute(
        "SELECT id FROM fixtures WHERE team_h=? AND team_a=?", (home_team_id, away_team_id)
    ).fetchone()
    return row["id"] if row else None


_REFRESH_LOOKBACK_HOURS = 8
_REFRESH_LOOKAHEAD_HOURS = 1


def refresh_in_progress_matches(conn, tracked_squad_ids: set[int] | None = None) -> dict:
    """The automatic PRE_MATCH->LIVE->HALFTIME->FULL_TIME detection hook
    (Slice A2, spec section 4) - re-syncs every match_intelligence row that
    isn't yet FULL_TIME and whose kickoff falls in a bounded recent window,
    using the real team names already stored (never a new "tracked match"
    registry). Wired into `fpl run-scheduled` (already running every 30min) -
    this is the whole "lightest reliable hook", no new daemon. Per-row
    failures are caught and counted, never abort the batch - the same
    posture every other run-scheduled step already uses.

    `tracked_squad_ids` (2026-08-22, automation-lifecycle pass) - optional,
    default `None` (unchanged behavior). Threaded straight through to
    `sync_match` so a real lineup-confirmation transition fires the
    corresponding change_events row automatically on this cadence too, not
    only from `fpl live-match-poll`'s faster loop.

    Real fast-engine wiring (2026-08-29, "live architecture rebuild" pass) -
    registers `live/fast_engine.py`'s real event-bus subscribers against
    THIS connection before any real `sync_match` call below can publish an
    event for them to react to. Safe to call every real invocation of this
    function (a fresh process each time - see `fast_engine.register`'s own
    docstring on why repeat registration is only a real concern within one
    long-lived process, e.g. this project's own test suite)."""
    from fpl_agent.live import fast_engine as _fast_engine
    from fpl_agent.live import materiality_engine as _materiality_engine

    _fast_engine.register(conn, _event_bus)
    _materiality_engine.register(_event_bus)
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT mi.id, mi.fotmob_match_id, mi.status AS prior_status, mi.kickoff_utc, "
        "ht.name AS home_name, at.name AS away_name "
        "FROM match_intelligence mi "
        "JOIN teams ht ON ht.id = mi.home_team_id "
        "JOIN teams at ON at.id = mi.away_team_id "
        "WHERE mi.status != 'FULL_TIME'"
    ).fetchall()

    refreshed = skipped = failed = 0
    for row in rows:
        if not row["kickoff_utc"]:
            skipped += 1
            continue
        try:
            kickoff = datetime.fromisoformat(row["kickoff_utc"].replace("Z", "+00:00"))
        except ValueError:
            skipped += 1
            continue
        hours_since_kickoff = (now - kickoff).total_seconds() / 3600
        if hours_since_kickoff < -_REFRESH_LOOKAHEAD_HOURS or hours_since_kickoff > _REFRESH_LOOKBACK_HOURS:
            skipped += 1
            continue
        try:
            sync_match(conn, row["home_name"], row["away_name"], kickoff.date(), tracked_squad_ids)
            refreshed += 1
        except FotMobFetchError:
            failed += 1

    return {"refreshed": refreshed, "skipped": skipped, "failed": failed}


def maybe_enqueue_analysis(
    conn, match_id: int, prior_status: str, home_name: str, away_name: str, result: dict,
) -> None:
    """Real, automatic FULL_TIME/HALFTIME -> qualitative-analysis-job hook
    (matchday-autonomy pass, 2026-08-22). Called from both this project's
    real match-lifecycle entry points (this function, used by the slow
    `run-scheduled` cadence, and `fpl live-match-poll`'s own fast loop) -
    `enqueue_analysis_job`'s own (match_id, phase) idempotency means both
    detecting the same real transition is safe, never a duplicate job."""
    new_status = result["status"]
    score = f"{home_name} {result.get('home_score')}-{result.get('away_score')} {away_name}"
    if new_status == "FULL_TIME" and prior_status != "FULL_TIME":
        enqueue_analysis_job(conn, match_id, "FULL_TIME", f"{score} (final)")
        # Real, universal, zero-LLM evidence coverage (2026-08-26, "redesign
        # the missing layer" architecture audit) - fires for EVERY real
        # match the instant it finishes, not just squad-relevant ones and
        # not gated behind a human opening Claude Code to run
        # `fpl match-analyze`. Non-fatal: a real failure here (e.g. the
        # Understat backfill for this match hasn't landed yet) must never
        # block the surrounding sync/queue step.
        try:
            from fpl_agent.models.statistical_evidence import record_statistical_evidence

            record_statistical_evidence(conn, match_id)
        except Exception:
            pass
        # Deterministic ROLE_CHANGE/SET_PIECE_CHANGE/TACTICAL_CHANGE detectors
        # (2026-09-02, Phase 3 finalization) - same non-fatal posture as the
        # statistical-evidence call above, same real FULL_TIME trigger.
        try:
            from fpl_agent.models.role_signal_detectors import record_role_signal_evidence

            record_role_signal_evidence(conn, match_id)
        except Exception:
            pass
    elif new_status == "HALFTIME" and prior_status != "HALFTIME":
        enqueue_analysis_job(conn, match_id, "HALFTIME", f"{score} (halftime)")


def sync_match(
    conn, home_team_name: str, away_team_name: str, day: date_cls,
    tracked_squad_ids: set[int] | None = None,
    provider: "FootballDataProvider | None" = None,
) -> dict:
    """Resolve -> fetch -> normalize -> upsert. Idempotent: re-running (the
    intended way to refresh a LIVE match) overwrites the same rows, never
    appends. On any failure, the pre-existing match_intelligence row (if any)
    is left completely untouched - never overwritten with a blank/degraded
    state (Data Integrity rule).

    `tracked_squad_ids` (2026-08-22, automation-lifecycle pass) - optional,
    default `None` (every pre-existing call site keeps today's exact
    behavior unchanged). When given, fires the real "lineup just confirmed"
    change-detection pass (`ingestion.change_detection.detect_lineup_confirmations`)
    for any tracked squad member on either side of this match - safe to call
    on every sync regardless of whether the lineup was ALREADY confirmed
    last time (the detector's own change_events idempotency guard is what
    prevents a repeat alert, not this flag).

    `provider` (2026-08-29, "live architecture rebuild" milestone 5) -
    optional, defaults to a real `FotMobProvider()` (unchanged behavior for
    every pre-existing call site). Real, genuine swappability per the
    spec's own provider-abstraction goal: `provider.find_match`/
    `.fetch_match_details` replace the bare module-level calls this
    function used before - a future caller (or a future alternative
    provider, per the standing free-resources-only constraint this session
    already resolved to keep FotMob as the sole real implementation) can
    inject a different one without touching this function's own logic."""
    from fpl_agent.providers.football import FootballDataProvider, FotMobProvider

    provider = provider or FotMobProvider()
    try:
        fotmob_match_id = provider.find_match(day, home_team_name, away_team_name)
        if fotmob_match_id is None:
            raise FotMobFetchError(
                f"no FotMob match found for {home_team_name!r} vs {away_team_name!r} on {day.isoformat()}"
            )
        payload = provider.fetch_match_details(fotmob_match_id)
    except FotMobFetchError as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise

    raw_path = save_raw(f"{_SOURCE_NAME}_match_{fotmob_match_id}", payload)

    prior_status_row = conn.execute(
        "SELECT status FROM match_intelligence WHERE fotmob_match_id=?", (fotmob_match_id,)
    ).fetchone()
    prior_status = prior_status_row["status"] if prior_status_row else None

    match = parse_match(payload)
    player_states = parse_player_states(payload)
    team_states = parse_team_states(payload)

    now = datetime.now(timezone.utc).isoformat()
    home_fpl_team_id = _resolve_fpl_team_id(conn, match.home_team_name)
    away_fpl_team_id = _resolve_fpl_team_id(conn, match.away_team_name)
    fpl_fixture_id = _resolve_fpl_fixture_id(conn, home_fpl_team_id, away_fpl_team_id, match.kickoff_utc)

    conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, fpl_fixture_id, competition, kickoff_utc, home_team_id, away_team_id, "
        "status, home_score, away_score, source, retrieved_at, confidence, raw_source_reference, live_minute) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(fotmob_match_id) DO UPDATE SET "
        "fpl_fixture_id=excluded.fpl_fixture_id, competition=excluded.competition, kickoff_utc=excluded.kickoff_utc, "
        "home_team_id=excluded.home_team_id, away_team_id=excluded.away_team_id, status=excluded.status, "
        "home_score=excluded.home_score, away_score=excluded.away_score, retrieved_at=excluded.retrieved_at, "
        "raw_source_reference=excluded.raw_source_reference, live_minute=excluded.live_minute",
        (match.fotmob_match_id, fpl_fixture_id, match.competition, match.kickoff_utc,
         home_fpl_team_id, away_fpl_team_id, match.status, match.home_score, match.away_score,
         _SOURCE_NAME, now, "high", str(raw_path), match.live_minute),
    )
    match_id = conn.execute(
        "SELECT id FROM match_intelligence WHERE fotmob_match_id=?", (fotmob_match_id,)
    ).fetchone()["id"]

    # Real match-lifecycle events (2026-08-29, "live architecture rebuild"
    # pass, milestone 1) - published once per genuine status transition,
    # never on every tick (an unchanged status is a real no-op, not a
    # repeat event). Generalizes the FULL_TIME-only check
    # `maybe_enqueue_analysis` already made further down this function -
    # that call is unchanged, this is a real, additional dispatch onto the
    # event bus for any live subscriber (the fast engine, a future
    # materiality engine), not a replacement for the qualitative-analysis
    # queue hook.
    _STATUS_TRANSITION_EVENT = {
        (PRE_MATCH, LIVE): EventType.MATCH_STARTED,
        (LIVE, HALFTIME): EventType.MATCH_HALFTIME,
        (HALFTIME, LIVE): EventType.MATCH_RESUMED,
    }
    if match.status == FULL_TIME and prior_status != FULL_TIME:
        _event_bus.publish(Event(
            event_type=EventType.MATCH_FINISHED, entity="match", entity_id=match_id, occurred_at=now,
            payload={"match_id": match_id, "home_score": match.home_score, "away_score": match.away_score},
            source=_SOURCE_NAME,
        ))
    else:
        # Real bug found + fixed while writing this milestone's own
        # deterministic test: a match with NO prior real sync (the first
        # time `sync_match` ever sees it - `prior_status_row` is `None`)
        # is equivalent to PRE_MATCH for transition-detection purposes
        # (this project has simply never observed it before) - the first
        # real check any tracked fixture gets is very often already LIVE
        # (a poll landing after kickoff), and that first observation IS a
        # real MATCH_STARTED, not a no-op.
        effective_prior = prior_status if prior_status is not None else PRE_MATCH
        transition_type = _STATUS_TRANSITION_EVENT.get((effective_prior, match.status))
        if transition_type is not None:
            _event_bus.publish(Event(
                event_type=transition_type, entity="match", entity_id=match_id,
                occurred_at=now, payload={"match_id": match_id, "live_minute": match.live_minute}, source=_SOURCE_NAME,
            ))

    team_name_to_fpl_id = {match.home_team_name: home_fpl_team_id, match.away_team_name: away_fpl_team_id}

    players_resolved = 0
    for ps in player_states:
        fpl_team_id = team_name_to_fpl_id.get(ps.team_name)
        player_id = match_player_in_team(conn, fpl_team_id, ps.name_raw) if fpl_team_id else None
        if player_id is not None:
            players_resolved += 1
        conn.execute(
            "INSERT INTO player_match_state "
            "(match_id, player_id, fotmob_player_id, team_id, started, minutes, position, rating, goals, "
            "assists, shots, key_passes, xg, xa, touches_box, substituted_on_minute, substituted_off_minute, "
            "penalty_shots, penalty_goals, source, retrieved_at, confidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(match_id, fotmob_player_id) DO UPDATE SET "
            "player_id=excluded.player_id, team_id=excluded.team_id, started=excluded.started, "
            # Real bug found + fixed 2026-08-29 ("live command centre" pass):
            # `rating` was in the INSERT column list but missing from this
            # UPDATE SET - a re-sync of an already-tracked match (every real
            # match, since `sync_match` is designed to be re-run repeatedly)
            # silently never updated a player's rating after the first
            # insert. Confirmed live: Haaland's real row had `rating=None`
            # even after `parse_player_states` (fixed the same session) had
            # started returning a real 8.85.
            "minutes=excluded.minutes, rating=excluded.rating, goals=excluded.goals, assists=excluded.assists, "
            "shots=excluded.shots, key_passes=excluded.key_passes, xg=excluded.xg, xa=excluded.xa, "
            "touches_box=excluded.touches_box, "
            "substituted_on_minute=excluded.substituted_on_minute, substituted_off_minute=excluded.substituted_off_minute, "
            "penalty_shots=excluded.penalty_shots, penalty_goals=excluded.penalty_goals, "
            "retrieved_at=excluded.retrieved_at",
            (match_id, player_id, ps.fotmob_player_id, fpl_team_id, int(ps.started), ps.minutes, ps.position,
             ps.rating, ps.goals, ps.assists, ps.shots, ps.key_passes, ps.xg, ps.xa, ps.touches_box,
             ps.substituted_on_minute, ps.substituted_off_minute, ps.penalty_shots, ps.penalty_goals,
             _SOURCE_NAME, now, "medium"),
        )

    for ts in team_states:
        fpl_team_id = team_name_to_fpl_id.get(ts.team_name)
        if fpl_team_id is None:
            continue
        conn.execute(
            "INSERT INTO team_match_state "
            "(match_id, team_id, formation, possession_pct, shots, shots_on_target, xg, corners, "
            "big_chances, big_chances_missed, source, retrieved_at, confidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(match_id, team_id) DO UPDATE SET "
            "formation=excluded.formation, possession_pct=excluded.possession_pct, shots=excluded.shots, "
            "shots_on_target=excluded.shots_on_target, xg=excluded.xg, corners=excluded.corners, "
            "big_chances=excluded.big_chances, big_chances_missed=excluded.big_chances_missed, "
            "retrieved_at=excluded.retrieved_at",
            (match_id, fpl_team_id, ts.formation, ts.possession_pct, ts.shots, ts.shots_on_target, ts.xg,
             ts.corners, ts.big_chances, ts.big_chances_missed, _SOURCE_NAME, now, "medium"),
        )

    # Real live match-feed incidents (goals/cards/subs/shots) - separate
    # append-only table (match_events, migration 0025), never mixed with
    # the qualitative match_observations layer. is_home resolves straight
    # to the two real FPL team ids already computed above (no team-name
    # matching needed); player resolution reuses the fotmob_player_id ->
    # player_id crosswalk this same sync just wrote into player_match_state,
    # rather than re-running name matching a second time.
    def _resolve_player(fotmob_id: str | None) -> int | None:
        if fotmob_id is None:
            return None
        row = conn.execute(
            "SELECT player_id FROM player_match_state WHERE match_id=? AND fotmob_player_id=?",
            (match_id, fotmob_id),
        ).fetchone()
        return row["player_id"] if row else None

    # Real event-type -> bus EventType map (2026-08-29, "live architecture
    # rebuild" pass) - `Half`/`AddedTime` are real administrative markers
    # (see parse_match_events's own docstring), not modeled as dispatchable
    # events this milestone - disclosed, not fabricated.
    _MATCH_EVENT_TYPE_MAP = {"Goal": EventType.GOAL, "Card": EventType.CARD, "Substitution": EventType.SUBSTITUTION, "Shot": EventType.SHOT}

    for me in parse_match_events(payload):
        event_team_id = home_fpl_team_id if me.is_home else (away_fpl_team_id if me.is_home is False else None)
        event_player_id = _resolve_player(me.fotmob_player_id)
        # Real "is this a genuinely NEW incident this tick" check (2026-08-29
        # - the event bus must only ever fire once per real incident, never
        # once per poll of an already-known one). `match_events`'s own real
        # UNIQUE(match_id, source, source_event_id) constraint is the exact
        # real identity key this project already committed to for this
        # table (migration 0025) - reused here, not a second definition.
        already_known = conn.execute(
            "SELECT 1 FROM match_events WHERE match_id=? AND source=? AND source_event_id=?",
            (match_id, _SOURCE_NAME, me.source_event_id),
        ).fetchone() is not None
        conn.execute(
            "INSERT INTO match_events "
            "(match_id, source, source_event_id, minute, event_type, team_id, player_id, description, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(match_id, source, source_event_id) DO UPDATE SET "
            "minute=excluded.minute, team_id=excluded.team_id, player_id=excluded.player_id, "
            "description=excluded.description, retrieved_at=excluded.retrieved_at",
            (match_id, _SOURCE_NAME, me.source_event_id, me.minute, me.event_type,
             event_team_id, event_player_id, me.description, now),
        )
        if already_known:
            continue
        bus_type = _MATCH_EVENT_TYPE_MAP.get(me.event_type)
        if bus_type is None:
            continue
        payload_extra = {"match_id": match_id, "minute": me.minute, "team_id": event_team_id, "description": me.description}
        if bus_type == EventType.SUBSTITUTION:
            payload_extra["player_in_id"] = _resolve_player(me.extra.get("player_in_fotmob_id"))
            payload_extra["player_out_id"] = _resolve_player(me.extra.get("player_out_fotmob_id"))
        elif bus_type == EventType.GOAL:
            assist_player_id = _resolve_player(me.extra.get("assist_player_fotmob_id"))
            if assist_player_id is not None:
                _event_bus.publish(Event(
                    event_type=EventType.ASSIST, entity="player", entity_id=assist_player_id, occurred_at=now,
                    payload={"match_id": match_id, "minute": me.minute, "team_id": event_team_id}, source=_SOURCE_NAME,
                ))
        _event_bus.publish(Event(
            event_type=bus_type, entity="player", entity_id=event_player_id, occurred_at=now,
            payload=payload_extra, source=_SOURCE_NAME,
        ))

    # Real per-minute momentum + per-shot x/y/xG storage (2026-08-29, "live
    # command centre" pass) - both confirmed live in this SAME payload
    # (migration 0035), never a second FotMob request. `INSERT OR REPLACE`
    # (not upsert-with-excluded) is fine here: both tables are pure derived
    # snapshots of the current real payload, never manually edited.
    for mp in parse_momentum(payload):
        conn.execute(
            "INSERT OR REPLACE INTO match_momentum (match_id, minute, value, source, retrieved_at) "
            "VALUES (?,?,?,?,?)",
            (match_id, mp.minute, mp.value, _SOURCE_NAME, now),
        )
    for shot in parse_shot_map(payload):
        # Real team-id resolution via the same fotmob_player_id crosswalk
        # `match_events` above already relies on (no second name-matching
        # pass) - a shot's own team is derivable from whichever side the
        # shooting player's already-resolved `player_match_state` row
        # belongs to, more reliable than FotMob's raw numeric team id
        # (never crosswalked to our own team ids elsewhere in this file).
        shot_team_id = None
        shot_player_id = None
        if shot.fotmob_player_id is not None:
            prow = conn.execute(
                "SELECT player_id, team_id FROM player_match_state WHERE match_id=? AND fotmob_player_id=?",
                (match_id, shot.fotmob_player_id),
            ).fetchone()
            if prow is not None:
                shot_player_id = prow["player_id"]
                shot_team_id = prow["team_id"]
        conn.execute(
            "INSERT OR REPLACE INTO match_shots "
            "(match_id, fotmob_shot_id, team_id, player_id, fotmob_player_id, player_name, minute, x, y, xg, "
            "is_on_target, outcome, shot_type, situation, period, source, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (match_id, shot.fotmob_shot_id, shot_team_id, shot_player_id, shot.fotmob_player_id, shot.player_name,
             shot.minute, shot.x, shot.y, shot.xg, int(shot.is_on_target) if shot.is_on_target is not None else None,
             shot.outcome, shot.shot_type, shot.situation, shot.period, _SOURCE_NAME, now),
        )

    conn.commit()
    update_source_health(conn, _SOURCE_NAME, success=True, error=None)

    result = {
        "match_id": match_id,
        "fotmob_match_id": fotmob_match_id,
        "status": match.status,
        "kickoff_utc": match.kickoff_utc,
        "home_team": match.home_team_name,
        "away_team": match.away_team_name,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "players_ingested": len(player_states),
        "players_resolved": players_resolved,
        "team_states_ingested": len(team_states),
    }

    maybe_enqueue_analysis(conn, match_id, prior_status, match.home_team_name, match.away_team_name, result)

    if tracked_squad_ids and player_states:
        from fpl_agent.ingestion.change_detection import detect_lineup_confirmations
        detect_lineup_confirmations(conn, tracked_squad_ids, match_id, now)
        conn.commit()

    return result
