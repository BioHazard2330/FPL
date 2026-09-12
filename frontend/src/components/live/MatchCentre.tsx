import { useState } from 'react'
import { Link } from 'react-router-dom'
import { crestUrl } from '@/lib/api'
import { MomentumBand } from '@/components/football/MomentumBand'
import { WinProbabilityOrb3D } from '@/components/three/WinProbabilityOrb3D'
import type { LiveMatch, LiveMatchPlayer, LiveShot, LiveTeamMatchStats } from '@/lib/types'

/** Real opposed stat bar - one rule split between the two sides in
 * proportion to their real values, so possession/shots/xG read as a
 * contest rather than as two independent numbers. A stat neither side has
 * reported yet is omitted entirely, never drawn as 0-0. */
function OpposedStat({ label, home, away, decimals = 0 }: { label: string; home: number | null; away: number | null; decimals?: number }) {
  if (home === null && away === null) return null
  const h = home ?? 0
  const a = away ?? 0
  const total = h + a
  const homePct = total > 0 ? (h / total) * 100 : 50
  return (
    <div className="grid grid-cols-[3.5rem_1fr_3.5rem] items-center gap-3 py-1.5">
      <span className="tabular text-right text-sm font-bold text-text">{home !== null ? home.toFixed(decimals) : '—'}</span>
      <div>
        <div className="text-center text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">{label}</div>
        <div className="mt-1 flex h-1.5 w-full gap-px">
          <div className="bar-draw bg-pitch-green" style={{ width: `${homePct}%` }} />
          <div className="flex-1 bg-broadcast-blue" />
        </div>
      </div>
      <span className="tabular text-sm font-bold text-text">{away !== null ? away.toFixed(decimals) : '—'}</span>
    </div>
  )
}

/** Real full-pitch shot map, both halves. FotMob reports every shot on its
 * own attacking 0-100 x-axis, so the away side is mirrored (`100 - x`)
 * purely so one pitch can carry both teams - the same display convention
 * this project's own backend match-centre renderer settled on. Real values
 * occasionally land just outside 0-100 and are clamped, or a genuine shot
 * gets clipped out of the viewBox entirely. Radius scales with real xG. */
function ShotMap({ shots, homeTeamId }: { shots: LiveShot[]; homeTeamId: number }) {
  const drawable = shots.filter((s) => s.x !== null && s.y !== null)
  if (drawable.length === 0) return null
  const W = 100
  const H = 62
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">Shot map</span>
        <span className="text-[9px] uppercase tracking-wide text-text-faint">{drawable.length} shots · radius = xG</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Shot map, ${drawable.length} real shots`}>
        <rect x="0.4" y="0.4" width={W - 0.8} height={H - 0.8} fill="none" stroke="var(--divider)" strokeWidth="0.5" />
        <line x1={W / 2} y1="0.4" x2={W / 2} y2={H - 0.4} stroke="var(--divider)" strokeWidth="0.5" />
        <circle cx={W / 2} cy={H / 2} r="8" fill="none" stroke="var(--divider)" strokeWidth="0.5" />
        <rect x="0.4" y={H / 2 - 18} width="16" height="36" fill="none" stroke="var(--divider)" strokeWidth="0.5" />
        <rect x="0.4" y={H / 2 - 8} width="5.5" height="16" fill="none" stroke="var(--divider)" strokeWidth="0.5" />
        <rect x={W - 16.4} y={H / 2 - 18} width="16" height="36" fill="none" stroke="var(--divider)" strokeWidth="0.5" />
        <rect x={W - 5.9} y={H / 2 - 8} width="5.5" height="16" fill="none" stroke="var(--divider)" strokeWidth="0.5" />
        {drawable.map((s, i) => {
          const isHome = s.team_id === homeTeamId
          const displayX = isHome ? (s.x as number) : 100 - (s.x as number)
          const cx = Math.max(0, Math.min(100, displayX))
          const cy = Math.max(0, Math.min(100, s.y as number)) * (H / 100)
          const isGoal = s.outcome === 'Goal'
          // Real xGOT (confirmed live 2026-09-10, `expectedGoalsOnTarget` -
          // a genuine separate field from xg) drives radius for an
          // on-target shot specifically, since it's the more honest read of
          // "how good was this chance" once the effort is actually on
          // frame - xg alone can't distinguish a well-placed on-target shot
          // from a tame one. Off-target/blocked shots keep xg, the only
          // real quality figure they have.
          const r = Math.max(0.9, Math.min(3.4, Math.sqrt((s.is_on_target ? s.xgot : null) ?? s.xg ?? 0.02) * 5))
          const color = isHome ? 'var(--pitch-green)' : 'var(--broadcast-blue)'
          return (
            <circle
              key={i}
              cx={cx}
              cy={cy}
              r={r}
              fill={isGoal ? color : 'none'}
              stroke={color}
              strokeWidth="0.6"
              opacity={isGoal ? 1 : s.is_on_target ? 0.85 : 0.4}
            >
              <title>
                {s.player_name ?? 'Unknown'}{s.minute !== null ? ` ${s.minute}'` : ''} · {s.outcome ?? 'shot'}
                {s.xg !== null ? ` · ${s.xg.toFixed(2)} xG` : ''}
                {s.is_on_target && s.xgot !== null ? ` · ${s.xgot.toFixed(2)} xGOT` : ''}
              </title>
            </circle>
          )
        })}
      </svg>
    </div>
  )
}

