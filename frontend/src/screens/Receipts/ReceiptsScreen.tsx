import { Masthead } from '@/components/shell/Masthead'
import { fetchReceiptsPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import type { LedgerRow, ReceiptsPayload } from '@/lib/types'

/** THE RECEIPTS - the optimizer measured against what you actually did.
 *
 * The first version of this screen compared the optimizer against its OWN
 * rejected runner-up and reported it winning by +22. Both sides of that
 * comparison were hypothetical, and it pointed the opposite way from the
 * truth. This version scores its recommended squad against your real squad,
 * in points, with a do-nothing baseline alongside.
 *
 * Design rule: the screen must be willing to say the optimizer is losing,
 * in the largest number on the page, because right now it is. A dashboard
 * that can only report its own engine favourably is not evidence. */

/** Points gained over DOING NOTHING, for each choice, on a zero-centred
 * axis.
 *
 * The first version drew the three absolute scores as zero-anchored bars.
 * Measured live, that was useless: 100, 102 and 99 render as bars of 98%,
 * 100% and 97% of the track - visually identical, while the entire question
 * is the three-point difference between them. Absolute totals belong in
 * text, where they are exact.
 *
 * So the bar shows each choice minus the roll baseline. A choice worth
 * nothing sits exactly on the zero line, which is the clearest possible
 * rendering of "you spent a free transfer and gained nothing", and a choice
 * that lost points crosses to the left of it. */
function DeltaBars({ row, scale }: { row: LedgerRow; scale: number }) {
  const rows: { label: string; value: number | null; tone: string }[] = [
    { label: 'You', value: row.roll_points === null ? null : row.your_points - row.roll_points, tone: 'bg-pitch-green' },
    {
      label: 'Optimizer',
      value: row.optimizer_points === null || row.roll_points === null ? null : row.optimizer_points - row.roll_points,
      tone: 'bg-accent',
    },
  ]
  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const pct = r.value === null ? 0 : (Math.abs(r.value) / scale) * 50
        const negative = (r.value ?? 0) < 0
        return (
          <div key={r.label} className="flex items-center gap-3">
            <div className="w-20 shrink-0 text-[10px] uppercase tracking-wide text-text-faint">{r.label}</div>
            <div className="relative h-4 flex-1">
              {/* the do-nothing line - everything is read against this */}
              <div className="absolute left-1/2 top-0 h-full w-px bg-divider" />
              {r.value !== null && (
                <div
                  className={`absolute top-0.5 h-3 ${negative ? 'bg-alert-red' : r.tone}`}
                  style={negative
                    ? { right: '50%', width: `${pct}%` }
                    : { left: '50%', width: `${pct}%` }}
                />
              )}
            </div>
            <div className={`tabular w-14 text-right text-sm font-semibold ${
              r.value === null ? 'text-text-faint' : r.value < 0 ? 'text-alert-red' : 'text-text'
            }`}>
              {r.value === null ? '—' : `${r.value > 0 ? '+' : ''}${r.value}`}
            </div>
          </div>
        )
      })}
      <div className="flex items-center gap-3 pt-0.5">
        <div className="w-20 shrink-0" />
        <div className="flex-1 text-center text-[9px] uppercase tracking-wide text-text-faint">
          vs doing nothing ({row.roll_points ?? '—'} pts)
        </div>
        <div className="w-14" />
      </div>
    </div>
  )
}

function GameweekCard({ row, scale }: { row: LedgerRow; scale: number }) {
  const beat = row.delta_vs_you !== null && row.delta_vs_you > 0
  return (
    <div className="border-b border-divider py-6">
      <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <div className="tabular text-lg font-bold text-text">GW{row.event}</div>
        {row.your_chip_label && (
          <div className="border border-broadcast-gold px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-broadcast-gold">
            you played {row.your_chip_label}
          </div>
        )}
        <div className="text-xs text-text-muted">
          {row.optimizer_action
            ? <>it said <span className="font-semibold text-text">{row.optimizer_action}</span></>
            : <span className="text-text-faint">it said nothing</span>}
        </div>
        {row.delta_vs_you !== null && (
          <div className={`tabular ml-auto text-lg font-bold ${beat ? 'text-accent' : 'text-pitch-green'}`}>
            {row.delta_vs_you > 0 ? '+' : ''}{row.delta_vs_you}
            <span className="ml-1 text-[10px] font-normal uppercase tracking-wide text-text-faint">
              {beat ? 'it would have gained' : 'you were ahead'}
            </span>
          </div>
        )}
      </div>

      <DeltaBars row={row} scale={scale} />

      {/* The single most useful thing this screen can say. A transfer that
          scored exactly what doing nothing scored spent a free transfer for
          no return, and no win/loss framing would ever surface it. */}
      {row.worthless_vs_roll && row.optimizer_points !== null && (
        <div className="mt-3 border-l-2 border-alert-red pl-3 text-xs text-alert-red">
          Its transfer scored no more than rolling would have
          {row.roll_points !== null && row.optimizer_points === row.roll_points
            ? ` (${row.optimizer_points} either way)`
            : ''} — a free transfer spent for nothing.
        </div>
      )}
      {row.note && (
        <div className="mt-3 border-l-2 border-broadcast-gold pl-3 text-xs text-broadcast-gold">{row.note}</div>
      )}
    </div>
  )
}

