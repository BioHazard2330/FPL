import { Link, useParams } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import { crestUrl, fetchMatchReport } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { MatchLineupRow, MatchTimelineRow, MatchTeamStats } from '@/lib/types'

const EVENT_MARK: Record<string, { label: string; ink: string; fill: string }> = {
  Goal: { label: 'Goal', ink: 'text-pitch-green', fill: 'bg-pitch-green' },
  Penalty: { label: 'Penalty', ink: 'text-pitch-green', fill: 'bg-pitch-green' },
  OwnGoal: { label: 'Own goal', ink: 'text-alert-red', fill: 'bg-alert-red' },
  MissedPenalty: { label: 'Penalty missed', ink: 'text-alert-red', fill: 'bg-alert-red' },
  Card: { label: 'Card', ink: 'text-broadcast-gold', fill: 'bg-broadcast-gold' },
  Substitution: { label: 'Substitution', ink: 'text-text-faint', fill: 'bg-text-faint' },
  VAR: { label: 'VAR', ink: 'text-broadcast-blue', fill: 'bg-broadcast-blue' },
}

/** Opposed team stat, on a shared scale. Same grammar as the live match
 * card - the contest is one shape, not two numbers to compare by hand. */
function Opposed({ label, home, away, decimals = 0 }: { label: string; home: number | null; away: number | null; decimals?: number }) {
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

/** The timeline, read down the middle with the minute as the spine and each
 * event sitting on its own team's side - the way a match report is laid out
 * on every football site, and the reason it is instantly readable. */
function TimelineRow({ e }: { e: MatchTimelineRow }) {
  const mark = EVENT_MARK[e.event_type] ?? { label: e.event_type, ink: 'text-text-muted', fill: 'bg-text-faint' }
  const body = (
    <div className={`min-w-0 ${e.is_home ? 'text-right' : 'text-left'}`}>
      <div className={`text-[9px] font-bold uppercase tracking-[0.14em] ${mark.ink}`}>{mark.label}</div>
      <div className="truncate text-sm font-bold text-text">
        {e.player_id !== null ? (
          <Link to={`/player/${e.player_id}`} className="hover:text-pitch-green">{e.player_name ?? '—'}</Link>
        ) : (
          e.player_name ?? '—'
        )}
        {e.is_mine && <span className="ml-1.5 bg-broadcast-gold px-1 text-[8px] font-bold text-broadcast-gold-ink">MINE</span>}
      </div>
      {e.description && <div className="truncate text-[11px] text-text-faint">{e.description}</div>}
    </div>
  )
  return (
    <div className="grid grid-cols-[1fr_3rem_1fr] items-center gap-3 border-b border-divider py-2.5">
      {e.is_home ? body : <div />}
      <div className="flex flex-col items-center gap-1">
        <span className={`size-2 shrink-0 ${mark.fill}`} />
        <span className="tabular text-[11px] font-bold text-text-muted">{e.minute !== null ? `${e.minute}'` : '—'}</span>
      </div>
      {e.is_home ? <div /> : body}
    </div>
  )
}

function LineupTable({ rows, title }: { rows: MatchLineupRow[]; title: string }) {
  const starters = rows.filter((r) => r.started)
  const subs = rows.filter((r) => !r.started)
  const render = (list: MatchLineupRow[]) =>
    list.map((r, i) => (
      <div key={`${r.player_id ?? 'x'}-${i}`} className={`flex items-baseline gap-2 border-b border-divider py-1.5 text-sm ${r.is_mine ? 'bg-panel' : ''}`}>
        <span className="min-w-0 flex-1 truncate font-bold text-text">
          {r.player_id !== null ? (
            <Link to={`/player/${r.player_id}`} className="hover:text-pitch-green">{r.name ?? '—'}</Link>
          ) : (
            r.name ?? '—'
          )}
          {r.is_mine && <span className="ml-1.5 bg-broadcast-gold px-1 text-[8px] font-bold text-broadcast-gold-ink">MINE</span>}
        </span>
        {(r.goals ?? 0) > 0 && <span className="shrink-0 text-xs font-bold text-pitch-green">{r.goals}G</span>}
        {(r.assists ?? 0) > 0 && <span className="shrink-0 text-xs font-bold text-broadcast-gold">{r.assists}A</span>}
        <span className="tabular shrink-0 text-[11px] text-text-faint">
          {r.minutes !== null && r.minutes > 0 ? `${r.minutes}'` : '—'}
        </span>
        {r.rating !== null && (
          <span
            className={`tabular w-8 shrink-0 text-right text-xs font-bold ${
              r.rating >= 7.5 ? 'text-pitch-green' : r.rating < 6.2 ? 'text-alert-red' : 'text-text'
            }`}
          >
            {r.rating.toFixed(1)}
          </span>
        )}
      </div>
    ))
  const anyDetail = rows.some((r) => r.rating !== null || (r.minutes ?? 0) > 0)
  return (
    <div>
      <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">{title}</div>
      {!anyDetail && (
        <p className="mb-3 text-[11px] text-text-faint">
          No per-player minutes or ratings were captured for this match &mdash; the lineup below is real, the detail
          simply was not recorded.
        </p>
      )}
      {render(starters)}
      {subs.length > 0 && (
        <>
          <div className="mb-1 mt-4 text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">Substitutes</div>
          <div className="opacity-70">{render(subs)}</div>
        </>
      )}
    </div>
  )
}

function stat(s: MatchTeamStats | null, k: keyof MatchTeamStats): number | null {
  const v = s ? s[k] : null
  return typeof v === 'number' ? v : null
}

export function MatchScreen() {
  const { id } = useParams()
  const state = useFetch(() => fetchMatchReport(Number(id)), [id], 30000)

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="border-b-2 border-divider px-10 py-8">
          <Skel className="mx-auto h-14 w-56" />
        </div>
        <div className="space-y-2 px-10 py-8">
          {[0, 1, 2, 3, 4, 5].map((i) => <Skel key={i} className="h-8 w-full" />)}
        </div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Match report unavailable"
        description="No report could be fetched for this match. If the id does not exist the backend returns a real 404 rather than an empty report."
        message={state.error.message}
      />
    )
  }

  const p = state.data
  const m = p.match
  const homeCrest = crestUrl(m.home.code)
  const awayCrest = crestUrl(m.away.code)
  const hs = p.team_stats.home
  const as = p.team_stats.away
  const live = m.status === 'LIVE' || m.status === 'HALFTIME'

  return (
    <div className="data-in pb-16">
      <Masthead
        edition="Match Report"
        title={`${m.home.short} v ${m.away.short}`}
        right={<span className="text-text-faint">{m.status.replace(/_/g, ' ')}</span>}
      />

      {/* THE SCORELINE */}
      <div className="border-b-2 border-divider px-10 py-8">
        <div className="flex items-center justify-center gap-6">
          <Link to={`/club/${m.home.team_id}`} className="flex flex-1 items-center justify-end gap-3 hover:opacity-80">
            <span className="truncate font-display text-2xl font-bold uppercase text-text">{m.home.name}</span>
            {homeCrest && <img src={homeCrest} alt="" className="h-12 w-12 shrink-0" />}
          </Link>
          <div className="shrink-0 text-center">
            <div className="tabular font-display text-6xl font-bold leading-none text-text">
              {m.home.score ?? 0}<span className="mx-2 text-text-faint">-</span>{m.away.score ?? 0}
            </div>
            <div className="mt-2 flex items-center justify-center gap-1.5">
              {live && <span className="size-1.5 animate-pulse-live rounded-full bg-alert-red" />}
              <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">
                {live ? (m.live_minute !== null ? `${m.live_minute}'` : m.status) : 'Full time'}
              </span>
            </div>
          </div>
          <Link to={`/club/${m.away.team_id}`} className="flex flex-1 items-center gap-3 hover:opacity-80">
            {awayCrest && <img src={awayCrest} alt="" className="h-12 w-12 shrink-0" />}
            <span className="truncate font-display text-2xl font-bold uppercase text-text">{m.away.name}</span>
          </Link>
        </div>
        {(hs?.formation || as?.formation) && (
          <div className="mt-4 flex items-center justify-center gap-6 text-[11px] font-bold uppercase tracking-[0.16em] text-text-faint">
            <span>{hs?.formation ?? ''}</span>
            <span className="text-text-faint">formation</span>
            <span>{as?.formation ?? ''}</span>
          </div>
        )}
      </div>

      {/* THE CONTEST */}
      {(hs || as) && (
        <div className="border-b-2 border-divider px-10 py-6">
          <Opposed label="Possession" home={stat(hs, 'possession_pct')} away={stat(as, 'possession_pct')} />
          <Opposed label="xG" home={stat(hs, 'xg')} away={stat(as, 'xg')} decimals={2} />
          <Opposed label="Shots" home={stat(hs, 'shots')} away={stat(as, 'shots')} />
          <Opposed label="On target" home={stat(hs, 'shots_on_target')} away={stat(as, 'shots_on_target')} />
          <Opposed label="Big chances" home={stat(hs, 'big_chances')} away={stat(as, 'big_chances')} />
          <Opposed label="Corners" home={stat(hs, 'corners')} away={stat(as, 'corners')} />
        </div>
      )}

      {/* THE TIMELINE */}
      {p.timeline.length > 0 && (
        <div className="border-b-2 border-divider px-10 py-8">
          <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Timeline</div>
          {p.timeline.map((e, i) => <TimelineRow key={i} e={e} />)}
        </div>
      )}

      {/* BOTH TEAMS - the live screen only ever showed my own players. */}
      {(p.lineups.home.length > 0 || p.lineups.away.length > 0) && (
        <div className="grid grid-cols-1 gap-px bg-divider lg:grid-cols-2">
          <div className="bg-void px-10 py-8">
            <LineupTable rows={p.lineups.home} title={`${m.home.name} · ratings`} />
          </div>
          <div className="bg-void px-10 py-8">
            <LineupTable rows={p.lineups.away} title={`${m.away.name} · ratings`} />
          </div>
        </div>
      )}
    </div>
  )
}
