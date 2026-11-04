import { Link } from 'react-router-dom'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** The calls locked on the Decider: quiet while they hold, loud only when a tripwire has reopened one. */
interface Call { id: number; label: string; state: 'holding' | 'reopened' | 'made'; wires: { reason: string }[] }

export function LockedCalls() {
  const state = useFetch(() => getJson<{ calls: Call[] }>('/api/locks'), [], 60000)
  const calls = state.status === 'ready' ? state.data.calls : []
  const open = calls.filter((c) => c.state === 'reopened')
  return (
    <Link to="/decide" className={`bare flex flex-wrap items-center gap-x-5 gap-y-1 border-2 border-ink px-5 py-3 shadow-[4px_4px_0_var(--ink)] hover:opacity-90 ${open.length ? 'bg-alert-red text-alert-red-ink' : 'bg-paper text-text'}`}>
      <span className="font-display text-[14px] font-black uppercase tracking-[0.08em]">
        {open.length ? `${open.length} call reopened` : calls.length ? 'Settled' : 'Decide'}
      </span>
      {open.length > 0
        ? <span className="text-[13.5px] font-semibold">{open[0].wires[0]?.reason}</span>
        : calls.length > 0
          ? calls.map((c) => <span key={c.id} className="text-[14px] font-bold">{c.label}</span>)
          : <span className="text-[14px] font-semibold text-text-muted">Name your ideas, get one call, lock it</span>}
    </Link>
  )
}
