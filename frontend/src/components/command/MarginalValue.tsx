import type { WeekPlanPayload } from '@/lib/types'

const ORDINAL = ['1st', '2nd', '3rd', '4th', '5th']
const BAR_AREA = 140
const FOOT = 28

/** WHAT EACH EXTRA TRANSFER BUYS.
 *
 * The question a manager holding several free transfers is really asking:
 * how many of them are worth using? Each bar is what the next transfer adds
 * on top of the plan that already contains the ones before it, over the same
 * horizon. The rule is drawn, not described: a transfer that does not reach
 * the line is not recommended, and the first bar to fall short ends the plan.
 *
 * Heights are the model's own differences between plans solved to the same
 * horizon - the diminishing returns are real, because each move spends the
 * best remaining opportunity first. */
export function MarginalValue({ plan }: { plan: WeekPlanPayload }) {
  const curve = plan.curve ?? []
  if (curve.length < 2) return null
  const steps = curve.slice(1).map((c, i) => ({ k: c.moves, marginal: c.total - curve[i].total }))
  const kept = (plan.moves ?? []).length
  const bar = plan.min_move_gain ?? 1.5
  const scale = Math.max(...steps.map((s) => s.marginal), bar, 1) * 1.1
  const ft = plan.free_transfers ?? 0
  const lineBottom = FOOT + (bar / scale) * BAR_AREA

  return (
    <section className="bg-panel px-10 py-10">
      <div className="mb-1 text-[13px] font-bold uppercase tracking-[0.15em] text-text-faint">What each extra transfer buys</div>
      <p className="mb-8 max-w-2xl text-sm text-text-muted">
        Points added over {plan.horizon} gameweeks by the next transfer, on top of the ones before it.
        {ft >= 5 && ' You hold five free transfers, so using one costs nothing and rolling wastes one.'}
      </p>

      <div className="relative max-w-3xl" style={{ height: BAR_AREA + FOOT + 44 }}>
        <div className="absolute inset-x-0 border-t border-dashed border-broadcast-gold/70" style={{ bottom: lineBottom }} />
        <span
          className="absolute right-0 bg-panel pl-2 text-[11px] font-bold uppercase tracking-[0.1em] text-broadcast-gold"
          style={{ bottom: lineBottom + 4 }}
        >
          {bar} points &mdash; the least a transfer has to earn
        </span>

        <div className="flex h-full items-end gap-px">
          {steps.map((s) => {
            const taken = s.k <= kept
            const h = Math.max(3, (Math.max(s.marginal, 0) / scale) * BAR_AREA)
            return (
              <div key={s.k} className="flex w-24 flex-col items-center justify-end" style={{ height: '100%' }}>
                <div className={`tabular mb-1.5 font-display text-2xl font-bold ${taken ? 'text-pitch-green' : 'text-text-faint'}`}>
                  {s.marginal >= 0 ? '+' : ''}
                  {s.marginal.toFixed(1)}
                </div>
                <div className={`bar-draw-up w-14 ${taken ? 'bg-pitch-green' : 'bg-raised'}`} style={{ height: h }} />
                <div
                  className="flex items-center text-[12px] font-bold uppercase tracking-[0.1em] text-text-faint"
                  style={{ height: FOOT }}
                >
                  {ORDINAL[s.k - 1] ?? `${s.k}th`} transfer
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
