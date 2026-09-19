import { Link } from 'react-router-dom'
import { fetchReceiptsPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** TRACK RECORD - the recommendation's own scoreboard, directly under the
 * recommendation.
 *
 * COMMAND is where decisions get made, and until this existed it showed a
 * verdict with no way to know whether the engine behind it had ever been
 * right. The full ledger lives on RECEIPTS; this is the one line of it that
 * belongs next to the verdict: its squad against yours, in points, over the
 * gameweeks where it actually said something.
 *
 * Reads the same `/api/receipts` payload RECEIPTS does - never a second
 * computation - and renders nothing at all when there is no settled record,
 * rather than a placeholder that implies a clean sheet. */
export function TrackRecordStrip() {
  const state = useFetch(fetchReceiptsPayload, [], 120000)
  if (state.status !== 'ready' || !state.data.has_record || !state.data.headline) return null

  const h = state.data.headline
  const f = state.data.flags
  if (h.delta === null || h.optimizer_total === null || h.your_total === null) return null
  const behind = h.delta < 0

  return (
    <Link
      to="/receipts"
      className="group block border-t border-divider bg-raised/40 px-10 py-4 transition-colors hover:bg-raised/70"
    >
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">
          Its record against you
        </div>
        <div className="flex items-baseline gap-2">
          <span className="tabular text-2xl font-bold text-pitch-green">{h.your_total}</span>
          <span className="text-[10px] uppercase tracking-wide text-text-faint">yours</span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="tabular text-2xl font-bold text-broadcast-blue">{h.optimizer_total}</span>
          <span className="text-[10px] uppercase tracking-wide text-text-faint">its</span>
        </div>
        <div className={`tabular text-2xl font-bold ${behind ? 'text-alert-red' : 'text-broadcast-blue'}`}>
          {h.delta > 0 ? '+' : ''}{h.delta}
          <span className="ml-1.5 text-[10px] font-normal uppercase tracking-wide text-text-faint">
            over {h.comparable_events} GW
          </span>
        </div>
        {f?.never_recommended_roll && (
          <div className="text-xs text-alert-red">it had never said roll</div>
        )}
        {f?.followed_none && (
          <div className="text-xs text-text-muted">you have followed none of its {h.recommendations_logged} calls</div>
        )}
        <div className="ml-auto text-[10px] font-bold uppercase tracking-wide text-text-faint group-hover:text-text">
          every call, scored →
        </div>
      </div>
    </Link>
  )
}
