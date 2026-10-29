"""Manager-change signal detector (section 44, deferred through Pillar 2
Plan 2a pending a second journalism source per CLAUDE.md's Tier 2-4
precedence policy: "one journalism source alone isn't enough to build a
corroboration detector around"). Now buildable: news_source.py ingests two
independent strong-reporter sources (BBC Sport + Sky Sports, both confirmed
live 2026-08-20).

FACTS boundary, same restraint as team-news-monitor: this is a heuristic
INDEX over already-ingested article text, surfaced for a human/Claude to
read and judge - it never writes to `teams`, `players.status`, or
`change_events`, and never asserts a manager change actually happened. A
keyword match on "sacked"/"appointed"/etc is a real, common way journalism
reports a managerial change, but keyword matching is not confirmation - two
INDEPENDENT sources both matching the same team within the lookback window
is the corroboration bar this project's own precedence policy requires
before treating a signal as worth surfacing at all (a single source's
report, however matched, is not returned)."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Deliberately conservative and explicit - a documented heuristic word list,
# not an NLP model. Chosen to catch how real journalism actually phrases a
# managerial change/appointment while staying narrow enough not to fire on
# routine match-result or transfer-rumour language.
MANAGER_CHANGE_KEYWORDS = (
    "sacked", "sacks", "sacking",
    "appointed as manager", "appointed as head coach", "appoints new manager",
    "appoints new head coach", "named as manager", "named as head coach",
    "new head coach", "new manager",
    "steps down as manager", "steps down as head coach",
    "resigns as manager", "resigns as head coach", "resignation as manager",
    "interim manager", "interim head coach", "interim boss",
    "parts company with manager", "parted company with manager",
    "sacked as manager", "sacked as head coach",
    "sack", "appoint", "appoints", "appointed", "new boss", "takes charge", "part ways", "parts ways", "parted ways",
)


@dataclass(frozen=True)
class ManagerChangeSignal:
    team_id: int
    team_name: str
    sources: tuple[str, ...]
    matched_titles: tuple[str, ...]
    earliest_published_at: str | None


# The club must be named in the headline before the phrase ("Aston Villa sack boss", not "Kuyt named Fenerbahce interim
# boss before Liverpool tie").
# Speculation about a change that has not happened ("X high on list if Y sacked", "could be sacked", "linked with the
# job") uses the same verbs; an article carrying any of these is not counted.
SPECULATION_MARKERS = (
    " if ", "could be", "could replace", "would be", "might", " list", "shortlist", "linked", "favourite", "frontrunner",
    "front-runner", "candidate", "considering", "under pressure", "odds", "in talks", "set to", "eyeing", "target",
    "rumour", "?", "wsl", "women",
)


def _keyword_at(text: str) -> int | None:
    """Position of the first manager-change phrase as whole words, or None."""
    import re

    low = text.lower()
    hits = [m.start() for kw in MANAGER_CHANGE_KEYWORDS for m in [re.search(r"\b" + re.escape(kw.strip()) + r"\b", low)] if m]
    return min(hits) if hits else None


def _matches_keyword(text: str) -> bool:
    text_lower = f" {text.lower()} "
    return _keyword_at(text) is not None and not any(m in text_lower for m in SPECULATION_MARKERS)


def _names_team(title: str, team_name: str) -> bool:
    """The headline itself names the club: an article tagged to a club for a passing mention (a former player taking a
    job elsewhere) is not about its manager."""
    from fpl_agent.ingestion.watcher_ratings import TEAM_ALIASES, _norm

    at = _keyword_at(title)
    if at is None:
        return False
    padded = f" {_norm(title[:at])} "
    return any(f" {_norm(n)} " in padded for n in [team_name, *TEAM_ALIASES.get(team_name, [])])


def _outlet(source: str) -> str:
    """Feeds of one outlet (BBC's football-all and Premier League feeds) are one source, not two."""
    return source.split("_", 1)[0]


def detect_manager_change_signals(conn: sqlite3.Connection, days_lookback: int = 7) -> list[ManagerChangeSignal]:
    """Only returns a signal for a team when at least 2 DISTINCT sources each
    have at least one keyword-matched article about that team within the
    lookback window - the real corroboration bar, not just "a keyword
    matched somewhere"."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_lookback)).isoformat()
    rows = conn.execute(
        "SELECT n.id, n.source, n.title, n.summary, n.published_at, nit.team_id, t.name AS team_name "
        "FROM news_items n "
        "JOIN news_item_teams nit ON nit.news_item_id = n.id "
        "JOIN teams t ON t.id = nit.team_id "
        "WHERE n.published_at IS NULL OR n.published_at >= ?",
        (cutoff,),
    ).fetchall()

    by_team: dict[int, dict] = {}
    for r in rows:
        if not _matches_keyword(r["title"]) or not _names_team(r["title"], r["team_name"]):
            continue
        bucket = by_team.setdefault(
            r["team_id"], {"team_name": r["team_name"], "sources": set(), "titles": [], "dates": []}
        )
        bucket["sources"].add(_outlet(r["source"]))
        bucket["titles"].append(r["title"])
        if r["published_at"]:
            bucket["dates"].append(r["published_at"])

    signals = []
    for team_id, bucket in by_team.items():
        if len(bucket["sources"]) < 2:
            continue  # not corroborated by a second independent source
        signals.append(
            ManagerChangeSignal(
                team_id=team_id, team_name=bucket["team_name"],
                sources=tuple(sorted(bucket["sources"])),
                matched_titles=tuple(bucket["titles"]),
                earliest_published_at=min(bucket["dates"]) if bucket["dates"] else None,
            )
        )
    signals.sort(key=lambda s: s.team_name)
    return signals
