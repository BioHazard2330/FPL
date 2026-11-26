import { Link } from 'react-router-dom'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** The deadline watch (`models/deadline_watch.py`): in the last 30 hours, every player who decides the gameweek - your
 * fifteen, the pundit's call, the plan's moves - with any red or amber finding from the pre-flight checks, an unflagged
 * injury headline or the start feed. Red findings in the last three hours also raise an alert. */
interface Flag { check: string; level: 'red' | 'amber'; text: string }
interface Row { player_id: number; name: string; team: string; roles: string[]; level: 'red' | 'amber' | 'clear'; start_percent: number | null; flags: Flag[] }
interface Payload { status: string; event?: number; hours_left?: number; show?: boolean; red?: number; amber?: number; players?: Row[] }

const DOT = { red: 'bg-alert-red', amber: 'bg-broadcast-gold', clear: 'bg-pitch-green' }

export function DeadlineWatch() {
  const st = useFetch(() => getJson<Payload>('/api/deadlinewatch'), [])
  if (st.status !== 'ready' || st.data.status !== 'ok' || !st.data.show) return null
  const d = st.data
  const flagged = (d.players ?? []).filter((r) => r.level !== 'clear')
  const clear = (d.players ?? []).filter((r) => r.level === 'clear')
  return (
    <section className="px-8 py-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-text">Deadline watch · GW{d.event}</h2>
          <p className="voice mt-1 text-[15px] text-text-muted">
            {d.hours_left}h to the deadline. {flagged.length === 0 ? 'Everyone who decides the week is clear.' : `${d.red} red, ${d.amber} amber among the players who decide the week.`}
          </p>
        </div>
        <div className="flex border-2 border-ink font-display text-xl font-black tabular">
          <span className="bg-alert-red px-3 py-1 text-alert-red-ink">{d.red}</span>
          <span className="bg-broadcast-gold px-3 py-1 text-broadcast-gold-ink">{d.amber}</span>
          <span className="bg-pitch-green px-3 py-1 text-pitch-green-ink">{clear.length}</span>
        </div>
      </div>
      {flagged.length > 0 && (
        <div className="mt-4 divide-y divide-divider border-y-2 border-ink">
          {flagged.map((r) => (
            <Link key={r.player_id} to={`/player/${r.player_id}`} className="grid grid-cols-[0.7rem_9rem_minmax(0,1fr)_3.5rem] items-center gap-3 py-2 hover:bg-raised/40">
              <span className={`size-3 rounded-full ${DOT[r.level]}`} />
              <span className="min-w-0">
                <span className="block truncate font-display text-lg font-black uppercase leading-none text-text">{r.name}</span>
                <span className="block truncate text-[11px] text-text-faint">{r.team} · {r.roles.join(', ')}</span>
              </span>
              <span className="min-w-0 truncate text-[13px] text-text-muted" title={r.flags.map((f) => f.text).join(' · ')}>{r.flags.map((f) => f.text).join(' · ')}</span>
              <span className="tabular text-right font-black text-text">{r.start_percent != null ? `${r.start_percent}%` : '–'}</span>
            </Link>
          ))}
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {clear.map((r) => (
          <span key={r.player_id} title={r.roles.join(', ')} className="border-2 border-pitch-green/50 px-1.5 text-[12px] font-bold text-text">{r.name}</span>
        ))}
      </div>
    </section>
  )
}
