import { useEffect, useState } from 'react'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** CHIP DRAFTS: the squad a wildcard or free hit still in hand would build in a chosen gameweek, solved by the week plan's
 * own MILP with that week's moves free, against the same solve without the chip. The wildcard ladder (a background job,
 * refreshed daily) is the draft's gain in every week of the window still ahead, so the best week can be read off. */
interface LadderRow { event: number; gain: number; total: number; moves: number; proven: boolean }
interface Overview { status: string; ladder: { computed_at: string; ladder: LadderRow[] } | null; events: Record<string, number[]> }
interface DraftPlayer {
  player_id: number; name: string; photo_code: number | null; team_code: number | null; team_short: string
  position: string; price: number | null; starting: boolean; new: boolean
}
interface Draft {
  status: string; chip?: string; event?: number; horizon?: number; squad?: DraftPlayer[]; out?: DraftPlayer[]
  captain_id?: number | null; total?: number; without?: number; gain?: number; proven?: boolean
}

const CHIPS = [{ key: 'wildcard', label: 'Wildcard' }, { key: 'freehit', label: 'Free hit' }]
const ROWS = ['GKP', 'DEF', 'MID', 'FWD']
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}`

function age(iso: string) {
  const h = (Date.now() - new Date(iso).getTime()) / 3.6e6
  return h < 1 ? 'under an hour ago' : h < 48 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)} days ago`
}

function Ladder({ rows, pick, chosen }: { rows: LadderRow[]; pick: (e: number) => void; chosen: number | null }) {
  const top = Math.max(1, ...rows.map((r) => r.gain))
  const best = rows.reduce<LadderRow | null>((b, r) => (!b || r.gain > b.gain ? r : b), null)
  return (
    <div className="flex h-44 items-end gap-2">
      {rows.map((r) => {
        const on = r.event === chosen
        const isBest = r.event === best?.event
        return (
          <button key={r.event} type="button" onClick={() => pick(r.event)} className="group flex h-full flex-1 flex-col items-stretch justify-end"
            title={`Wildcard in GW${r.event}: ${signed(r.gain)} over its horizon, ${r.moves} players changed`}>
            <div className={`tabular text-center font-display text-[15px] font-black ${isBest ? 'text-spot' : 'text-text'}`}>{signed(r.gain)}</div>
            <div className={`chipdraft-bar relative mt-1 border-2 border-ink transition-[filter] group-hover:brightness-110 ${isBest ? 'bg-spot' : on ? 'bg-broadcast-blue' : 'bg-broadcast-blue/45'}`}
              style={{ height: `${Math.max(4, (Math.max(0, r.gain) / top) * 100)}%`, boxShadow: on ? '4px 4px 0 var(--ink)' : undefined }} />
            <div className={`mt-1 text-center font-display text-[13px] font-black ${on ? 'text-text' : 'text-text-muted'}`}>GW{r.event}</div>
          </button>
        )
      })}
    </div>
  )
}

/** What the ladder says in words: the best week, and whether the weeks differ by more than a projection weeks out can tell
 * apart (a few points over six gameweeks is inside it). */
function LadderNote({ rows }: { rows: LadderRow[] }) {
  if (rows.length < 2) return null
  const gains = rows.map((r) => r.gain)
  const best = rows.reduce((b, r) => (r.gain > b.gain ? r : b))
  const spread = Math.max(...gains) - Math.min(...gains)
  return (
    <div className="mt-4 border-t-2 border-ink/15 pt-3 text-[13px] text-text-muted">
      Best week GW{best.event} ({signed(best.gain)}).{' '}
      {spread < 6
        ? `Every week is within ${spread.toFixed(1)} points of the others over six gameweeks: on today's fixtures the week matters less than playing it, so hold it for a blank, a double or an injury crisis.`
        : `The weeks differ by ${spread.toFixed(1)} points: the timing matters.`}
    </div>
  )
}

