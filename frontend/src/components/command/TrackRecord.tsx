import { Link } from 'react-router-dom'
import { fetchReceiptsPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { ReceiptsPayload, ReplayTotals } from '@/lib/types'

/** THE PLAN'S RECORD in three numbers: what its recommended squad scored with its own eleven and armband over the gameweeks
 * it has been the decision of record, what last week's team scored left untouched, and what you scored as you played. Read from the counterfactual ledger, so a week
 * with no stored plan is absent rather than counted as zero. */
export function TrackRecord() {
  const state = useFetch(fetchReceiptsPayload, [])
  if (state.status !== 'ready') return null
  const h = state.data.headline
  const replay = state.data.replay
  if (!h || !h.plan_events || h.plan_total == null || h.plan_roll_total == null || h.plan_your_total == null) return replay ? <Replay r={replay} /> : null
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
      {replay && <Replay r={replay} />}
    </section>
  )
}

/** The same transfer policy replayed over past seasons, leakage-free (`fpl plan-replay`). */
function Replay({ r }: { r: NonNullable<ReceiptsPayload['replay']> }) {
  const n = r.seasons.length
  const lead = r.lead ?? 'plan'
  const rows = (lead === 'plan_fixture'
    ? [['plan_fixture', 'Plan', 'bg-pitch-green', 'reads each club\'s matches and opponents'], ['plan', 'Blind', 'bg-broadcast-gold/70', 'same plan, every week one average match'], ['swap', 'Swap', 'bg-broadcast-blue', 'one swap a decision, old 2-point bar'], ['hold', 'Hold', 'bg-text-faint/60', 'never transfers']]
    : [['plan', 'Plan', 'bg-pitch-green', 'the week plan\'s solver'], ['swap', 'Swap', 'bg-broadcast-blue', 'one swap a decision'], ['hold', 'Hold', 'bg-text-faint/60', 'never transfers']]) as [keyof ReplayTotals, string, string, string][]
  const values = r.seasons.flatMap((s) => rows.map(([k]) => s.totals[k] ?? 0))
  const max = Math.max(...values)
  const min = Math.min(...values)
  const w = (v: number) => `${8 + ((v - min) / Math.max(1, max - min)) * 92}%`
  const total = (k: keyof ReplayTotals) => r.total[k] ?? 0
  return (
    <div className="mt-1 w-full border-t border-divider pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="text-[13px] text-text-muted">
          <span className="font-semibold text-text">Replayed on {n} past seasons:</span> the plan's transfer policy beat a single swap a decision in{' '}
          <span className="font-semibold text-pitch-green">{r.beat_swap} of {n}</span> (+{Math.round(total(lead) - total('swap'))} points) and never transferring in{' '}
          <span className="font-semibold text-pitch-green">{r.beat_hold} of {n}</span> (+{Math.round(total(lead) - total('hold'))}), hits included.
          {r.beat_blind != null && (
            <>
              {' '}Reading fixtures (how many matches, against whom) added{' '}
              <span className="font-semibold text-pitch-green">+{Math.round(total(lead) - total('plan'))}</span> over the same plan blind to them, ahead in {r.beat_blind} of {n}.
            </>
          )}
        </div>
        <span className="text-[12px] text-text-faint">walk-forward projections (appearance, goals, assists, cards, clean sheets), a decision every three gameweeks, no bonus or chips</span>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-5">
        {r.seasons.map((s) => (
          <div key={s.season} className="rounded-lg bg-void/40 px-3 py-2">
            <div className="mb-1.5 text-[12px] font-semibold text-text-muted">{s.season}</div>
            {rows.map(([k, label, tone, hint]) => (
              <div key={k} className="flex items-center gap-2 text-[11px] text-text-faint" title={hint}>
                <span className="w-9">{label}</span>
                <span className="h-1.5 flex-1 rounded-full bg-raised">
                  <span className={`bar-draw block h-full rounded-full ${tone}`} style={{ width: w(s.totals[k] ?? 0) }} />
                </span>
                <span className="w-9 text-right tabular-nums text-text-muted">{Math.round(s.totals[k] ?? 0)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
