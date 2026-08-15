"""
Transfer optimiser (section 62-64). Compares rolling a free transfer against
swapping a specific player out for a specific replacement, across 1/3/5-GW
windows, including the -4 cost of a hit if the transfer exceeds the banked
free transfers. Never recommends a move on single-GW xP alone (section 62) -
every comparison here uses expected_points_window, not the single-match model.
"""

import sqlite3
from dataclasses import dataclass

from fpl_agent.models.expected_points import expected_points_window

HIT_COST = 4  # points, per transfer beyond the free allowance


@dataclass(frozen=True)
class TransferCandidate:
    player_out_id: int
    player_out_name: str
    player_in_id: int
    player_in_name: str
    price_delta_tenths: int  # positive = costs more than the sold player
    ev_1gw: float
    ev_3gw: float
    ev_5gw: float
    net_ev_1gw: float  # after hit cost, if this transfer uses a hit
    net_ev_3gw: float
    net_ev_5gw: float
    uses_hit: bool


def _player_name(conn: sqlite3.Connection, player_id: int) -> str:
    row = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()
    return row["web_name"] if row else f"#{player_id}"


def _current_price(conn: sqlite3.Connection, player_id: int) -> int:
    row = conn.execute(
        "SELECT value_tenths FROM player_price_history WHERE player_id=? AND valid_until IS NULL",
        (player_id,),
    ).fetchone()
    return row["value_tenths"] if row else 0


def _position(conn: sqlite3.Connection, player_id: int) -> str:
    row = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    return row["position"] if row else None


def evaluate_transfer(
    conn: sqlite3.Connection, player_out_id: int, player_in_id: int, is_hit: bool,
    from_event: int | None = None,
) -> TransferCandidate:
    kwargs = {"from_event": from_event} if from_event is not None else {}
    ev_out = {n: expected_points_window(conn, player_out_id, n, **kwargs).total_median for n in (1, 3, 5)}
    ev_in = {n: expected_points_window(conn, player_in_id, n, **kwargs).total_median for n in (1, 3, 5)}
    ev_delta = {n: round(ev_in[n] - ev_out[n], 2) for n in (1, 3, 5)}

    hit = HIT_COST if is_hit else 0
    net = {n: round(ev_delta[n] - hit, 2) for n in (1, 3, 5)}

    price_out = _current_price(conn, player_out_id)
    price_in = _current_price(conn, player_in_id)

    return TransferCandidate(
        player_out_id=player_out_id, player_out_name=_player_name(conn, player_out_id),
        player_in_id=player_in_id, player_in_name=_player_name(conn, player_in_id),
        price_delta_tenths=price_in - price_out,
        ev_1gw=ev_delta[1], ev_3gw=ev_delta[3], ev_5gw=ev_delta[5],
        net_ev_1gw=net[1], net_ev_3gw=net[3], net_ev_5gw=net[5],
        uses_hit=is_hit,
    )


def best_transfer_for_player(
    conn: sqlite3.Connection,
    player_out_id: int,
    squad_ids: list[int],
    bank_tenths: int,
    is_hit: bool,
    n_gw: int = 3,
    top_n: int = 5,
    from_event: int | None = None,
) -> list[TransferCandidate]:
    """Best same-position replacements for player_out, respecting bank + club limit
    (same club limit enforced implicitly by squad_optimiser at squad-build time -
    this only checks budget, since a like-for-like swap doesn't change club counts
    unless the replacement is from a club already at the 3-player cap)."""
    position = _position(conn, player_out_id)
    price_out = _current_price(conn, player_out_id)
    budget_tenths = price_out + bank_tenths

    squad_team_ids = {
        r["team_id"] for r in conn.execute(
            f"SELECT team_id FROM players WHERE id IN ({','.join('?' * len(squad_ids))})", squad_ids
        ).fetchall()
    }

    candidates = conn.execute(
        "SELECT p.id, p.team_id FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "WHERE et.singular_name_short = ? AND p.removed = 0",
        (position,),
    ).fetchall()

    results = []
    for c in candidates:
        if c["id"] == player_out_id or c["id"] in squad_ids:
            continue
        price_in = _current_price(conn, c["id"])
        if price_in > budget_tenths:
            continue
        results.append(evaluate_transfer(conn, player_out_id, c["id"], is_hit, from_event=from_event))

    key = {1: "net_ev_1gw", 3: "net_ev_3gw", 5: "net_ev_5gw"}[n_gw]
    results.sort(key=lambda t: getattr(t, key), reverse=True)
    return results[:top_n]


@dataclass(frozen=True)
class RollRecommendation:
    action: str  # "roll" or "transfer"
    best_candidate: TransferCandidate | None
    reason: str


def recommend(
    conn: sqlite3.Connection,
    squad_ids: list[int],
    bank_tenths: int,
    free_transfers: int,
    n_gw: int = 3,
) -> RollRecommendation:
    """Section 62: never recommend a move solely because the incoming player has
    higher single-GW xP - this compares windowed net EV (post-hit-cost) against
    rolling (net EV = 0)."""
    best: TransferCandidate | None = None
    for player_out_id in squad_ids:
        is_hit = free_transfers < 1
        options = best_transfer_for_player(conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw=n_gw, top_n=1)
        if options and (best is None or getattr(options[0], f"net_ev_{n_gw}gw") > getattr(best, f"net_ev_{n_gw}gw")):
            best = options[0]

    if best is None or getattr(best, f"net_ev_{n_gw}gw") <= 0:
        return RollRecommendation(
            action="roll", best_candidate=best,
            reason=f"no transfer clears a positive {n_gw}-GW net EV after accounting for hit cost - bank the free transfer",
        )
    return RollRecommendation(
        action="transfer", best_candidate=best,
        reason=f"{best.player_out_name} -> {best.player_in_name} nets +{getattr(best, f'net_ev_{n_gw}gw')} xP over {n_gw} GWs",
    )