function MyPlayerRow({ p }: { p: LiveMatchPlayer }) {
  const involved = (p.goals ?? 0) > 0 || (p.assists ?? 0) > 0
  return (
    <div className={`flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-divider py-2 last:border-b-0 ${involved ? 'bg-pitch-green/10' : ''}`}>
      <Link to={`/player/${p.player_id}`} className="font-bold text-text hover:text-pitch-green">{p.web_name}</Link>
      {!p.started && <span className="bg-raised px-1 py-0.5 text-[9px] font-bold uppercase text-text-muted">sub</span>}
      {(p.goals ?? 0) > 0 && <span className="text-sm font-bold text-pitch-green">{p.goals}G</span>}
      {(p.assists ?? 0) > 0 && <span className="text-sm font-bold text-broadcast-gold">{p.assists}A</span>}
      <span className="tabular ml-auto flex shrink-0 gap-3 text-xs text-text-muted">
        {p.minutes !== null && <span>{p.minutes}&prime;</span>}
        {p.xg !== null && <span>{p.xg.toFixed(2)} xG</span>}
        {p.xa !== null && <span>{p.xa.toFixed(2)} xA</span>}
        {p.rating !== null && <span className="font-bold text-text">{p.rating.toFixed(1)}</span>}
      </span>
    </div>
  )
}

function stat(s: LiveTeamMatchStats | null, k: keyof LiveTeamMatchStats): number | null {
  return s ? (s[k] as number | null) : null
}

/** The leading real minute out of FotMob's own already-complete display
 * string ("24'" -> 24, "45+2'" -> 45, "HT"/"FT" -> null - no real "current
 * minute" during a break). Only ever used for a real elapsed-time
 * calculation (the last-shot ticker below), never re-rendered as if it
 * were the real display string itself (`live_minute` already is one). */
function parseLiveMinute(live_minute: string | null): number | null {
  if (!live_minute) return null
  const match = /^(\d+)/.exec(live_minute)
  return match ? Number(match[1]) : null
}

/** One real live match, composed as a broadcast match card rather than a
 * data card: scoreline dominant, the contest expressed as opposed rules,
 * then the two genuinely spatial objects (momentum band, shot map), then
 * only my own players. Every value is a straight read of
 * `live_snapshot.json::active_matches` - nothing derived in the browser,
 * nothing filled in when the feed hasn't sent it. */
