import { Link } from 'react-router-dom'
import { EdgeDensity } from '@/components/charts/EdgeDensity'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchLiveCone } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** WHERE THIS GAMEWEEK ENDS - the rest of the gameweek simulated from the state
 * it is in right now: matches not started are played out whole, matches under
 * way are played out from their minute and score, finished ones are done. Your
 * final score and the average manager's are summed over the same simulated
 * endings, so the gap is a real distribution, not a guess from the table.
 * Renders nothing outside a gameweek in progress. */
export function LiveCone() {
  const state = useFetch(fetchLiveCone, [], 30000)
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  const f = d.forecast!
  const e = d.edge!
  const span = Math.max(f.p90 - Math.min(f.p10, d.now ?? 0), 1)
  const lo = Math.min(f.p10, d.now ?? f.p10)
  const at = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / span) * 100))}%`
  const movers = (d.players ?? []).slice(0, 6)

  return (
    <section className="border-b-2 border-divider px-10 py-8">
      <div className="mb-1 flex flex-wrap items-baseline gap-x-5">
        <span className="font-display text-2xl font-bold uppercase tracking-wide text-text">Where GW{d.event} ends</span>
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-text-faint">
          {d.fixtures_left} match{d.fixtures_left === 1 ? '' : 'es'} still to finish · {d.fixtures_live} live · simulated from the current score and minute
        </span>
      </div>
      <div className="mt-4 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-12">
        <div>
          <div className="flex flex-wrap items-end gap-x-10 gap-y-3">
            <div>
              <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">Likely finish</div>
              <div className="tabular font-display text-6xl font-bold leading-none text-pitch-green">{f.p50.toFixed(0)}</div>
              <div className="tabular mt-1 text-xs text-text-faint">{f.p10.toFixed(0)} to {f.p90.toFixed(0)} in 4 of 5 endings</div>
            </div>
            <div>
              <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">Average manager</div>
              <div className="tabular font-display text-4xl font-bold leading-none text-text-muted">{d.field_forecast?.toFixed(0)}</div>
              <div className="tabular mt-1 text-xs text-text-faint">{d.field_now?.toFixed(0)} so far</div>
            </div>
            <div>
              <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">Ahead of them</div>
              <div className="tabular font-display text-4xl font-bold leading-none text-text">{Math.round(e.p_beat * 100)}%</div>
              <div className="tabular mt-1 text-xs text-text-faint">{e.mean >= 0 ? '+' : ''}{e.mean.toFixed(1)} on average</div>
            </div>
          </div>
          <div className="mt-6">
            <div className="relative h-3 bg-raised">
              <div className="absolute inset-y-0 bg-pitch-green/40" style={{ left: at(f.p10), right: `calc(100% - ${at(f.p90)})` }} />
              <div className="absolute inset-y-[-3px] w-1 bg-text" style={{ left: at(d.now ?? 0) }} title="your points now" />
              <div className="absolute inset-y-[-3px] w-1 bg-pitch-green" style={{ left: at(f.p50) }} title="likely finish" />
            </div>
            <div className="tabular mt-1 flex justify-between text-[10px] text-text-faint">
              <span>{lo.toFixed(0)}</span>
              <span>now {d.now?.toFixed(0)}</span>
              <span>{f.p90.toFixed(0)}</span>
            </div>
          </div>
          <div className="mt-4">
            <EdgeDensity series={[{ key: 'edge', label: 'You minus the average manager', hist: e.hist, color: 'var(--pitch-green)' }]} min={d.axis!.min} max={d.axis!.max} height={150} />
          </div>
        </div>
        <div>
          <div className="mb-2 text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">Who can still move it</div>
          {movers.length === 0 && <p className="text-sm text-text-muted">Nobody in your eleven has anything left to play.</p>}
          {movers.map((p) => (
            <div key={p.player_id} className="grid grid-cols-[2.2rem_minmax(0,1fr)_4rem_5.5rem_4.5rem] items-center gap-3 border-b border-divider py-2 text-sm">
              <PlayerPhoto code={p.photo_code} teamCode={p.team_code ?? null} isGkp={p.position === 'GKP'} className="h-9 w-7" />
              <div className="min-w-0">
                <Link to={`/player/${p.player_id}`} className="font-bold text-text hover:text-pitch-green">{p.name}</Link>
                {p.multiplier > 1 && <span className="ml-2 bg-broadcast-gold px-1 text-[9px] font-bold uppercase leading-4 text-broadcast-gold-ink">C</span>}
                <span className="ml-2 font-mono text-[10px] uppercase text-text-faint">{p.team_short}</span>
              </div>
              <div className="tabular text-right text-text-muted" title="points so far">{p.points_now} now</div>
              <div className="tabular text-right text-text" title="expected more, and how far it can swing">+{p.remaining_mean.toFixed(1)} ± {p.remaining_sd.toFixed(1)}</div>
              <div className="tabular text-right text-text-muted" title="chance of 5 or more points still to come">{Math.round(p.p_five_more * 100)}% for 5+</div>
            </div>
          ))}
          <p className="mt-3 text-[11px] leading-relaxed text-text-faint">
            Remaining points include the model's measured shortfall per player still to play. Automatic substitutions are not applied, so a benched player who comes on is a small understatement.
          </p>
        </div>
      </div>
    </section>
  )
}
