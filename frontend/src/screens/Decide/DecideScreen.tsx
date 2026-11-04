import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Info } from '@/components/ui/Info'
import { Masthead } from '@/components/shell/Masthead'
import { ScreenError, Skel } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchPlayersIndex, getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { PlayerIndexRow } from '@/lib/types'

/** THE DECIDER: three questions, one call each, how sure it is, then lock it so the question stays closed. A locked call is
 * reopened only by a tripwire (`models/decider.py`): a flag, an injury headline, a published sheet, the money, or the
 * runner-up pulling clear. When the two sides are within a coin flip the screen says so, because then more thinking buys
 * nothing. */

interface Person { player_id: number; name: string; photo_code?: number | null; team_code: number | null; team_short: string; xp?: number }
interface LockBlob { label: string; detail: Record<string, unknown> }
interface Option {
  key: string; source: 'roll' | 'plan' | 'you'; pairs: { out: Person; into: Person }[]; hits: number; gain: number
  starts: { event: number; started: boolean[] }[]; benched_weeks: number; beats_it: number | null; lock: LockBlob
}
interface TransferCard {
  options: Option[]; refused: { players: string[]; problem: string }[]; call: string; runner: string | null; chance: number
  tier: Tier; tie_break: boolean; horizon: number; free_transfers: number
}
interface PersonCard { call: number; runner: number | null; chance: number; tier: Tier; options: (Person & { lock: LockBlob })[] }
interface Wire { player_id: number; reason: string }
interface Call { id: number; kind: Kind; label: string; state: 'holding' | 'reopened' | 'made'; wires: Wire[]; chance: number | null }
interface Locks { calls: Call[]; record: { won: number; lost: number; edge: number; calls: { event: number; label: string; margin: number }[] } }
interface DecidePayload {
  status: string; reason?: string; event: number; sd: number
  cards: { transfer: TransferCard; armband: PersonCard | null; eleven: PersonCard | null }; locks: Locks
}
type Tier = 'coin_flip' | 'lean' | 'clear'
type Kind = 'transfer' | 'armband' | 'eleven'

