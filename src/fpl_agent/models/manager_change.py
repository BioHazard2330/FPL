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
)


@dataclass(frozen=True)
class ManagerChangeSignal:
    team_id: int
    team_name: str
    sources: tuple[str, ...]
    matched_titles: tuple[str, ...]
    earliest_published_at: str | None


def _matches_keyword(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in MANAGER_CHANGE_KEYWORDS)


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
        text = r["title"] + " " + (r["summary"] or "")
        if not _matches_keyword(text):
            continue
        bucket = by_team.setdefault(
            r["team_id"], {"team_name": r["team_name"], "sources": set(), "titles": [], "dates": []}
        )
        bucket["sources"].add(r["source"])
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
