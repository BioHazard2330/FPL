import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** WORKLOAD: every match of the last 28 days for the squad and the plan's targets, league and cup alike, from FotMob -
 * minutes over 7 and 14 days, distance run, and the latest top speed against his own average (a drop is worth a look,
 * not a verdict). Context only: congestion has not moved league minutes measurably. */

interface Row {
  player_id: number; name: string; photo_code: number | null; team_code: number | null; mine: boolean
  minutes_7: number; minutes_14: number; minutes_28: number; cup_minutes_14: number; league_minutes_14: number; matches_14: number; distance_14_km: number
  last: { competition: string; kickoff: string; minutes: number; distance_km: number; sprints: number | null; top_speed: number | null; touches_box: number | null } | null
  top_speed_avg: number | null
  matches: { competition: string; kickoff: string; minutes: number }[]
}

export function Workload() {
  const state = useFetch(() => getJson<{ status: string; players: Row[] }>('/api/workload'), [])
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const rows = [...state.data.players].sort((a, b) => Number(b.mine) - Number(a.mine) || b.minutes_14 - a.minutes_14)
  const now = Date.now()
  const day = 86_400_000
  return (
    <section className="px-10 py-8">
      <div className="voice text-lg text-text-muted">every match of the last four weeks, league and cup</div>
      <h2 className="font-display text-text">Workload</h2>
      <div className="mt-4 grid grid-cols-[minmax(0,13rem)_minmax(0,1fr)_4.5rem_4.5rem_5rem_6.5rem] items-center gap-x-4 border-b-2 border-ink pb-1.5 text-[10.5px] font-bold uppercase tracking-[0.12em] text-text-faint">
        <span>player</span><span>last 28 days (bar height = minutes)</span><span className="text-right">7 days</span><span className="text-right">14 days</span><span className="text-right">km, 14d</span><span className="text-right">top speed</span>
      </div>
      {rows.map((r) => {
        const speedDrop = r.last?.top_speed && r.top_speed_avg ? r.last.top_speed - r.top_speed_avg : null
        return (
          <div key={r.player_id} className={`grid grid-cols-[minmax(0,13rem)_minmax(0,1fr)_4.5rem_4.5rem_5rem_6.5rem] items-center gap-x-4 border-b border-divider py-1.5 ${r.mine ? '' : 'opacity-75'}`}>
            <Link to={`/player/${r.player_id}`} className="flex min-w-0 items-center gap-2 hover:text-spot">
              <PlayerPhoto code={r.photo_code} teamCode={r.team_code} className="h-9 w-7" />
              <span className="truncate text-[14px] font-bold text-text">{r.name}</span>
              {!r.mine && <span className="text-[10.5px] font-bold uppercase text-text-faint">target</span>}
            </Link>
            <div className="relative h-9 border-b border-ink/30">
              {r.matches.map((m) => {
                const age = (now - new Date(m.kickoff).getTime()) / day
                if (age > 28 || age < 0) return null
                const cup = m.competition !== 'Premier League'
                return (
                  <div key={m.kickoff} title={`${m.competition}: ${m.minutes}'`}
                    className={`absolute bottom-0 w-2.5 -translate-x-1/2 border border-ink ${cup ? 'bg-broadcast-blue' : 'bg-pitch-green'}`}
                    style={{ left: `${100 - (age / 28) * 100}%`, height: `${Math.max(8, (m.minutes / 90) * 100)}%` }} />
                )
              })}
            </div>
            <span className={`tabular text-right font-display text-xl font-black ${r.minutes_7 >= 170 ? 'text-alert-red' : 'text-text'}`}>{r.minutes_7}</span>
            <span className="tabular text-right font-display text-xl font-black text-text">{r.league_minutes_14}{r.cup_minutes_14 ? <span className="ml-0.5 text-[11px] text-broadcast-blue">+{r.cup_minutes_14}c</span> : null}</span>
            <span className="tabular text-right font-display text-lg font-black text-text-muted">{r.distance_14_km || '—'}</span>
            <span className="tabular text-right text-[13px]">
              {r.last?.top_speed ? <span className="font-display text-lg font-black text-text">{r.last.top_speed.toFixed(1)}</span> : '—'}
              {speedDrop !== null && Math.abs(speedDrop) >= 1 && (
                <span className={`ml-1 font-bold ${speedDrop < 0 ? 'text-alert-red' : 'text-pitch-green'}`}>{speedDrop > 0 ? '+' : ''}{speedDrop.toFixed(1)}</span>
              )}
            </span>
          </div>
        )
      })}
      <div className="mt-2 flex flex-wrap gap-4 text-[11.5px] text-text-muted">
        <span className="flex items-center gap-1.5"><span className="inline-block size-3 border border-ink bg-pitch-green" />league</span>
        <span className="flex items-center gap-1.5"><span className="inline-block size-3 border border-ink bg-broadcast-blue" />cup and Europe</span>
        <span>14-day minutes: league, then cup (c). Top speed in km/h, last match against his own average. Red: 170+ minutes in 7 days.</span>
      </div>
    </section>
  )
}
