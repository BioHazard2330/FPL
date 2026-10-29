import { Panel } from '@/components/ui/kit'
import type { WeekPlanPayload } from '@/lib/types'

const ORDINAL = ['1st', '2nd', '3rd', '4th', '5th']

/** WHAT EACH EXTRA TRANSFER BUYS.
 *
 * The question a manager holding several free transfers is really asking: how many of them are worth using? Each bar is what
 * the next transfer adds on top of the plan that already contains the ones before it, over the same horizon. The rule is
 * drawn, not described: a transfer that does not reach the line is not recommended, and the first bar to fall short ends the
 * plan. The diminishing returns are real: each move spends the best remaining opportunity first. */
export function MarginalValue({ plan }: { plan: WeekPlanPayload }) {
  const curve = plan.curve ?? []
  if (curve.length < 2) return null
  const steps = curve.slice(1).map((c, i) => ({ k: c.moves, marginal: c.total - curve[i].total }))
  const kept = (plan.moves ?? []).length
  const bar = plan.min_move_gain ?? 1.5
  const scale = Math.max(...steps.map((s) => s.marginal), bar, 1) * 1.15
  const ft = plan.free_transfers ?? 0

  return (
    <Panel
      title="What each extra transfer buys"
      sub={`Points the next transfer adds over ${plan.horizon} gameweeks, on top of the ones before it. A transfer has to reach ${bar} to be recommended.${ft >= 5 ? ' You hold five free transfers, so using one costs nothing and rolling wastes one.' : ''}`}
    >
      <div className="relative space-y-3 pt-4">
        <div className="pointer-events-none absolute -top-3 bottom-0 z-10 border-l-2 border-dashed border-ink" style={{ left: `calc(4.25rem + (100% - 8.5rem) * ${bar / scale})` }}>
          <span className="absolute -top-2 left-1 whitespace-nowrap bg-ink px-1.5 font-display text-[12px] font-black uppercase text-paper">bar {bar}</span>
        </div>
        {steps.map((s) => {
          const taken = s.k <= kept
          return (
            <div key={s.k} className="flex items-center gap-3">
              <span className="w-[3.5rem] shrink-0 font-display text-lg font-black uppercase text-text">{ORDINAL[s.k - 1] ?? `${s.k}th`}</span>
              <div className="relative h-7 flex-1 border-2 border-ink bg-paper">
                <div className={`bar-draw h-full ${taken ? 'bg-pitch-green' : '[background-image:repeating-linear-gradient(135deg,var(--text-faint)_0_2px,transparent_2px_7px)]'}`} style={{ width: `${Math.max(1.5, (Math.max(s.marginal, 0) / scale) * 100)}%` }} />
              </div>
              <span className={`tabular w-[3.5rem] shrink-0 text-right font-display text-2xl font-black ${taken ? 'text-pitch-green' : 'text-text-faint'}`}>
                {s.marginal >= 0 ? '+' : ''}
                {s.marginal.toFixed(1)}
              </span>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}