export function ReceiptsScreen() {
  const state = useFetch(fetchReceiptsPayload, [], 60000)

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="border-b-2 border-divider px-10 py-10">
          <Skel className="h-2 w-40" />
          <Skel className="mt-4 h-16 w-72" />
        </div>
        <div className="px-10 py-8"><Skel className="h-40 w-full" /></div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="No record to show"
        description="The decision ledger could not be fetched, so the optimizer's track record is unknown right now. That is not the same as a clean sheet — treat its recommendations as unverified until this loads."
        message={state.error.message}
      />
    )
  }

  const data: ReceiptsPayload = state.data
  if (!data.has_record || !data.headline) {
    return (
      <div>
        <Masthead edition="The Receipts" title="Optimizer track record" />
        <div className="px-10 py-16 text-sm text-text-muted">{data.reason}</div>
      </div>
    )
  }

  const h = data.headline
  const rows = data.ledger ?? []
  // One shared scale across every gameweek, set by the largest swing in
  // either direction, so a +21 and a +2 are not drawn the same length.
  const scale = Math.max(
    ...rows.flatMap((r) => [
      r.roll_points === null ? 0 : Math.abs(r.your_points - r.roll_points),
      r.optimizer_points === null || r.roll_points === null ? 0 : Math.abs(r.optimizer_points - r.roll_points),
    ]),
    1,
  )
  const behind = (h.delta ?? 0) < 0

  return (
    <div>
      <Masthead edition="The Receipts" title="Its squad vs your squad" />

      {/* HERO - three totals over the SAME gameweeks. The delta is coloured
          by who is actually ahead, not by who we would like to be ahead. */}
      <div className="border-b-2 border-divider px-10 py-10">
        <div className="flex flex-wrap items-baseline gap-x-12 gap-y-5">
          <div>
            <div className="tabular text-6xl font-bold leading-none text-pitch-green">{h.your_total}</div>
            <div className="mt-2 text-[11px] uppercase tracking-wide text-text-faint">your squad</div>
          </div>
          <div>
            <div className="tabular text-6xl font-bold leading-none text-accent">{h.optimizer_total ?? '—'}</div>
            <div className="mt-2 text-[11px] uppercase tracking-wide text-text-faint">its squad</div>
          </div>
          <div>
            <div className="tabular text-4xl font-bold leading-none text-text-faint">{h.roll_total ?? '—'}</div>
            <div className="mt-2 text-[11px] uppercase tracking-wide text-text-faint">doing nothing</div>
          </div>
          {h.delta !== null && (
            <div className="ml-auto text-right">
              <div className={`tabular text-5xl font-bold leading-none ${behind ? 'text-alert-red' : 'text-accent'}`}>
                {h.delta > 0 ? '+' : ''}{h.delta}
              </div>
              <div className="mt-2 max-w-[16rem] text-[11px] uppercase tracking-wide text-text-faint">
                {behind ? 'points it would have COST you' : 'points it would have gained you'}
              </div>
            </div>
          )}
        </div>

        <div className="mt-6 text-xs text-text-muted">
          Over the {h.comparable_events} gameweek{h.comparable_events === 1 ? '' : 's'} where it actually
          produced a recommendation. Your full season total is {h.your_total_all_events}.
        </div>
      </div>

      {/* WHAT IS WRONG WITH IT - stated plainly, because these are the
          reasons the advice goes unused and they are all measurable. */}
      {data.flags && (
        <div className="border-b border-divider bg-raised/40 px-10 py-6">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-wide text-alert-red">
            Why this is not being followed
          </div>
          <ul className="space-y-2 text-xs text-text-muted">
            {data.flags.followed_none && (
              <li>· You have followed <span className="font-semibold text-text">none</span> of its {h.recommendations_logged} recommendations.</li>
            )}
            {data.flags.never_recommended_roll && (
              <li>· It has <span className="font-semibold text-text">never once</span> said roll. Every gameweek it proposed a transfer, whether or not one was worth making.</li>
            )}
            {data.flags.missing_recommendations > 0 && (
              <li>· {data.flags.missing_recommendations} gameweek{data.flags.missing_recommendations === 1 ? '' : 's'} produced no recommendation at all.</li>
            )}
            <li>· It only ever proposes a single transfer. It cannot express a chip, and cannot express doing nothing.</li>
          </ul>
        </div>
      )}

      <div className="px-10 py-4">
        {rows.map((r) => <GameweekCard key={r.event} row={r} scale={scale} />)}
      </div>

      {/* METHOD + the correction, on the same page as the numbers. */}
      <div className="border-t-2 border-divider bg-raised/40 px-10 py-8">
        <div className="mb-2 text-[11px] font-bold uppercase tracking-wide text-broadcast-gold">How this is measured</div>
        <div className="max-w-3xl text-xs leading-relaxed text-text-muted">{data.method}</div>
        {data.correction && (
          <>
            <div className="mb-2 mt-6 text-[11px] font-bold uppercase tracking-wide text-alert-red">Correction</div>
            <div className="max-w-3xl text-xs leading-relaxed text-text-muted">{data.correction}</div>
          </>
        )}
        {data.internal_consistency && data.internal_consistency.length > 0 && (
          <div className="mt-6">
            <div className="mb-2 text-[11px] font-bold uppercase tracking-wide text-text-faint">
              Internal consistency (a different question)
            </div>
            <div className="flex flex-wrap gap-6 text-xs text-text-muted">
              {data.internal_consistency.map((k) => (
                <div key={k.kind}>
                  <span className="font-semibold text-text">{k.kind}</span>{' '}
                  beat its own second choice {k.win_rate_pct}% of the time (n={k.n})
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
