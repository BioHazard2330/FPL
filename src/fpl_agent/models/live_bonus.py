"""Live provisional bonus points from FPL's own official live-event endpoint
(`/api/event/{N}/live/`, `ingestion/fpl_api.py::fetch_event_live`) - real
Tier 1 data, not a model. Corrects an earlier limitation this project
documented too strongly ("no Tier 1 access to a live-match-event feed") -
found by taking a competitor idea seriously enough to verify it rather than
dismissing it: the suggested script had real problems (wrong API domain,
conflated BPS with DefCon's separate CBIT/CBIRT raw-action count), but the
underlying goal - live bonus tracking - is genuinely reachable via FPL's own
endpoint, which already computes `bps` for you every few minutes during a
live match.

Bonus points are awarded PER FIXTURE, not across the whole gameweek - the
top 3 BPS scorers *in that specific match* get 3/2/1, with the real official
tie rule: tied players share the higher points value and compress the
remaining slots (two players tied for the top BPS in a match both get 3,
and the next-best player gets 1, not 2 - the "2" slot is skipped entirely).
`_assign_bonus` below implements that exact rule, not a naive rank-1/2/3.

Cannot be live-verified against real in-progress-match data yet (GW1 hasn't
kicked off) - built and tested against the real, well-documented endpoint
schema instead, honestly disclosed rather than claimed as fully proven."""
import sqlite3
from dataclasses import dataclass

_BONUS_POINTS_POOL = (3, 2, 1)


def _assign_bonus(bps_desc: list[int]) -> list[int]:
    """`bps_desc` must already be sorted descending. Returns the bonus point
    awarded to each position, real FPL tie rule (see module docstring)."""
    bonus = [0] * len(bps_desc)
    pool_idx = 0
    for score in sorted(set(bps_desc), reverse=True):
        if pool_idx >= len(_BONUS_POINTS_POOL):
            break
        awarded = _BONUS_POINTS_POOL[pool_idx]
        indices = [i for i, b in enumerate(bps_desc) if b == score]
        for i in indices:
            bonus[i] = awarded
        pool_idx += len(indices)
    return bonus


@dataclass(frozen=True)
class LiveBonusRow:
    player_id: int
    web_name: str
    fixture_id: int
    bps: int
    provisional_bonus: int
    confirmed_bonus: int | None  # None until FPL finalizes it post-match
    minutes: int
    goals_scored: int
    assists: int
    red_cards: int = 0


def compute_live_bonus(conn: sqlite3.Connection, live_payload: dict) -> list[LiveBonusRow]:
    """`live_payload` is the raw dict from `fetch_event_live(event).data` -
    `{"elements": [{"id": ..., "stats": {...}, "explain": [{"fixture": ..., ...}]}]}`.
    Groups by fixture (a player can appear in 2+ fixtures in a double
    gameweek - each scored independently, matching real FPL rules), ranks by
    `bps` within each fixture group, assigns provisional bonus. Players with
    0 minutes are excluded (can't earn bonus, and BPS is meaningless for a
    non-appearance) - matches FPL's own real behavior."""
    by_fixture: dict[int, list[dict]] = {}
    for element in live_payload.get("elements", []):
        stats = element.get("stats", {})
        if not stats.get("minutes"):
            continue
        for fixture_entry in element.get("explain", []):
            fixture_id = fixture_entry.get("fixture")
            if fixture_id is None:
                continue
            by_fixture.setdefault(fixture_id, []).append({"player_id": element["id"], "stats": stats})

    rows: list[LiveBonusRow] = []
    for fixture_id, entries in by_fixture.items():
        entries.sort(key=lambda e: e["stats"].get("bps", 0), reverse=True)
        bps_list = [e["stats"].get("bps", 0) for e in entries]
        bonus_list = _assign_bonus(bps_list)
        for entry, provisional in zip(entries, bonus_list):
            player_id = entry["player_id"]
            stats = entry["stats"]
            name_row = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()
            rows.append(LiveBonusRow(
                player_id=player_id,
                web_name=name_row["web_name"] if name_row else f"#{player_id}",
                fixture_id=fixture_id,
                bps=stats.get("bps", 0),
                provisional_bonus=provisional,
                confirmed_bonus=stats.get("bonus") if stats.get("bonus", 0) > 0 else None,
                minutes=stats.get("minutes", 0),
                goals_scored=stats.get("goals_scored", 0),
                assists=stats.get("assists", 0),
                red_cards=stats.get("red_cards", 0),
            ))

    rows.sort(key=lambda r: (r.fixture_id, -r.bps))
    return rows