function Card({ p, captain }: { p: DraftPlayer; captain: boolean }) {
  return (
    <div className={`relative flex w-[7.2rem] flex-col items-center border-2 border-ink px-1 pb-1.5 pt-2 ${p.starting ? 'bg-paper' : 'bg-paper/55 opacity-75'} ${p.new ? 'shadow-[4px_4px_0_var(--spot)]' : 'shadow-[3px_3px_0_var(--ink)]'}`}>
      {p.new && <span className="absolute -top-2.5 left-1 bg-spot px-1 font-display text-[10px] font-black uppercase text-ink">in</span>}
      {captain && <span className="absolute -top-2.5 right-1 rounded-full border-2 border-ink bg-broadcast-gold px-1 font-display text-[10px] font-black text-ink">C</span>}
      <PlayerPhoto code={p.photo_code} teamCode={p.team_code} className="h-12 w-9" muted={!p.starting} />
      <div className="mt-1 w-full truncate text-center text-[12.5px] font-bold text-text">{p.name}</div>
      <div className="text-[10.5px] text-text-faint">{p.team_short}{p.price !== null ? ` · £${p.price.toFixed(1)}` : ''}</div>
    </div>
  )
}

function DraftView({ d }: { d: Draft }) {
  const squad = d.squad ?? []
  const xi = squad.filter((p) => p.starting)
  const bench = squad.filter((p) => !p.starting)
  const gain = d.gain ?? 0
  return (
    <div className="chipdraft-in mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_17rem]">
      <div className="relative overflow-hidden border-2 border-ink bg-[linear-gradient(180deg,#2f6b3a,#24572f)] px-4 py-5 shadow-[6px_6px_0_var(--ink)]">
        <div className="pointer-events-none absolute inset-0 bg-[repeating-linear-gradient(180deg,transparent_0_44px,rgba(255,255,255,0.05)_44px_88px)]" />
        <div className="pointer-events-none absolute left-1/2 top-1/2 h-28 w-28 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white/25" />
        <div className="pointer-events-none absolute inset-x-0 top-1/2 h-0.5 bg-white/25" />
        <div className="relative space-y-4">
          {ROWS.map((pos) => (
            <div key={pos} className="flex flex-wrap justify-center gap-3">
              {xi.filter((p) => p.position === pos).map((p) => <Card key={p.player_id} p={p} captain={p.player_id === d.captain_id} />)}
            </div>
          ))}
          <div className="flex flex-wrap justify-center gap-3 border-t-2 border-dashed border-white/30 pt-4">
            {bench.map((p) => <Card key={p.player_id} p={p} captain={false} />)}
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-4">
        <div className="border-2 border-ink bg-paper p-4 shadow-[4px_4px_0_var(--ink)]">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">the chip adds</div>
          <div className={`tabular font-display text-5xl font-black ${gain >= 4 ? 'text-pitch-green' : gain >= 0 ? 'text-text' : 'text-alert-red'}`}>{signed(gain)}</div>
          <div className="text-[12px] text-text-muted">
            over {d.horizon} gameweek{d.horizon === 1 ? '' : 's'}: {d.total?.toFixed(1)} with it, {d.without?.toFixed(1)} without
            {d.chip === 'freehit' ? ' (holding the squad)' : ' (one free transfer a week, hits charged)'}
          </div>
        </div>
        <div className="border-2 border-ink bg-paper p-4">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">{d.out?.length ?? 0} of your fifteen go</div>
          <div className="mt-2 space-y-1.5">
            {(d.out ?? []).map((p) => (
              <div key={p.player_id} className="flex items-center gap-2">
                <PlayerPhoto code={p.photo_code} teamCode={p.team_code} className="h-8 w-6" muted />
                <span className="truncate text-[13px] text-text-muted line-through decoration-alert-red/60">{p.name}</span>
                <span className="ml-auto text-[11px] text-text-faint">{p.position}</span>
              </div>
            ))}
            {!d.out?.length && <div className="text-[13px] text-text-muted">None: the draft keeps your squad.</div>}
          </div>
        </div>
        <div className="text-[11.5px] leading-snug text-text-faint">
          Today's prices and the plan's projections, evidence shrink and eye gate. A draft weeks ahead reads fixtures and current
          form; injuries and price moves before then change it.{d.proven === false ? ' Solver stopped at its time limit: best found, not proven best.' : ''}
        </div>
      </div>
    </div>
  )
}

