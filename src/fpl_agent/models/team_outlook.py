"""Real, per-team qualitative synthesis - "be an automatic football pundit"
(user, 2026-08-21). Fuses three signals this project already has, none of
them new ingestion: squad_churn.py's real minutes-weighted departure ratio
(the actual "sold their key players" fact), Tier 2-4 news matched to the team
(news_item_teams), and the predicted-lineup source's own "Latest News" text
(ingestion/predicted_lineups_source.py). Nothing here is generated/guessed -
every field traces to a row already in the DB. `churn_ratio=None` means
insufficient history to say honestly (same contract team_churn_ratio already
has - a promoted team or one with sparse history, not "stable")."""
from dataclasses import dataclass

from fpl_agent.ingestion.market_identity import get_or_create_market_team, normalize_common_team_name
from fpl_agent.models.manager_change import detect_manager_change_signals
from fpl_agent.models.manager_intelligence import ManagerIntelligence, manager_intelligence
from fpl_agent.models.squad_churn import team_churn_ratio
from fpl_agent.models.team_intelligence import TeamQualitativeIntelligence, team_qualitative_intelligence

# Thresholds are a disclosed heuristic (not fit to real outcome data - no
# season has been played yet to fit against), same honesty posture as every
# other uncalibrated threshold in this project (differentials.py's ownership
# bands, traps.py's minutes threshold).
_HIGH_CHURN = 0.15
_MODERATE_CHURN = 0.07


@dataclass(frozen=True)
class TeamOutlook:
    team_id: int
    team_name: str
    churn_ratio: float | None
    churn_label: str
    recent_news: list[dict]
    lineup_news: str | None
    formation: str | None
    manager_change: str | None
    qualitative: TeamQualitativeIntelligence | None  # post-match tactical read + trend, None until Slice A2 has analyzed a real match for this team
    tactics: ManagerIntelligence | None  # real formation/rotation/sub-timing pattern from match history, None until >=2 real matches observed


def _churn_label(ratio: float | None) -> str:
    if ratio is None:
        return "unknown (insufficient squad history to say honestly)"
    if ratio >= _HIGH_CHURN:
        return f"significant turnover ({ratio:.0%} of last season's key minutes gone)"
    if ratio >= _MODERATE_CHURN:
        return f"moderate turnover ({ratio:.0%} of last season's key minutes gone)"
    return f"squad largely retained ({ratio:.0%} turnover)"


def team_outlook(conn, team_id: int, news_limit: int = 5) -> TeamOutlook:
    team_row = conn.execute("SELECT name, short_name FROM teams WHERE id=?", (team_id,)).fetchone()
    if team_row is None:
        raise ValueError(f"unknown team_id: {team_id}")

    market_id = get_or_create_market_team(conn, "fpl", normalize_common_team_name(team_row["name"]))
    ratio = team_churn_ratio(conn, market_id)

    news_rows = conn.execute(
        "SELECT n.title, n.link, n.published_at, n.source_tier FROM news_items n "
        "JOIN news_item_teams nit ON nit.news_item_id = n.id "
        "WHERE nit.team_id = ? ORDER BY n.published_at DESC LIMIT ?",
        (team_id, news_limit),
    ).fetchall()

    lineup_row = conn.execute(
        "SELECT formation, latest_news FROM predicted_lineup_teams WHERE team_id=?", (team_id,)
    ).fetchone()

    # Corroborated (2+ independent sources) manager-change signal for this team.
    manager_signal = next(
        (s for s in detect_manager_change_signals(conn) if s.team_id == team_id), None
    )
    manager_change_text = None
    if manager_signal is not None:
        manager_change_text = (
            f"possible managerial change ({', '.join(manager_signal.sources)} both reporting): "
            f"{manager_signal.matched_titles[0]}"
        )

    qual = team_qualitative_intelligence(conn, team_id)
    qualitative = qual if (qual.current_tactical_signal is not None or qual.trends) else None

    return TeamOutlook(
        team_id=team_id, team_name=team_row["name"], churn_ratio=ratio,
        churn_label=_churn_label(ratio),
        recent_news=[dict(r) for r in news_rows],
        lineup_news=lineup_row["latest_news"] if lineup_row else None,
        formation=lineup_row["formation"] if lineup_row else None,
        manager_change=manager_change_text,
        qualitative=qualitative,
        tactics=manager_intelligence(conn, team_id),
    )


def squad_team_outlooks(conn, player_ids: list[int]) -> list[TeamOutlook]:
    """One TeamOutlook per distinct team represented in a squad - the actual
    "before every gameweek, check every team my squad touches" workflow,
    ordered by churn_ratio descending (unknown/None last) so the most
    real-world-volatile teams surface first."""
    if not player_ids:
        return []
    placeholders = ",".join("?" * len(player_ids))
    team_ids = {
        r["team_id"] for r in conn.execute(
            f"SELECT DISTINCT team_id FROM players WHERE id IN ({placeholders})", player_ids
        ).fetchall()
    }
    outlooks = [team_outlook(conn, tid) for tid in team_ids]
    outlooks.sort(key=lambda o: (o.churn_ratio is None, -(o.churn_ratio or 0)))
    return outlooks
