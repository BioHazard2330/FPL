"""Real qualitative rotation-risk signal (2026-08-21), built after the user
pushed back directly on the model's own GW1 squad ("Osula? Gyokeres? Foden?
These guys might not even start... there has to be a massive qualitative
opinion as well") - checked by hand against the real synced data before
writing any code, per this project's own standing discipline.

Confirmed real, not imagined: `predicted_lineup_players.predicted_status`
(`ingestion/predicted_lineups_source.py`) is a binary starting/bench/doubt
classification, and `models/expected_minutes.py` trusts "starting" as
near-certain (raises the estimate to a real per-start rate or a flat 75min
floor). But the SAME scrape's own free-text `latest_news` paragraph for these
exact players, read by hand, plainly hedges:
  - Newcastle (Osula): "It'll be two from three of Will Osula, Yoane Wissa
    and Nick Woltemade up top" - real 3-way rotation for what sounds like
    fewer starting spots than candidates.
  - Man Utd (Dorgu): "Matheus Cunha... may miss out, unless he displaces
    Patrick Dorgu on the left" - a real, named threat to his starting spot.
  - Arsenal (Gyokeres): "he was only a substitute against Man City... it
    wouldn't be a surprise to see him here" - genuinely uncertain, not the
    confident "starting" the structured flag implies.

This module is the fix: a genuine, disclosed, keyword-proximity heuristic
over text this project ALREADY scrapes (no new ingestion) - never a claimed
NLP classification, always returns the real matched sentence as evidence
rather than asserting a fabricated confidence number. Sentence-scoped (not
paragraph-wide) specifically to keep false-positive risk bounded: a hedge
keyword has to appear in the SAME sentence as the player's own name, not
just somewhere in the same news blob.
"""
import re
import sqlite3
from dataclasses import dataclass

from fpl_agent.ingestion.predicted_lineups_source import _fold

_MIN_NAME_LENGTH = 3

# Real hedge/rotation phrases found by hand in this project's own scraped
# team news (see module docstring) plus common equivalents - a disclosed,
# uncalibrated keyword list, not a trained classifier. Deliberately excludes
# generic injury words ("injury", "knock") already covered by
# `models/availability.py`'s own status-based classification - this module
# is specifically about ROLE/rotation uncertainty for an otherwise-fit player.
_ROTATION_KEYWORDS = (
    "unless", "displace", "two from three", "one of three", "two of three",
    "any one of", "either of", "battle for", "compete for",
    "vying for", "vying to", "rotation", "rotate", "may miss out",
    "could miss out", "only a substitute", "named on the bench",
    "forgotten man", "big doubt", "doubt for", "off the pace", "wonder if",
    "possibility to deputise", "alternative to", "alternatives to",
    "may have to", "could be dropped", "options to", "less likely",
    "question mark", "toss-up", "unclear whether", "not certain",
    "stay of execution", "leapfrog", "push forward to",
)


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _name_variants(web_name: str | None, second_name: str | None) -> list[str]:
    """web_name only, deliberately - NOT the same fallback chain
    `predicted_lineups_source.py::match_player_in_team` uses. That function's
    second_name-last-word fallback exists for cross-source name resolution
    (matching a scraper's own prose against our DB) and accepts some
    collision risk in exchange for recall. This module's job is the
    opposite trade: it fabricates a real risk claim about a real squad
    member if it's wrong, so it optimizes for precision instead. Real
    collision caught live 2026-08-21: Raya's `second_name` is "Raya Martín" -
    the last-word fallback would match "Martin" as a substring of an
    unrelated "Martin Zubimendi" mention in the same Arsenal news sentence,
    fabricating a rotation-risk flag on the wrong player entirely. Every
    real case this module was built to catch (Osula/Gyokeres/Dorgu) matched
    cleanly on web_name alone - the second_name fallback added collision
    risk with no corresponding real recall gain, so it's dropped here."""
    if web_name and len(web_name) >= _MIN_NAME_LENGTH:
        return [web_name]
    return []


@dataclass(frozen=True)
class RotationRiskFlag:
    player_id: int
    web_name: str
    snippet: str


def rotation_risk_snippet(conn: sqlite3.Connection, player_id: int) -> str | None:
    """Real matched sentence from this player's own team's scraped news text
    if a rotation/role-uncertainty hedge phrase appears alongside their name
    - `None` if no predicted-lineup news exists yet, or nothing matched.
    Returns the actual quoted evidence, never a synthesized claim."""
    row = conn.execute(
        "SELECT p.web_name, p.second_name, plt.latest_news FROM players p "
        "JOIN predicted_lineup_teams plt ON plt.team_id = p.team_id WHERE p.id=?",
        (player_id,),
    ).fetchone()
    if row is None or not row["latest_news"]:
        return None
    names_folded = {_fold(n) for n in _name_variants(row["web_name"], row["second_name"])}
    if not names_folded:
        return None
    for sentence in _split_sentences(row["latest_news"]):
        folded = _fold(sentence)
        if any(name in folded for name in names_folded) and any(kw in folded for kw in _ROTATION_KEYWORDS):
            return sentence.strip()
    return None


def flag_squad_rotation_risk(conn: sqlite3.Connection, squad_ids: list[int]) -> list[RotationRiskFlag]:
    flags = []
    for pid in squad_ids:
        snippet = rotation_risk_snippet(conn, pid)
        if snippet is None:
            continue
        row = conn.execute("SELECT web_name FROM players WHERE id=?", (pid,)).fetchone()
        flags.append(RotationRiskFlag(player_id=pid, web_name=row["web_name"] if row else "?", snippet=snippet))
    return flags
