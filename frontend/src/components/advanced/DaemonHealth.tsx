import { getJson } from '@/lib/api'
import { Info } from '@/components/ui/Info'
import { useFetch } from '@/lib/useFetch'

/** THE DAEMON: the self-check as ticks and the last cycles as bars against the task's 10-minute limit, with where the
 * latest cycle spent its time and any step failing cycle after cycle (`scheduler/run_ledger.py`, `models/self_check.py`). */
interface Check { name: string; ok: boolean; detail: string; level: 'act' | 'look' }
interface Run { id: number; started_at: string; seconds: number | null; status: string; errors: number }
interface Step { text: string; level: string; seconds: number }
interface Payload { status: string; checks: Check[]; failing: string[]; limit_seconds: number; runs: Run[]; latest: (Run & { steps: Step[] }) | null }

const RUN_TONE: Record<string, string> = { ok: 'bg-pitch-green', errors: 'bg-broadcast-gold', failed: 'bg-alert-red', killed: 'bg-alert-red' }
const secs = (s: number | null) => (s === null ? '—' : s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`)

export function DaemonHealth() {
  const state = useFetch(() => getJson<Payload>('/api/daemon'), [], 60000)
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  const bad = d.checks.filter((c) => !c.ok)
  const good = d.checks.filter((c) => c.ok)
  const allOk = bad.length === 0 && d.failing.length === 0
  return (
    <section className="slab px-6 py-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="font-display text-text">The daemon</h2>
          <Info label="What this is">Runs after every background cycle: each check compares stored state with itself and the calendar. Bars are the last cycles against the task's 10-minute limit.</Info>
        </div>
        <span className={`px-2 py-0.5 font-display text-[14px] font-black uppercase ${allOk ? 'bg-pitch-green text-paper' : bad.some((c) => c.level === 'act') ? 'bg-alert-red text-alert-red-ink' : 'bg-broadcast-gold text-ink'}`}>
          {allOk ? 'all clear' : `${bad.length + d.failing.length} to look at`}
        </span>
      </div>

      {bad.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {bad.map((c) => (
            <div key={c.name} className="flex items-baseline gap-2.5">
              <span className={`font-black ${c.level === 'act' ? 'text-alert-red' : 'text-broadcast-gold'}`}>✗</span>
              <span className="text-[14.5px] font-semibold text-text">{c.name}</span>
              <span className="text-[13px] text-text-muted">{c.detail}</span>
            </div>
          ))}
        </div>
      )}
      {d.failing.map((f) => (
        <div key={f} className="mt-1.5 flex items-baseline gap-2.5"><span className="font-black text-alert-red">✗</span><span className="text-[14px] text-text">failing every cycle: {f}</span></div>
      ))}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {good.map((c) => (
          <span key={c.name} title={c.detail} className="inline-flex items-center gap-1 border-2 border-pitch-green/50 bg-pitch-green/10 px-2 py-0.5 text-[12px] font-semibold text-text"><span className="font-black text-pitch-green">✓</span>{c.name}</span>
        ))}
      </div>

      {d.runs.length > 0 && (
        <div className="mt-5 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <div>
            <div className="relative flex h-28 items-end gap-1 border-b-2 border-ink">
              <div className="absolute inset-x-0 top-0 border-t-2 border-dashed border-alert-red/60"><span className="absolute -top-4 right-0 text-[10px] font-bold uppercase text-alert-red">10 min limit</span></div>
              {d.runs.map((r) => (
                <div key={r.id} title={`${new Date(r.started_at).toLocaleString()} · ${secs(r.seconds)} · ${r.status}${r.errors ? ` · ${r.errors} errors` : ''}`}
                  className={`min-w-0 max-w-8 flex-1 ${RUN_TONE[r.status] ?? 'bg-ink/40'}`} style={{ height: `${Math.max(3, Math.min(100, ((r.seconds ?? 0) / d.limit_seconds) * 100))}%` }} />
              ))}
            </div>
            <div className="mt-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">last {d.runs.length} cycles · green clean · gold a step failed · red cut off</div>
          </div>
          {d.latest && (
            <div className="space-y-1">
              {d.latest.steps.slice(0, 6).map((s, i) => (
                <div key={i} className="grid grid-cols-[3.4rem_minmax(0,1fr)] items-baseline gap-2 text-[12.5px]">
                  <span className="tabular text-right font-display font-black text-text">{secs(s.seconds)}</span>
                  <span className={`truncate ${s.level === 'ERROR' ? 'font-semibold text-alert-red' : 'text-text-muted'}`} title={s.text}>{s.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
