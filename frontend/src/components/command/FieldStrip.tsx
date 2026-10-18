import { Link } from 'react-router-dom'
import { fetchFieldPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** THIS WEEK AGAINST THE FIELD, in one line: the plan's edge over the average
 * manager, how often it beats them in simulation, and which captain the field
 * makes best for you. The full picture (the spread, the versions of your week,
 * the players the field has that you do not) is on the Field screen. Renders
 * nothing until the simulation has run, and nothing if it cannot. */
export function FieldStrip() {
  const state = useFetch(() => fetchFieldPayload('population'), [], 600000)
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  const plan = d.plan_option!
  const best = d.captains?.find((c) => c.player_id === d.best_captain_id)
  const chosen = d.captains?.find((c) => c.chosen)
  return (
    <section className="bg-panel px-10 py-8">
      <div className="mb-3 flex items-baseline justify-between">
        <span className="text-[13px] font-bold uppercase tracking-[0.15em] text-text-faint">Against the field</span>
        <Link to="/field" className="font-mono text-[12px] uppercase tracking-[0.1em] text-text-faint hover:text-text">The full picture &rarr;</Link>
      </div>
      <div className="flex flex-wrap items-end gap-x-12 gap-y-4">
        <div>
          <div className="tabular font-display text-5xl font-bold leading-none text-pitch-green">{plan.edge.mean >= 0 ? '+' : ''}{plan.edge.mean.toFixed(1)}</div>
          <div className="mt-1 text-xs text-text-faint">points over the average manager, on average</div>
        </div>
        <div>
          <div className="tabular font-display text-5xl font-bold leading-none text-text">{Math.round(plan.edge.p_beat * 100)}%</div>
          <div className="mt-1 text-xs text-text-faint">of simulated gameweeks you beat them</div>
        </div>
        {best && (
          <div className="max-w-sm text-sm text-text-muted">
            {chosen && chosen.player_id === best.player_id ? (
              <>The field makes <span className="font-bold text-text">{best.name}</span> your best armband too.</>
            ) : (
              <>Against the field <span className="font-bold text-text">{best?.name}</span> is the best armband; the plan has {chosen?.name}.</>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