export function ChipDraft() {
  const overview = useFetch(() => getJson<Overview>('/api/chipdraft'), [])
  const [chip, setChip] = useState('wildcard')
  const [event, setEvent] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)

  const events = overview.status === 'ready' ? overview.data.events?.[chip] ?? [] : []
  const ladder = overview.status === 'ready' ? overview.data.ladder : null

  useEffect(() => {
    if (!busy) return
    const t0 = Date.now()
    const id = window.setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000)
    return () => window.clearInterval(id)
  }, [busy])

  async function run(c: string, e: number) {
    setChip(c)
    setEvent(e)
    setDraft(null)
    setBusy(true)
    setElapsed(0)
    try {
      setDraft(await getJson<Draft>(`/api/chipdraft?chip=${c}&event=${e}`))
    } catch {
      setDraft({ status: 'error' })
    } finally {
      setBusy(false)
    }
  }

  if (overview.status !== 'ready' || overview.data.status !== 'ok') return null
  const anyInHand = Object.values(overview.data.events ?? {}).some((v) => v.length)
  if (!anyInHand) return null

  return (
    <section className="px-10 py-8">
      <div className="voice text-lg text-text-muted">the squad a chip in hand would build, and what it is worth</div>
      <h2 className="font-display text-text">Chip drafts</h2>

      {ladder && ladder.ladder.length > 0 && (
        <div className="mt-5 border-2 border-ink bg-paper/70 p-5">
          <div className="mb-3 flex items-baseline justify-between">
            <div className="font-display text-xl font-black uppercase text-text">The wildcard ladder</div>
            <div className="text-[11.5px] text-text-faint">a draft for every week, {age(ladder.computed_at)} · click a week to see its squad</div>
          </div>
          <Ladder rows={ladder.ladder} chosen={chip === 'wildcard' ? event : null} pick={(e) => run('wildcard', e)} />
          <LadderNote rows={ladder.ladder} />
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3">
        {CHIPS.map((c) => (
          <button key={c.key} type="button" onClick={() => { setChip(c.key); setDraft(null); setEvent(null) }}
            disabled={!(overview.data.events?.[c.key] ?? []).length}
            className={`border-2 border-ink px-3 py-1 font-display text-[14px] font-black uppercase disabled:opacity-30 ${chip === c.key ? 'bg-ink text-paper' : 'bg-paper text-text hover:bg-raised'}`}>
            {c.label}
          </button>
        ))}
        <span className="mx-1 h-6 w-0.5 bg-ink/30" />
        {events.map((e) => (
          <button key={e} type="button" onClick={() => run(chip, e)} disabled={busy}
            className={`border-2 border-ink px-2 py-1 font-display text-[13px] font-black disabled:opacity-40 ${event === e ? 'bg-spot text-ink shadow-[3px_3px_0_var(--ink)]' : 'bg-paper text-text hover:bg-raised'}`}>
            GW{e}
          </button>
        ))}
      </div>

      {busy && (
        <div className="mt-6 flex items-center gap-4 border-2 border-dashed border-ink/50 p-5">
          <div className="animate-spin h-8 w-8 rounded-full border-4 border-ink border-t-spot" />
          <div className="text-[13px] text-text-muted">
            Drafting a {chip === 'wildcard' ? 'wildcard' : 'free hit'} for GW{event}: two solves of the week plan, about a minute and a half. {elapsed}s
          </div>
        </div>
      )}
      {!busy && draft?.status === 'ok' && <DraftView d={draft} />}
      {!busy && draft && draft.status !== 'ok' && (
        <div className="mt-6 text-[13px] text-text-muted">No draft for that week ({draft.status.replace(/_/g, ' ')}).</div>
      )}
    </section>
  )
}