const STAMP: Record<Tier, { text: string; tone: string }> = {
  coin_flip: { text: 'Coin flip', tone: 'bg-broadcast-gold text-ink' },
  lean: { text: 'Lean', tone: 'bg-paper text-ink' },
  clear: { text: 'Clear', tone: 'bg-pitch-green text-pitch-green-ink' },
}
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}`
const pct = (v: number) => `${Math.round(v * 100)}%`

function Tug({ left, right, chance }: { left: string; right: string; chance: number }) {
  return (
    <div>
      <div className="flex h-9 overflow-hidden border-2 border-ink">
        <div className="flex items-center bg-ink px-2 font-display text-lg font-black text-paper transition-all duration-500" style={{ width: `${chance * 100}%` }}>{pct(chance)}</div>
        <div className="flex flex-1 items-center justify-end bg-paper px-2 font-display text-lg font-black text-text-faint">{100 - Math.round(chance * 100)}%</div>
      </div>
      <div className="mt-1 flex justify-between text-[12px] font-bold uppercase tracking-[0.08em]">
        <span className="truncate text-text">{left}</span>
        <span className="truncate text-text-faint">{right}</span>
      </div>
    </div>
  )
}

function Verdict({ title, tier, chance, left, right, children, tip }: { title: string; tier: Tier; chance: number; left: string; right: string; children: React.ReactNode; tip: string }) {
  const stamp = STAMP[tier]
  return (
    <section className="relative border-2 border-ink bg-paper p-5 shadow-[6px_6px_0_var(--ink)]">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-text">{title}<Info label={title}>{tip}</Info></h2>
        <span className={`-rotate-2 border-2 border-ink px-3 py-0.5 font-display text-[15px] font-black uppercase ${stamp.tone}`}>{stamp.text}</span>
      </div>
      <div className="mt-3"><Tug left={left} right={right} chance={chance} /></div>
      <div className="mt-4">{children}</div>
    </section>
  )
}

function LockButton({ event, kind, blob, onDone, primary }: { event: number; kind: Kind; blob: LockBlob; onDone: () => void; primary?: boolean }) {
  const [busy, setBusy] = useState(false)
  return (
    <button
      type="button"
      disabled={busy}
      onClick={async () => {
        setBusy(true)
        await fetch('/api/decide/lock', { method: 'POST', headers: { 'X-FPL-Refresh': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ event, kind, ...blob }) })
        onDone()
      }}
      className={primary
        ? 'border-2 border-ink bg-spot px-4 py-1.5 font-display text-[15px] font-black uppercase text-ink shadow-[3px_3px_0_var(--ink)] hover:-translate-y-px disabled:opacity-50'
        : 'border-2 border-ink/40 px-2 py-0.5 text-[12px] font-bold uppercase text-text-muted hover:border-ink hover:text-text disabled:opacity-50'}
    >
      {busy ? 'Locking…' : primary ? 'Lock it' : 'Lock this instead'}
    </button>
  )
}

function Settled({ call, onDone }: { call: Call; onDone: () => void }) {
  const open = call.state === 'reopened'
  return (
    <div className={`flex flex-wrap items-center gap-3 border-2 border-ink px-3 py-2 ${open ? 'bg-alert-red text-alert-red-ink' : 'bg-ink text-paper'}`}>
      <span className="font-display text-[15px] font-black uppercase">{open ? 'Reopened' : call.state === 'made' ? 'Done' : 'Locked'}</span>
      <span className="min-w-0 flex-1 text-[13.5px] font-semibold">{open ? call.wires.map((w) => w.reason).join(' · ') : call.label}</span>
      <button
        type="button"
        className="text-[12px] font-bold uppercase underline opacity-80 hover:opacity-100"
        onClick={async () => {
          await fetch(`/api/decide/lock?release=${call.id}`, { method: 'POST', headers: { 'X-FPL-Refresh': '1' } })
          onDone()
        }}
      >
        Let it go
      </button>
    </div>
  )
}

function StartDots({ o }: { o: Option }) {
  if (!o.pairs.length) return null
  return (
    <div className="flex gap-1" title={`${o.benched_weeks} benched player-weeks in ${o.starts.length} gameweeks`}>
      {o.starts.map((s) => {
        const on = s.started.filter(Boolean).length / s.started.length
        return <span key={s.event} className={`size-3 border-2 border-ink ${on === 1 ? 'bg-pitch-green' : on > 0 ? 'bg-broadcast-gold' : 'bg-transparent'}`} title={`GW${s.event}`} />
      })}
    </div>
  )
}

function OptionCard({ o, chosen, event, onDone }: { o: Option; chosen: boolean; event: number; onDone: () => void }) {
  const faces = o.pairs.length ? o.pairs : []
  return (
    <div className={`flex min-w-0 flex-col justify-between gap-3 border-2 border-ink p-3 ${chosen ? 'bg-paper shadow-[4px_4px_0_var(--spot)]' : 'bg-paper/60'}`}>
      <div>
        <div className="flex items-start justify-between gap-2">
          <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">{o.source === 'plan' ? `the plan · ${o.pairs.length} moves` : o.source === 'roll' ? 'do nothing' : 'your idea'}</span>
          <span className={`tabular font-display text-2xl font-black leading-none ${o.gain >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(o.gain)}</span>
        </div>
        {faces.length === 0 && <div className="mt-2 font-display text-lg font-black uppercase text-text">Roll</div>}
        {faces.map((p) => (
          <div key={p.into.player_id} className="mt-2 flex items-center gap-2">
            <PlayerPhoto code={p.into.photo_code} teamCode={p.into.team_code} className="h-10 w-8" />
            <div className="min-w-0">
              <div className="truncate font-display text-[16px] font-black uppercase leading-tight text-text">{p.into.name}</div>
              <div className="truncate text-[12px] text-text-faint line-through">{p.out.name}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between gap-2">
        <StartDots o={o} />
        {!chosen && <LockButton event={event} kind="transfer" blob={o.lock} onDone={onDone} />}
      </div>
    </div>
  )
}

function IdeaBar({ ideas, setIdeas }: { ideas: number[][]; setIdeas: (v: number[][]) => void }) {
  const index = useFetch(fetchPlayersIndex, [])
  const [q, setQ] = useState('')
  const [target, setTarget] = useState<number | null>(null)
  const players: PlayerIndexRow[] = useMemo(() => (index.status === 'ready' ? index.data.players : []), [index])
  const byId = useMemo(() => new Map(players.map((p) => [p.player_id, p])), [players])
  const hits = q.length >= 2 ? players.filter((p) => p.name.toLowerCase().includes(q.toLowerCase())).slice(0, 6) : []
  const add = (id: number) => {
    setQ('')
    if (target !== null && ideas[target]) setIdeas(ideas.map((idea, i) => (i === target ? [...idea, id] : idea)))
    else if (ideas.length < 4) setIdeas([...ideas, [id]])
    setTarget(null)
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      {ideas.map((idea, i) => (
        <span key={i} className={`flex items-center gap-1 border-2 border-ink px-2 py-1 ${target === i ? 'bg-spot' : 'bg-paper'}`}>
          <span className="font-display text-[14px] font-black uppercase text-text">{idea.map((id) => byId.get(id)?.name ?? id).join(' + ')}</span>
          <button type="button" className="px-1 text-[13px] font-bold text-text-muted hover:text-text" title="Add another player to this idea" onClick={() => setTarget(target === i ? null : i)}>+</button>
          <button type="button" className="px-1 text-[13px] font-bold text-text-muted hover:text-alert-red" title="Remove" onClick={() => setIdeas(ideas.filter((_, n) => n !== i))}>×</button>
        </span>
      ))}
      <div className="relative">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={target !== null ? 'Add to this idea…' : ideas.length ? 'Another idea…' : 'Who are you thinking of?'}
          className="w-56 border-2 border-ink bg-paper px-2 py-1 text-[14px] text-text placeholder:text-text-faint"
        />
        {hits.length > 0 && (
          <div className="absolute z-20 mt-1 w-64 border-2 border-ink bg-paper shadow-[4px_4px_0_var(--ink)]">
            {hits.map((p) => (
              <button key={p.player_id} type="button" onClick={() => add(p.player_id)} className="flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-raised">
                <PlayerPhoto code={p.photo_code} teamCode={p.team_code} className="h-7 w-6" />
                <span className="flex-1 truncate text-[13.5px] font-bold text-text">{p.name}</span>
                <span className="text-[12px] text-text-faint">{p.team_short} £{p.price?.toFixed(1)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function TransferSection({ d, ideas, setIdeas, onDone, locked }: { d: DecidePayload; ideas: number[][]; setIdeas: (v: number[][]) => void; onDone: () => void; locked?: Call }) {
  const t = d.cards.transfer
  const call = t.options.find((o) => o.key === t.call)!
  const runner = t.options.find((o) => o.key === t.runner)
  const plan = t.options.find((o) => o.source === 'plan')
  const others = t.options.filter((o) => o !== call && !(o.source === 'plan' && call.source !== 'plan'))
  return (
    <Verdict
      title="Transfers" tier={t.tier} chance={t.chance} left={call.lock.label} right={runner?.lock.label ?? ''}
      tip={`Each option keeps the same fifteen for ${t.horizon} gameweeks, best eleven each week, hits charged. The percentage is the chance it outscores the runner-up over those weeks, from a measured ${d.sd} points of noise a player a week; the one-week version held up on GW8-9, the ${t.horizon}-week version assumes weeks are independent. Dots show if the new player makes your eleven each week.`}
    >
      <IdeaBar ideas={ideas} setIdeas={setIdeas} />
      {t.refused.map((r) => <div key={r.players.join()} className="mt-2 text-[13px] font-semibold text-alert-red">{r.players.join(' + ')}: {r.problem}</div>)}
      {t.tie_break && <div className="mt-2 text-[13px] font-bold text-text">Too close on points. This one sits on your bench less.</div>}
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <OptionCard o={call} chosen event={d.event} onDone={onDone} />
        {others.map((o) => <OptionCard key={o.key} o={o} chosen={false} event={d.event} onDone={onDone} />)}
      </div>
      {plan && call.source !== 'plan' && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t-2 border-ink/15 pt-2 text-[13px] text-text-muted">
          <span>The plan, {plan.pairs.length} moves: <b className="tabular text-text">{signed(plan.gain)}</b> ({plan.pairs.map((p) => p.into.name).join(', ')}). You have {t.free_transfers} free: use + to add players to an idea.</span>
          <LockButton event={d.event} kind="transfer" blob={plan.lock} onDone={onDone} />
        </div>
      )}
      <div className="mt-4">{locked ? <Settled call={locked} onDone={onDone} /> : <LockButton event={d.event} kind="transfer" blob={call.lock} onDone={onDone} primary />}</div>
    </Verdict>
  )
}

function PersonSection({ title, kind, card, d, onDone, locked, tip, doubled }: { title: string; kind: Kind; card: PersonCard; d: DecidePayload; onDone: () => void; locked?: Call; tip: string; doubled?: boolean }) {
  const chosen = card.options.find((o) => o.player_id === card.call)!
  const runner = card.options.find((o) => o.player_id === card.runner)
  return (
    <Verdict title={title} tier={card.tier} chance={card.chance} left={chosen.name} right={runner?.name ?? ''} tip={tip}>
      <div className="flex items-stretch gap-3">
        {card.options.map((o) => (
          <div key={o.player_id} className={`flex min-w-0 flex-1 flex-col items-center gap-1 border-2 border-ink p-2 ${o.player_id === card.call ? 'bg-paper shadow-[4px_4px_0_var(--spot)]' : 'bg-paper/60'}`}>
            <PlayerPhoto code={o.photo_code} teamCode={o.team_code} className="h-16 w-12" />
            <div className="w-full truncate text-center font-display text-[15px] font-black uppercase text-text">{o.name}</div>
            <div className="tabular font-display text-xl font-black text-text">{((o.xp ?? 0) * (doubled ? 2 : 1)).toFixed(1)}</div>
            {o.player_id !== card.call && <LockButton event={d.event} kind={kind} blob={o.lock} onDone={onDone} />}
          </div>
        ))}
      </div>
      <div className="mt-4">{locked ? <Settled call={locked} onDone={onDone} /> : <LockButton event={d.event} kind={kind} blob={chosen.lock} onDone={onDone} primary />}</div>
    </Verdict>
  )
}

export function DecideScreen() {
  const [params, setParams] = useSearchParams()
  const [tick, setTick] = useState(0)
  const raw = params.get('ideas') ?? ''
  const ideas = useMemo(() => raw.split(',').filter(Boolean).map((chunk) => chunk.split('+').map(Number)), [raw])
  const state = useFetch(() => getJson<DecidePayload>(`/api/decide?ideas=${encodeURIComponent(raw)}`), [raw, tick])
  const setIdeas = (v: number[][]) => setParams(v.length ? { ideas: v.map((i) => i.join('+')).join(',') } : {}, { replace: true })
  const refresh = () => setTick((n) => n + 1)

  if (state.status === 'loading') return <div className="space-y-4 p-6"><Skel className="h-48 w-full" /><Skel className="h-48 w-full" /></div>
  if (state.status === 'error') return <ScreenError title="The Decider is unavailable" description="This week's questions could not be scored." message={state.error.message} />
  const d = state.data
  if (d.status !== 'ok') return <div className="p-6 text-[15px] font-semibold text-text">{d.reason ?? 'No synced squad yet.'}</div>
  const calls = d.locks.calls
  const of = (k: Kind) => calls.find((c) => c.kind === k)
  const total = [d.cards.transfer, d.cards.armband, d.cards.eleven].filter(Boolean).length
  const held = calls.filter((c) => c.state !== 'reopened').length
  const rec = d.locks.record

  return (
    <div className="space-y-6 pb-10">
      <Masthead right={<span>nothing is sent to FPL</span>} />
      <div className="bare flex flex-wrap items-end justify-between gap-4 px-1">
        <div>
          <div className="font-display text-5xl font-black uppercase leading-none text-text">GW{d.event}: {held} of {total} settled</div>
          <div className="mt-2 flex gap-1.5">
            {Array.from({ length: total }, (_, i) => <span key={i} className={`h-2.5 w-12 border-2 border-ink ${i < held ? 'bg-spot' : 'bg-transparent'}`} />)}
          </div>
        </div>
        {rec.won + rec.lost > 0 && (
          <div className="text-right">
            <div className="tabular font-display text-3xl font-black text-text">{rec.won}–{rec.lost}</div>
            <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">your locks vs the runner-up · {signed(rec.edge)} pts</div>
          </div>
        )}
      </div>
      <div className="bare"><TransferSection d={d} ideas={ideas} setIdeas={setIdeas} onDone={refresh} locked={of('transfer')} /></div>
      <div className="bare grid gap-6 lg:grid-cols-2">
        {d.cards.armband && (
          <PersonSection title="Armband" kind="armband" card={d.cards.armband} d={d} onDone={refresh} locked={of('armband')} doubled
            tip={`Points shown are doubled. The percentage is the chance your pick outscores the next option this gameweek, from ${d.sd} points of noise a player.`} />
        )}
        {d.cards.eleven && (
          <PersonSection title="Last place in the eleven" kind="eleven" card={d.cards.eleven} d={d} onDone={refresh} locked={of('eleven')}
            tip="Your lowest starter against your best substitute who could legally replace him, this gameweek." />
        )}
      </div>
    </div>
  )
}
