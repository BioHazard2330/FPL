"""POINTS CHANGES panel (fpl.page parity) - real post-match Bonus/DefCon
revisions, `models.points_changes.detect_points_revisions`. Squad players
are visually flagged (real decision relevance: a revision on your own
player changes their actual total points), everyone else shown for
league-wide context, matching fpl.page's own scope (not squad-only)."""
from fpl_agent.models.points_changes import detect_points_revisions, is_gw_locked
from fpl_agent.monitoring.dashboard.legacy import _esc, _official_badge_url


def _team_code_for(conn, team_short: str) -> int | None:
    row = conn.execute("SELECT code FROM teams WHERE short_name = ?", (team_short,)).fetchone()
    return row["code"] if row else None


def _revision_row_html(conn, r, squad_ids: set[int], team_code_cache: dict[str, int | None]) -> str:
    if r.team_short not in team_code_cache:
        team_code_cache[r.team_short] = _team_code_for(conn, r.team_short)
    code = team_code_cache[r.team_short]
    badge = f"<img class='injury-badge' src='{_esc(_official_badge_url(code))}' loading='lazy' alt=''>" if code else ""
    squad_cls = " price-row-squad" if r.player_id in squad_ids else ""
    delta_points = r.new_points - r.old_points
    delta_cls = "price-predict-ok" if delta_points > 0 else "price-predict-bad" if delta_points < 0 else "price-predict-warn"
    delta_text = f"{delta_points:+d} pts" if delta_points != 0 else "no points impact"
    return f"""<div class="price-predict-row{squad_cls}">
  <span class="price-predict-name">{badge}<strong>{_esc(r.web_name)}</strong> <span class='fx-teams'>{_esc(r.team_short)} &bull; {_esc(r.position)}</span></span>
  <span class="price-predict-price">{r.old_value} &rarr; {r.new_value}</span>
  <span class="{delta_cls}">{delta_text}</span>
</div>"""


def render_points_changes_html(conn, squad_ids: set[int] | None = None) -> str:
    squad_ids = squad_ids or set()
    row = conn.execute("SELECT id, name FROM events WHERE finished = 1 ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return "<div class='empty-state'>No finished gameweek yet - revisions can only be judged once a gameweek completes.</div>"

    revisions = detect_points_revisions(conn, event=row["id"])
    bonus_revisions = [r for r in revisions if r.category == "bonus"]
    defcon_revisions = [r for r in revisions if r.category == "defcon"]
    team_code_cache: dict[str, int | None] = {}

    bonus_html = (
        "\n".join(_revision_row_html(conn, r, squad_ids, team_code_cache) for r in bonus_revisions)
        if bonus_revisions else "<div class='empty-state'>No bonus revisions observed.</div>"
    )
    defcon_html = (
        "\n".join(_revision_row_html(conn, r, squad_ids, team_code_cache) for r in defcon_revisions)
        if defcon_revisions else "<div class='empty-state'>No defensive contribution revisions observed.</div>"
    )

    # Real LIVE/EXPIRED status (fpl.page-parity pass, their own real
    # published lock rule - see `models.points_changes.is_gw_locked`'s
    # docstring). Every revision shown above is, by construction, already
    # reflected in this project's own synced data - fpl.page's real
    # third "Pending" state (Opta has recorded a correction but FPL hasn't
    # processed the points yet) needs Opta's own raw pre-FPL-processing
    # feed, which this project has no access to - not fabricated here, see
    # docs/history for the full disclosed account.
    locked = is_gw_locked(conn, row["id"])
    if locked is True:
        lock_html = "<span class='points-change-lock points-change-lock-expired'>&#10060; EXPIRED &mdash; gameweek locked, no further corrections possible</span>"
    elif locked is False:
        lock_html = "<span class='points-change-lock points-change-lock-live'>&#9989; LIVE &mdash; corrections still possible until 1h after the final match</span>"
    else:
        lock_html = ""

    return f"""<div class="panel-subtitle" style="margin-bottom:8px">Gameweek {row['id']} revision ledger - real snapshot diff, post-full-time only, never in-play bonus churn</div>
{lock_html}
<div class="market-section"><h3>Bonus Points</h3>{bonus_html}</div>
<div class="market-section"><h3>Defensive Contributions</h3>{defcon_html}</div>"""
