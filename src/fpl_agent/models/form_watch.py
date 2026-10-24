"""THE EYE TEST, WITH THE EVIDENCE BESIDE IT.

A manager sees a player drift: fewer shots, a worse rating, the ball not
finding him. That is real, and it deserves to be on screen. Whether it should
move a projection is a question this project can answer from its own history,
so each reading here carries both: what the last three matches look like against
the rest of his season, and what players whose last three looked like that did
in the match after, measured on every stored season.

Per player (this season's Understat matches, 45+ minutes):
- involvement = (xG + xA) per 90. `ratio` = last three matches over the matches
  before them. Shots per 90 and minutes are shown beside it; FotMob's match
  ratings are shown when the match was read.
- `label`: COLD under 0.5 of his own earlier level, COOLING under 0.75, HOT over
  1.5, otherwise STEADY. These cut-offs are descriptive, not fitted.

The evidence table: for every stored (player, season) with 6+ matches, the same
ratio for a midfielder or forward and his next match's xG + xA per 90 against a
shrunk full-season baseline (empirical Bayes, 12 pseudo-90s toward the position
rate; the baseline contains the dip). 1.00 means the baseline already knew. The
extreme bin (a player at under a quarter of his earlier level) is the only one
that has realised clearly below baseline; the ordinary dips have not.
Nothing here changes a projection by itself; the moves are priced with these
numbers visible and `My view` lets a manager apply his own.
"""
import sqlite3

import numpy as np

LAST_N = 3
MIN_MINUTES = 45
BINS = ((0.0, 0.25, "under a quarter"), (0.25, 0.5, "a quarter to a half"), (0.5, 0.75, "half to three quarters"),
        (0.75, 1.0, "three quarters to level"), (1.0, 1.5, "above"), (1.5, 99.0, "well above"))
PRIOR_90S = 12.0
MIN_BIN = 40
_cache: dict = {}


def _seq(conn: sqlite3.Connection, season: str | None = None):
    pos = {r["id"]: r["element_type"] for r in conn.execute("SELECT id, element_type FROM players")}
    q = "SELECT player_id, season, minutes, xg, xa, shots FROM player_match_stats_history WHERE player_id IS NOT NULL AND minutes >= ?"
    args: list = [MIN_MINUTES]
    if season:
        q += " AND season = ?"
        args.append(season)
    q += " ORDER BY season, match_date, id"
    seqs: dict[tuple, list] = {}
    for r in conn.execute(q, args):
        seqs.setdefault((r["player_id"], r["season"]), []).append(r)
    return pos, seqs


def evidence_table(conn: sqlite3.Connection) -> dict:
    """Realised / baseline next-match xG + xA per 90 by how cold the last three matches were. Cached per history size."""
    n = conn.execute("SELECT COUNT(*) AS n FROM player_match_stats_history").fetchone()["n"]
    key = (str(conn.execute("PRAGMA database_list").fetchone()[2]), n)
    if _cache.get("key") == key:
        return _cache["table"]
    pos, seqs = _seq(conn)
    recs = []
    for (pid, _season), ms in seqs.items():
        p = pos.get(pid)
        if p not in (3, 4) or len(ms) < LAST_N + 4:
            continue
        xgi = np.array([(m["xg"] or 0) + (m["xa"] or 0) for m in ms], float)
        mins = np.array([m["minutes"] for m in ms], float)
        for i in range(LAST_N + 2, len(ms) - 1):
            before = slice(0, i - LAST_N + 1)
            last = slice(i - LAST_N + 1, i + 1)
            base_before = xgi[before].sum() / mins[before].sum() * 90
            recent = xgi[last].sum() / mins[last].sum() * 90
            recs.append((p, recent / max(base_before, 0.05), xgi[: i + 1].sum(), mins[: i + 1].sum() / 90, xgi[i + 1] * 90 / mins[i + 1], mins[i + 1]))
    if not recs:
        _cache.update(key=key, table={"bins": [], "n": 0})
        return _cache["table"]
    A = np.array(recs, float)
    P, ratio, tot, m90, ny, nm = A.T
    overall = tot.sum() / m90.sum()
    mu = {p: (tot[P == p].sum() / m90[P == p].sum() if (P == p).any() else overall) for p in (3, 4)}
    mu_vec = np.where(P == 3, mu[3], mu[4])
    base = (tot + PRIOR_90S * mu_vec) / (m90 + PRIOR_90S)
    w = nm / 90.0
    rng = np.random.default_rng(4)
    bins = []
    for lo, hi, label in BINS:
        mask = (ratio >= lo) & (ratio < hi)
        k = int(mask.sum())
        if k < MIN_BIN:
            continue
        idx_all = np.where(mask)[0]
        boots = []
        for _ in range(300):
            idx = rng.choice(idx_all, k)
            boots.append((ny[idx] * w[idx]).sum() / (base[idx] * w[idx]).sum())
        r = float((ny[mask] * w[mask]).sum() / (base[mask] * w[mask]).sum())
        bins.append({"lo": lo, "hi": hi, "label": label, "n": k, "ratio": round(r, 3),
                     "ci": [round(float(np.percentile(boots, 5)), 3), round(float(np.percentile(boots, 95)), 3)]})
    table = {"bins": bins, "n": int(len(A))}
    _cache.update(key=key, table=table)
    return table


