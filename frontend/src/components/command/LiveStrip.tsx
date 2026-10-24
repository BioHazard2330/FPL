import { Link } from 'react-router-dom'
import { fetchLiveCone } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** GAMEWEEK IN PROGRESS, in one line: your points now, where the simulation says they end, and how that compares with the
 * average manager. The full picture (the spread, who can still move it, every match) is on Live. Renders nothing outside a
 * gameweek in play. */
export function LiveStrip() {
  const state = useFetch(fetchLiveCone, [], 30000)
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  if (!d.forecast || !d.edge) return null
  const movers = (d.players ?? []).filter((p) => p.remaining_mean > 0.3).length
  return (
    <Link
      to="/live"
      className="flex flex-wrap items-center gap-x-8 gap-y-2 rounded-xl border border-alert-red/30 bg-alert-red/5 px-6 py-4 transition-colors hover:bg-alert-red/10"
    >
      <span className="flex items-center gap-2 text-[14px] font-semibold text-alert-red">
        <span className="size-2 animate-pulse-live rounded-full bg-alert-red" />
        GW{d.event} in progress
      </span>
      <span className="text-[14px] text-text-muted">
        <span className="tabular font-display text-2xl font-semibold text-text">{d.now?.toFixed(0)}</span> points now
      </span>
      <span className="text-[14px] text-text-muted">
        likely finish <span className="tabular font-semibold text-text">{d.forecast.p50.toFixed(0)}</span>{' '}
        <span className="tabular text-text-faint">({d.forecast.p10.toFixed(0)} to {d.forecast.p90.toFixed(0)})</span> against {d.field_forecast?.toFixed(0)} for the average manager
      </span>
      <span className="text-[14px] text-text-muted">
        <span className="tabular font-semibold text-text">{Math.round(d.edge.p_beat * 100)}%</span> to finish ahead of them
        {movers > 0 && <span className="text-text-faint"> &middot; {movers} of your eleven still to play</span>}
      </span>
      <span className="ml-auto text-[13px] font-medium text-text-faint">Open Live &rarr;</span>
    </Link>
  )
}
