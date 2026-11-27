import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** THE COUNCIL (`/api/council`, `models/council.py`): every source the system reads votes on this gameweek's moves and
 * armband - the model, the verdict, the football read, the manager's presser, the match analyst, the crowd, your eye and
 * the pre-flight checks. Green for, red against, grey abstains; hover a tile for its reason. It never overrides the plan:
 * it shows how much of what the system knows agrees with it, and who dissents. */
interface Vote { source: string; lean: number; why: string }
interface Move { kind: 'move'; source: string; label: string; votes: Vote[]; for: number; against: number }
interface CapOption { player_id: number; name: string; xp: number; votes: Vote[]; for: number; against: number }
interface Cap { kind: 'captain'; label: string; options: CapOption[] }
interface Payload { status: string; event?: number; decisions?: (Move | Cap)[]; sources?: string[] }

const NAME: Record<string, string> = { model: 'Model', verdict: 'Verdict', read: 'Football read', manager: 'Manager', analyst: 'Analyst', crowd: 'Crowd', eye: 'Your eye', checks: 'Checks' }

function Tiles({ votes }: { votes: Vote[] }) {
  return (
    <div className="grid grid-cols-8 gap-1">
      {votes.map((v) => (
        <div key={v.source} title={`${NAME[v.source] ?? v.source}: ${v.why}`}
          className={`cursor-help px-1 py-1.5 text-center text-[10.5px] font-black uppercase leading-tight ${v.lean > 0 ? 'bg-pitch-green text-pitch-green-ink' : v.lean < 0 ? 'bg-alert-red text-alert-red-ink' : 'bg-raised text-text-faint'}`}>
          {NAME[v.source] ?? v.source}
        </div>
      ))}
    </div>
  )
}

function Tally({ f, a, n }: { f: number; a: number; n: number }) {
  return (
    <div className="shrink-0 text-right">
      <div className="tabular font-display text-3xl font-black leading-none"><span className="text-pitch-green">{f}</span><span className="text-text-faint">–</span><span className="text-alert-red">{a}</span></div>
      <div className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-text-faint">of {n} for–against</div>
    </div>
  )
}

export function Council() {
  const st = useFetch(() => getJson<Payload>('/api/council'), [], 60000)
  if (st.status !== 'ready' || st.data.status !== 'ok' || !(st.data.decisions ?? []).length) return null
  const d = st.data
  const n = d.sources?.length ?? 8
  return (
    <section className="px-8 py-6">
      <h2 className="font-display text-text">The council · GW{d.event}</h2>
      <p className="voice mt-1 text-[15px] text-text-muted">Every source the system reads, voting on the call. Hover a tile for its reason.</p>
      <div className="mt-4 space-y-3">
        {d.decisions!.map((x, i) => x.kind === 'move' ? (
          <div key={i} className="flex items-center gap-4 border-2 border-ink bg-paper p-3">
            <div className="w-56 shrink-0">
              <div className="font-display text-xl font-black uppercase leading-none">{x.label}</div>
              <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">{x.source === 'plan' ? 'the plan' : "the pundit's call"}</div>
            </div>
            <div className="min-w-0 flex-1"><Tiles votes={x.votes} /></div>
            <Tally f={x.for} a={x.against} n={n} />
          </div>
        ) : (
          <div key={i} className="border-2 border-ink bg-paper p-3">
            <div className="mb-2 font-display text-xl font-black uppercase">Armband</div>
            <div className="space-y-2">
              {x.options.map((o, k) => {
                const best = Math.max(...x.options.map((q) => q.for - q.against))
                const pick = o.for - o.against === best
                return (
                <div key={o.player_id} className="flex items-center gap-4">
                  <div className="w-56 shrink-0 font-display text-lg font-black uppercase">
                    {o.name} <span className="tabular text-[13px] text-text-faint">{o.xp.toFixed(1)}</span>
                    {k === 0 && <span className="ml-2 bg-ink px-1 text-[10px] text-paper">plan</span>}
                    {pick && <span className="ml-1 bg-spot px-1 text-[10px] text-ink">council</span>}
                  </div>
                  <div className="min-w-0 flex-1"><Tiles votes={o.votes} /></div>
                  <Tally f={o.for} a={o.against} n={n} />
                </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