def _bin_for(table: dict, ratio: float) -> dict | None:
    for b in table["bins"]:
        if b["lo"] <= ratio < b["hi"]:
            return b
    return None


_SPELL = {
    "under a quarter": "fell below a quarter of their earlier output",
    "a quarter to a half": "ran at a quarter to a half of their earlier output",
    "half to three quarters": "ran at half to three quarters of their earlier output",
    "three quarters to level": "ran just under their earlier output",
    "above": "ran above their earlier output",
    "well above": "ran at more than one and a half times their earlier output",
}


def evidence_sentence(b: dict | None) -> str:
    if b is None:
        return "Too few players in history had a spell like this to say what follows one."
    lo, hi = b["ci"]
    spell = _SPELL.get(b["label"], b["label"])
    if hi < 1.0:
        verdict = "so a spell like this has carried over into the next match"
    elif lo > 1.0:
        verdict = "so a spell like this has carried over upward"
    else:
        verdict = "no different from what their season already implied: the spell told us nothing"
    return (
        f"Midfielders and forwards whose last three matches {spell} produced {b['ratio']:.2f} times their baseline in the next match "
        f"(90% range {lo:.2f} to {hi:.2f}, {b['n']:,} cases), {verdict}."
    )


def label_for(ratio: float | None) -> str:
    if ratio is None:
        return "STEADY"
    return "COLD" if ratio < 0.5 else "COOLING" if ratio < 0.75 else "HOT" if ratio > 1.5 else "STEADY"


def form_watch(conn: sqlite3.Connection, player_ids: list[int], season: str | None = None) -> dict[int, dict]:
    if not player_ids:
        return {}
    season = season or (conn.execute("SELECT MAX(season) AS s FROM player_match_stats_history").fetchone()["s"])
    table = evidence_table(conn)
    pos, seqs = _seq(conn, season)
    ratings: dict[int, list] = {}
    for r in conn.execute(
        "SELECT pms.player_id, pms.rating FROM player_match_state pms JOIN match_intelligence mi ON mi.id = pms.match_id "
        "WHERE pms.player_id IN (%s) AND pms.rating IS NOT NULL ORDER BY mi.kickoff_utc" % ",".join("?" * len(player_ids)), tuple(player_ids),
    ):
        ratings.setdefault(r["player_id"], []).append(round(r["rating"], 1))
    out: dict[int, dict] = {}
    for pid in player_ids:
        ms = seqs.get((pid, season), [])
        if len(ms) < LAST_N + 2:
            continue
        xgi = np.array([(m["xg"] or 0) + (m["xa"] or 0) for m in ms], float)
        mins = np.array([m["minutes"] for m in ms], float)
        shots = np.array([m["shots"] or 0 for m in ms], float)
        before, last = slice(0, len(ms) - LAST_N), slice(len(ms) - LAST_N, len(ms))
        base_before = float(xgi[before].sum() / mins[before].sum() * 90)
        recent = float(xgi[last].sum() / mins[last].sum() * 90)
        ratio = recent / max(base_before, 0.05)
        attacker = pos.get(pid) in (3, 4)
        b = _bin_for(table, ratio) if attacker else None
        out[pid] = {
            "matches": len(ms), "recent_xgi90": round(recent, 2), "before_xgi90": round(base_before, 2), "ratio": round(ratio, 2),
            "recent_shots90": round(float(shots[last].sum() / mins[last].sum() * 90), 1), "before_shots90": round(float(shots[before].sum() / mins[before].sum() * 90), 1),
            "per_match_xgi": [round(float(x), 2) for x in xgi[-5:]], "ratings": ratings.get(pid, [])[-5:],
            "label": label_for(ratio) if attacker else "STEADY",
            "evidence": ({"bin": b["label"], "ratio": b["ratio"], "ci": b["ci"], "n": b["n"], "sentence": evidence_sentence(b)} if b else None),
        }
    return out
