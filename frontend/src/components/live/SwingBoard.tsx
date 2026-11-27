import { aheadWord, pts, vsTop10k } from '@/lib/say'
import { Info } from '@/components/ui/Info'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { crestUrl, getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** WHO TO CHEER: how far you are from the top 10k this gameweek, the side you want scoring next in every match still to
 * finish and what that goal is worth, and the players who have moved you so far (`models/live_swing.py`). */
interface Mover { player_id: number; name: string; photo_code: number | null; team_code: number | null; team_short: string; points: number; mine: number; eo: number; edge: number }
interface Side { short: string; code: number | null; goals: number; next_goal: number }
interface Card {
  fixture: number; status: 'pre' | 'live'; minute: number; kickoff: string | null; home: Side; away: Side; cheer: 'home' | 'away' | null
  key: { player_id: number; name: string; photo_code: number | null; team_code: number | null; stake: number }[]
}
interface Swing { status: string; event?: number; edge?: number; matches?: Card[]; helping?: Mover[]; hurting?: Mover[]; field?: string; field_event?: number | null; subs?: number; bonus_pending?: number }

const signed = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}`
const tone = (v: number) => (v >= 0 ? 'text-pitch-green' : 'text-alert-red')

function GoalWorth({ side, on }: { side: Side; on: boolean }) {
  return (
    <div className={`flex flex-1 flex-col items-center gap-1 border-2 border-ink px-2 py-3 ${on ? 'bg-spot text-ink' : 'bg-paper text-text'}`}>
      {crestUrl(side.code) && <img src={crestUrl(side.code)!} alt="" className="size-9" />}
      <span className="font-display text-lg font-black uppercase leading-none">{side.short}</span>
      <span className="text-[10.5px] font-bold uppercase tracking-[0.1em] opacity-70">if they score</span>
      <span className={`tabular font-display text-3xl font-black leading-none ${on ? '' : tone(side.next_goal)}`}>{signed(side.next_goal)}</span>
      <span className="text-[10.5px] font-bold uppercase tracking-[0.1em] opacity-70">pts {side.next_goal >= 0 ? 'gained' : 'lost'} on the 10k</span>
    </div>
  )
}

function CheerCard({ c }: { c: Card }) {
  const wanted = c.cheer ? c[c.cheer] : null
  const clock = c.status === 'live' ? `${c.minute}'` : c.kickoff ? new Date(c.kickoff).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : ''
  return (
    <div className="border-2 border-ink bg-paper p-3 shadow-[4px_4px_0_var(--ink)]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-display text-[15px] font-black uppercase text-text">{wanted ? `Cheer ${wanted.short}` : 'Either way'}</span>
        <span className={`tabular text-[12px] font-bold uppercase ${c.status === 'live' ? 'text-alert-red' : 'text-text-faint'}`}>
          {c.status === 'live' ? `${c.home.goals}–${c.away.goals} · ${clock}` : clock}
        </span>
      </div>
      <div className="mt-2 flex gap-2">
        <GoalWorth side={c.home} on={c.cheer === 'home'} />
        <GoalWorth side={c.away} on={c.cheer === 'away'} />
      </div>
      {c.key.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1" title="What each point he scores is worth to you against the top 10k">
          {c.key.map((k) => (
            <span key={k.player_id} className="flex min-w-0 items-center gap-1" title={`${k.name}: each point he scores moves you ${pts(k.stake)} against the top 10k`}>
              <PlayerPhoto code={k.photo_code} teamCode={k.team_code} className="h-7 w-6" />
              <span className="min-w-0 truncate text-[11px] text-text-muted">{k.name}</span>
              <span className={`tabular text-[12px] font-bold ${tone(k.stake)}`}>{signed(k.stake)}/pt</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function MoverColumn({ title, rows }: { title: string; rows: Mover[] }) {
  if (!rows.length) return null
  const top = Math.max(...rows.map((r) => Math.abs(r.edge)), 1)
  return (
    <div>
      <div className="mb-2 font-display text-[15px] font-black uppercase text-text">{title} <span className="text-[11px] font-bold normal-case tracking-normal text-text-faint">pts gained or lost on the top 10k</span></div>
      <div className="space-y-1.5">
        {rows.map((m) => (
          <div key={m.player_id} className="grid grid-cols-[2rem_6.5rem_minmax(0,1fr)_3.2rem] items-center gap-2" title={`${m.points} points so far. You own him ×${m.mine}, the top 10k ×${m.eo.toFixed(2)} on average, so he has moved you ${pts(m.edge)} against them`}>
            <PlayerPhoto code={m.photo_code} teamCode={m.team_code} className="h-9 w-7" />
            <span className="truncate text-[13.5px] font-bold text-text">{m.name}</span>
            <span className="h-3 bg-raised"><span className={`block h-full ${m.edge >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`} style={{ width: `${(Math.abs(m.edge) / top) * 100}%` }} /></span>
            <span className={`tabular text-right font-display text-lg font-black ${tone(m.edge)}`}>{signed(m.edge)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** The edge alone, for Matchday TV. */
export function EdgeLine() {
  const state = useFetch(() => getJson<Swing>('/api/swing'), [], 15000)
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const edge = state.data.edge ?? 0
  return (
    <div className="mt-3 flex items-baseline gap-2">
      <span className={`tabular font-display text-4xl font-black ${edge >= 0 ? 'text-[#4fd88a]' : 'text-[#ff6b57]'}`}>{Math.abs(edge).toFixed(1)}</span>
      <span className="text-[11px] font-bold uppercase tracking-[0.18em] text-paper/45">pts {aheadWord(edge)} of the top 10k</span>
    </div>
  )
}

export function SwingBoard({ event }: { event?: number }) {
  const state = useFetch(() => getJson<Swing>(`/api/swing${event ? `?event=${event}` : ''}`), [event], 15000)
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  const edge = d.edge ?? 0
  return (
    <section className="px-10 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className={`tabular font-display text-7xl font-black leading-none ${tone(edge)}`}>{Math.abs(edge).toFixed(1)} <span className="text-3xl">pts {aheadWord(edge)}</span></div>
          <div className="mt-1 flex items-center gap-2 text-[13px] font-bold uppercase tracking-[0.1em] text-text-faint">
            {vsTop10k(edge)} this gameweek, on the points so far
            <Info label="How this is worked out">
              Every player&apos;s live points, with provisional bonus, times your multiplier minus his effective ownership among the top 10k ({d.field}). Your substitutions and armband follow FPL&apos;s rules once a match ends; the field&apos;s are as locked. A next goal is shared across the side&apos;s players on the pitch by their projected goals and assists, with the bonus a goal usually carries, and takes off what the other side&apos;s 60-minute players lose.
            </Info>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-[12px] font-bold uppercase">
          {(d.bonus_pending ?? 0) > 0 && <span className="border-2 border-ink px-2 py-0.5 text-text">Bonus provisional</span>}
          {(d.subs ?? 0) > 0 && <span className="border-2 border-ink px-2 py-0.5 text-text">{d.subs} auto-sub{d.subs === 1 ? '' : 's'} in</span>}
          {d.field_event != null && d.field_event !== d.event && <span className="border-2 border-broadcast-gold px-2 py-0.5 text-text">Top 10k: GW{d.field_event} picks, aged</span>}
        </div>
      </div>
      {(d.matches ?? []).length > 0 && (
        <>
          <h2 className="mt-6 font-display text-text">Who to cheer</h2>
          <p className="voice mt-1 text-[15px] text-text-muted">For each match left: how many points you would gain or lose against the top 10k if each side scores next.</p>
          <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {d.matches!.map((c) => <CheerCard key={c.fixture} c={c} />)}
          </div>
        </>
      )}
      {((d.helping ?? []).length > 0 || (d.hurting ?? []).length > 0) && (
        <div className="mt-6 grid gap-8 md:grid-cols-2">
          <MoverColumn title="Helping you" rows={d.helping ?? []} />
          <MoverColumn title="Hurting you" rows={d.hurting ?? []} />
        </div>
      )}
    </section>
  )
}