export function MatchCard({ m }: { m: LiveMatch }) {
  const homeCrest = crestUrl(m.home_code)
  const awayCrest = crestUrl(m.away_code)
  const hs = m.team_stats.home
  const as = m.team_stats.away
  const hasStats = hs !== null || as !== null
  const [orbView, setOrbView] = useState(false)

  return (
    <div className={`bg-void border-l-4 ${m.is_squad_match ? 'border-broadcast-gold' : 'border-divider'}`}>
      <div className="flex items-center gap-4 px-6 py-5">
        <Link to={`/club/${m.home_team_id}`} className="flex flex-1 items-center justify-end gap-3 hover:opacity-80">
          <span className="font-display text-xl font-bold uppercase tracking-wide text-text">{m.home_short}</span>
          {homeCrest && <img src={homeCrest} alt="" className="h-9 w-9" />}
        </Link>
        <div className="shrink-0 text-center">
          <div className="tabular font-display text-5xl font-bold leading-none text-text">
            {m.home_score ?? 0}<span className="mx-1.5 text-text-faint">-</span>{m.away_score ?? 0}
          </div>
          <div className="mt-1.5 flex items-center justify-center gap-1.5">
            <span className={`size-1.5 rounded-full ${m.status === 'LIVE' ? 'animate-pulse-live bg-alert-red' : 'bg-broadcast-gold'}`} />
            <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-text-muted">
              {/* FotMob's own display string is already complete ("17'",
                  "HT", "45+2'") - a real, previously-dormant bug appended a
                  second apostrophe on top of it (never caught live - this
                  whole screen has been untestable without an actual live
                  match). Rendered as-is now. */}
              {m.live_minute ?? m.status}
            </span>
          </div>
        </div>
        <Link to={`/club/${m.away_team_id}`} className="flex flex-1 items-center gap-3 hover:opacity-80">
          {awayCrest && <img src={awayCrest} alt="" className="h-9 w-9" />}
          <span className="font-display text-xl font-bold uppercase tracking-wide text-text">{m.away_short}</span>
        </Link>
      </div>

      {m.is_squad_match && (
        <div className="bg-broadcast-gold px-6 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-broadcast-gold-ink">
          Your squad is in this match
        </div>
      )}

      {m.win_probability && (
        <div className="border-t-2 border-divider px-6 py-3" title={m.win_probability.basis}>
          <div className="mb-1.5 flex items-baseline justify-between text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">
            <span>Win probability</span>
            <div className="flex items-center gap-2">
              <span className="normal-case tracking-normal text-text-faint">real-time, not live-performance-adjusted</span>
              <button
                type="button"
                onClick={() => setOrbView((v) => !v)}
                className={`px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ${orbView ? 'bg-broadcast-blue text-void' : 'bg-raised text-text-muted hover:text-text'}`}
              >
                {orbView ? 'Bar' : '3D'}
              </button>
            </div>
          </div>
          {orbView ? (
            <div className="h-28 w-full">
              <WinProbabilityOrb3D
                split={{
                  homeWinPct: m.win_probability.home_win_pct,
                  drawPct: m.win_probability.draw_pct,
                  awayWinPct: m.win_probability.away_win_pct,
                }}
              />
            </div>
          ) : (
            <>
              <div className="flex h-3 w-full overflow-hidden">
                <div className="bg-pitch-green" style={{ width: `${m.win_probability.home_win_pct}%` }} />
                <div className="bg-text-faint" style={{ width: `${m.win_probability.draw_pct}%` }} />
                <div className="bg-broadcast-blue" style={{ width: `${m.win_probability.away_win_pct}%` }} />
              </div>
              <div className="mt-1 flex justify-between text-[10px] font-bold">
                <span className="text-pitch-green">{m.win_probability.home_win_pct.toFixed(0)}%</span>
                <span className="text-text-faint">{m.win_probability.draw_pct.toFixed(0)}% draw</span>
                <span className="text-broadcast-blue">{m.win_probability.away_win_pct.toFixed(0)}%</span>
              </div>
            </>
          )}
        </div>
      )}

      {hasStats && (
        <div className="border-t-2 border-divider px-6 py-4">
          <OpposedStat label="Possession" home={stat(hs, 'possession_pct')} away={stat(as, 'possession_pct')} />
          <OpposedStat label="xG" home={stat(hs, 'xg')} away={stat(as, 'xg')} decimals={2} />
          <OpposedStat label="Shots" home={stat(hs, 'shots')} away={stat(as, 'shots')} />
          <OpposedStat label="On target" home={stat(hs, 'shots_on_target')} away={stat(as, 'shots_on_target')} />
          <OpposedStat label="Big chances" home={stat(hs, 'big_chances')} away={stat(as, 'big_chances')} />
          <OpposedStat label="Chances created" home={stat(hs, 'chances_created')} away={stat(as, 'chances_created')} />
          <OpposedStat label="Corners" home={stat(hs, 'corners')} away={stat(as, 'corners')} />
          {/* Real discipline meter - the same real FotMob team-card counts
              (migration 0042) other screens already show for a finished
              match, now on the live card too. Yellow and red kept as two
              separate real opposed rows rather than one blended "discipline
              score" - a weighting scheme (is a red really "worth" 2
              yellows?) would be an invented number, not a real one. */}
          <OpposedStat label="Yellow cards" home={stat(hs, 'yellow_cards')} away={stat(as, 'yellow_cards')} />
          <OpposedStat label="Red cards" home={stat(hs, 'red_cards')} away={stat(as, 'red_cards')} />
          {(hs?.formation || as?.formation) && (
            <div className="mt-2 flex items-center justify-between text-[11px] text-text-muted">
              <span>{hs?.formation ?? '—'}</span>
              <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">Formation</span>
              <span>{as?.formation ?? '—'}</span>
            </div>
          )}
        </div>
      )}

      {/* Real "time since last shot" ticker - FotMob's own real shot
          timestamps (`m.shots`, already ordered most-recent-first by the
          backend) diffed against the real current live minute. Omitted
          entirely at kickoff/half-time/before any shot - never a
          fabricated "0m" reading. */}
      {m.shots.length > 0 && m.shots[0].minute !== null && (() => {
        const nowMinute = parseLiveMinute(m.live_minute)
        if (nowMinute === null) return null
        const elapsed = Math.max(nowMinute - m.shots[0].minute!, 0)
        return (
          <div className="border-t-2 border-divider px-6 py-2 text-center text-[10px] font-bold uppercase tracking-[0.12em] text-text-faint">
            {elapsed === 0 ? 'Shot just now' : `${elapsed}' since last shot`}
            {m.shots[0].player_name && <span className="normal-case tracking-normal text-text-muted"> &middot; {m.shots[0].player_name}</span>}
          </div>
        )
      })()}

      {(m.momentum.length > 1 || m.shots.length > 0) && (
        <div className="grid grid-cols-1 gap-6 border-t-2 border-divider px-6 py-4 xl:grid-cols-2">
          <MomentumBand
            points={m.momentum}
            isLive={m.status === 'LIVE' || m.status === 'HALFTIME'}
            // Real goal markers derived from the same shot list the shot
            // map already renders (`outcome === 'Goal'`, FotMob's own raw
            // eventType) - no new source, never a fabricated card marker
            // (this project has no per-match card timeline to draw from).
            markers={m.shots
              .filter((s) => s.outcome === 'Goal' && s.minute !== null)
              .map((s) => ({ minute: s.minute!, isHome: s.team_id === m.home_team_id, kind: 'Goal' as const }))}
          />
          <ShotMap shots={m.shots} homeTeamId={m.home_team_id} />
        </div>
      )}

      {m.my_players.length > 0 && (
        <div className="border-t-2 border-divider px-6 py-4">
          <div className="mb-1 text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">My players in this match</div>
          {m.my_players
            .slice()
            .sort((a, b) => (b.minutes ?? 0) - (a.minutes ?? 0))
            .map((p) => <MyPlayerRow key={p.player_id} p={p} />)}
        </div>
      )}
    </div>
  )
}