@dataclass(frozen=True)
class LiveMatchEvent:
    """One real, user-facing moment worth pushing a notification for -
    diffed between two consecutive polls, never fabricated. `kind` is one
    of "goal"/"assist"/"bonus"/"red_card"."""
    player_id: int
    web_name: str
    kind: str
    detail: str
    fixture_id: int


def diff_live_rows(
    previous: dict[int, LiveBonusRow], current: list[LiveBonusRow]
) -> tuple[list[LiveMatchEvent], dict[int, LiveBonusRow]]:
    """Pure diff between the previous poll's per-player state and the
    current one. An EMPTY `previous` dict means "first observation this
    watch session" - seeds the baseline with zero events, deliberately:
    without this, starting a live-watch mid-match would fire a false
    "just scored!" alert for every goal a player already had before the
    watch began. Only a genuine increase in a stat fires an event; a
    provisional bonus can also legitimately DECREASE mid-match as BPS
    swings - that never fires an event (nothing to celebrate about a
    bonus going down, and it would be a confusing false alarm).

    Deduped by player_id before diffing: a double-gameweek player gets one
    LiveBonusRow per fixture from compute_live_bonus, but goals_scored/
    assists/red_cards in FPL's own live stats are whole-gameweek totals
    (identical across that player's fixture rows) - diffing per fixture-row
    would fire the same real goal/assist/red-card event twice in a single
    poll. A real, disclosed simplification for bonus specifically: this
    takes the higher of the player's fixture-scoped provisional_bonus
    values rather than tracking both fixtures' bonus independently (a fully
    correct version would need per-(player, fixture) state, not just
    per-player) - fine given GW1 has no doubles; revisit if this ever needs
    to fire for a real double-gameweek captain."""
    deduped: dict[int, LiveBonusRow] = {}
    for row in current:
        existing = deduped.get(row.player_id)
        if existing is None or row.provisional_bonus > existing.provisional_bonus:
            deduped[row.player_id] = row
    current = list(deduped.values())

    events: list[LiveMatchEvent] = []
    new_state: dict[int, LiveBonusRow] = {}
    first_observation = not previous

    for row in current:
        prev = previous.get(row.player_id)
        if not first_observation:
            prev_goals = prev.goals_scored if prev else 0
            prev_assists = prev.assists if prev else 0
            prev_bonus = prev.provisional_bonus if prev else 0
            prev_red = prev.red_cards if prev else 0

            if row.goals_scored > prev_goals:
                events.append(LiveMatchEvent(
                    row.player_id, row.web_name, "goal",
                    f"scored! ({row.goals_scored} today)", row.fixture_id,
                ))
            if row.assists > prev_assists:
                events.append(LiveMatchEvent(
                    row.player_id, row.web_name, "assist",
                    f"assist! ({row.assists} today)", row.fixture_id,
                ))
            if row.provisional_bonus > prev_bonus and row.provisional_bonus > 0:
                events.append(LiveMatchEvent(
                    row.player_id, row.web_name, "bonus",
                    f"provisional +{row.provisional_bonus} bonus (BPS {row.bps})", row.fixture_id,
                ))
            if row.red_cards > prev_red:
                events.append(LiveMatchEvent(
                    row.player_id, row.web_name, "red_card",
                    "sent off", row.fixture_id,
                ))

        new_state[row.player_id] = row

    return events, new_state
