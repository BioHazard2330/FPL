import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { Info } from '@/components/ui/Info'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** THE PUNDIT'S CALL: Claude's reasoned decision for the gameweek, made in a session from the week's dossier. A separate voice
 * beside the plan of record, scored on the real points in the ledger (`models/pundit_call.py`). */
interface Person { player_id: number; name: string; photo_code?: number | null; team_code: number | null; team_short?: string }
interface Move { out: Person; into: Person; why?: string; with_plan: boolean }
interface Row { event: number; pundit: number; plan: number; you: number }
interface Payload {
  status: string; event: number; made_at?: string; headline?: string; moves?: Move[]; hold?: { name: string; why: string }[]; captain?: Person & { why?: string }; vice?: Person
  differs?: string; watch?: string[]; ledger: { rows: Row[]; pundit?: number; plan?: number; you?: number }
  views?: { id: number; name: string; factor: number; from: number; through: number; reason: string }[]
  view_ledger?: { scored: number; helped: number; net: number; trust: number }
  suggested?: { key: string; kind: string; player_id: number; name: string; factor: number; from: number; through: number; reason: string }[]
}

/** Changes of situation the projections lag, found by the daemon (`models/situation_scan.py`); one click writes the view. */
function Suggested({ items }: { items: NonNullable<Payload['suggested']> }) {
  const [done, setDone] = useState<Record<string, string>>({})
  if (items.length === 0) return null
  const accept = async (key: string) => {
    setDone((d) => ({ ...d, [key]: '…' }))
    try {
      const res = await fetch(`/api/pundit-view?accept=${encodeURIComponent(key)}`, { method: 'POST', headers: { 'X-FPL-Refresh': '1' } })
      const body = await res.json()
      setDone((d) => ({ ...d, [key]: body.status === 'accepted' ? 'In the plan · rebuilding' : 'Gone' }))
    } catch {
      setDone((d) => ({ ...d, [key]: 'Failed' }))
    }
  }
  return (
    <div className="mt-3 border-t border-paper/25 pt-2">
      <div className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.14em] text-spot">
        Situation changes the numbers lag
        <Info label="Suggested views">Found each cycle for your squad and the plan&apos;s targets: a regular fit again whose cover is still listed to start (the start feed cannot have both), or an injury headline FPL has not flagged (regulars behind one played 60+ at 0.89x their record). Nothing changes until you accept; an accepted view is scored like any other.</Info>
      </div>
      <div className="mt-1 grid gap-2">
        {items.map((s) => (
          <div key={s.key} className="flex flex-wrap items-center gap-3 text-[13.5px]">
            <b className="font-display uppercase">{s.name}</b>
            <span className="tabular font-black text-alert-red">×{s.factor}</span>
            <span className="text-paper/60">GW{s.from}{s.through !== s.from ? `-${s.through}` : ''}</span>
            <span className="min-w-0 flex-1 text-paper/85">{s.reason}</span>
            {done[s.key] ? <span className="text-[12px] font-bold uppercase text-paper/70">{done[s.key]}</span> : (
              <button type="button" onClick={() => accept(s.key)} className="border-2 border-paper bg-paper px-2 py-0.5 text-[12px] font-black uppercase text-ink hover:bg-spot">Accept</button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function PunditCall() {
  const state = useFetch(() => getJson<Payload>('/api/punditcall'), [])
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  const b = d.ledger
  return (
    <section className="relative border-2 border-ink bg-ink p-5 text-paper shadow-[6px_6px_0_var(--spot)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.14em] text-paper/60">
            The pundit&apos;s call · GW{d.event}
            <Info label="The pundit's call">Claude&apos;s reasoned decision, made in a session from the week&apos;s evidence. It is separate from the plan and is only as fresh as that session: {d.made_at ? new Date(d.made_at).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : ''}. Check the news after it.</Info>
          </div>
          <div className="mt-1 font-display text-3xl font-black uppercase leading-tight">{d.headline}</div>
        </div>
        {b.rows.length > 0 && (
          <div className="tabular text-right font-display text-lg font-black uppercase" title="Points on the real scores, gameweeks with a call">
            Pundit {b.pundit} · Plan {b.plan} · You {b.you}
          </div>
        )}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(d.moves ?? []).map((m) => (
          <Link key={m.into.player_id} to={`/player/${m.into.player_id}`} className="flex gap-3 border-2 border-paper/30 bg-paper p-3 text-ink hover:border-spot">
            <PlayerPhoto code={m.into.photo_code} teamCode={m.into.team_code} className="h-16 w-12" />
            <div className="min-w-0">
              <div className="truncate font-display text-xl font-black uppercase leading-none">{m.into.name}</div>
              <div className="truncate text-[12px] text-text-faint line-through">{m.out.name}</div>
              <p className="mt-1 text-[13.5px] leading-snug">{m.why}</p>
            </div>
          </Link>
        ))}
        {d.captain && (
          <Link to={`/player/${d.captain.player_id}`} className="flex gap-3 border-2 border-spot bg-paper p-3 text-ink">
            <PlayerPhoto code={d.captain.photo_code} teamCode={d.captain.team_code} className="h-16 w-12" />
            <div className="min-w-0">
              <div className="flex items-center gap-2 truncate font-display text-xl font-black uppercase leading-none">{d.captain.name}<span className="bg-spot px-1 text-[13px] text-ink">C</span></div>
              <div className="text-[12px] text-text-faint">vice {d.vice?.name}</div>
              <p className="mt-1 text-[13.5px] leading-snug">{d.captain.why}</p>
            </div>
          </Link>
        )}
      </div>
      {(d.hold ?? []).length > 0 && (
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[13.5px]">
          {d.hold!.map((h) => <span key={h.name}><b className="font-display uppercase">Keep {h.name}:</b> {h.why}</span>)}
        </div>
      )}
      {(d.views ?? []).length > 0 && (
        <div className="mt-3 border-t border-paper/25 pt-2">
          <div className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.14em] text-paper/60">
            In the plan&apos;s numbers
            <Info label="Pundit views">Each view scales one player&apos;s projection for its gameweeks, for a change of situation the numbers cannot see, and every decision reads it: the plan, the eleven, the armband, the Decider. Scored afterwards against what he did{d.view_ledger && d.view_ledger.scored > 0 ? `: ${d.view_ledger.helped} of ${d.view_ledger.scored} player-weeks helped so far` : ''}; a run of wrong reads halves them.</Info>
          </div>
          <div className="mt-1 flex flex-wrap gap-2">
            {d.views!.map((v) => (
              <span key={v.id} className="border-2 border-paper/40 px-2 py-0.5 text-[13.5px]" title={v.reason}>
                <b className="font-display uppercase">{v.name}</b> <span className={`tabular font-black ${v.factor < 1 ? 'text-alert-red' : 'text-pitch-green'}`}>×{v.factor}</span> <span className="text-paper/60">GW{v.from}{v.through !== v.from ? `-${v.through}` : ''}</span> · {v.reason}
              </span>
            ))}
          </div>
        </div>
      )}
      <Suggested items={d.suggested ?? []} />
      {d.differs && <div className="mt-3 border-t border-paper/25 pt-2 text-[14px]"><b className="font-display uppercase text-spot">Against the plan:</b> {d.differs}</div>}
      {(d.watch ?? []).length > 0 && <div className="mt-2 text-[13.5px] text-paper/75"><b className="font-display uppercase">Changes my mind:</b> {d.watch!.join(' · ')}</div>}
    </section>
  )
}
