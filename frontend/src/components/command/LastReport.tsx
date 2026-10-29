import { Link } from 'react-router-dom'
import { fetchReviewPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

const signed = (v: number, d = 0) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`
const fmtRank = (r: number) => (r >= 1_000_000 ? `${(r / 1_000_000).toFixed(2)}m` : `${Math.round(r / 1_000)}k`)

/** The last finished gameweek in one line, linking to its report: score, against the top ten thousand, rank move, and what
 * the plan of record would have scored. */
export function LastReport() {
  const state = useFetch(() => fetchReviewPayload(null), [])
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  const moved = d.rank && d.previous_rank ? d.previous_rank - d.rank : null
  const field = d.top10k_field !== null ? d.points - d.top10k_field : null
  const items: [string, string, string?][] = [
    ['scored', String(d.points)],
    ...(field !== null ? [['on the top 10k', signed(field, 1), field >= 0 ? 'text-[#7fe0a6]' : 'text-[#ff8a7a]'] as [string, string, string]] : []),
    ...(moved !== null ? [['rank', `${moved >= 0 ? '▲' : '▼'} ${fmtRank(Math.abs(moved))}`, moved >= 0 ? 'text-[#7fe0a6]' : 'text-[#ff8a7a]'] as [string, string, string]] : []),
    ...(d.plan ? [['the plan would have', String(d.plan.score)] as [string, string]] : []),
    ...(d.captain ? [['armband', `${d.captain.captain.name} ${d.captain.captain.actual * d.captain.multiplier}`]] as [string, string][] : []),
  ]
  return (
    <Link to="/review" className="bare group flex flex-wrap items-center gap-x-7 gap-y-2 !border-2 !border-ink !bg-ink px-5 py-3 text-paper !shadow-[5px_5px_0_var(--spot)] transition-transform hover:-translate-y-0.5">
      <span className="bg-spot px-2 py-0.5 font-display text-[15px] font-black uppercase text-ink">GW{d.event} report</span>
      {items.map(([k, v, tone]) => (
        <span key={k} className="flex items-baseline gap-2">
          <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-paper/60">{k}</span>
          <span className={`tabular font-display text-2xl font-black ${tone ?? 'text-paper'}`}>{v}</span>
        </span>
      ))}
      <span className="ml-auto font-display text-[15px] font-black uppercase text-paper/80 group-hover:text-spot">read it →</span>
    </Link>
  )
}
