import { Link } from 'react-router-dom'
import { fetchReceiptsPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** THE PLAN'S RECORD in three numbers: what its recommended squad scored with its own eleven and armband over the gameweeks
 * it has been the decision of record, what last week's team scored left untouched, and what you scored as you played. Read from the counterfactual ledger, so a week
 * with no stored plan is absent rather than counted as zero. */
export function TrackRecord() {
  const state = useFetch(fetchReceiptsPayload, [])
  if (state.status !== 'ready') return null
  const h = state.data.headline
  if (!h || !h.plan_events || h.plan_total == null || h.plan_roll_total == null || h.plan_your_total == null) return null
  const vsRoll = h.plan_total - h.plan_roll_total
  const vsYou = h.plan_total - h.plan_your_total
  const figs: [string, number, string][] = [
    ['The plan', h.plan_total, 'text-text'],
    ["Last week's team, untouched", h.plan_roll_total, 'text-text-muted'],
    ['You, as you played', h.plan_your_total, 'text-text'],
  ]
  return (
    <section className="flex flex-wrap items-center gap-x-10 gap-y-3 rounded-xl border border-divider bg-panel px-6 py-4">
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-text-faint">The plan's record</div>
        <div className="text-[13px] text-text-muted">
          {h.plan_events} gameweek{h.plan_events > 1 ? 's' : ''} as the decision of record; the plan with its own eleven and armband
        </div>
      </div>
      {figs.map(([label, v, tone]) => (
        <div key={label}>
          <div className="text-[12px] text-text-faint">{label}</div>
          <div className={`font-display text-3xl font-bold leading-none tabular-nums ${tone}`}>{v}</div>
        </div>
      ))}
      <div className="text-[14px] leading-snug text-text-muted">
        Its moves and lineup were worth <span className={vsRoll >= 0 ? 'font-semibold text-pitch-green' : 'font-semibold text-alert-red'}>{vsRoll >= 0 ? '+' : ''}{vsRoll}</span> over leaving last week's team;
        you finished <span className="font-semibold text-text">{vsYou <= 0 ? `${-vsYou} ahead of` : `${vsYou} behind`}</span> it.{' '}
        <Link to="/receipts" className="text-text-faint hover:text-text">Full record &rarr;</Link>
      </div>
    </section>
  )
}
