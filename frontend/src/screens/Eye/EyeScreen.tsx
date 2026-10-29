import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, ScreenError } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { getJson } from '@/lib/api'
import { clubColors } from '@/lib/clubs'
import { useFetch } from '@/lib/useFetch'

/** THE EYE JOURNAL - you watched it; the app did not. After a gameweek, one tap per player: how he looked (poor to
 * outstanding) and what you saw (sharp, isolated, tired...). The notes sit beside the data on the album and the war room,
 * reach the plan through the eye gate (rated sharp or better: protected from sale; off it or worse: unprotected, and a
 * target needs the extra margin), and are scored against what each player did next, so the journal learns how much your
 * eye is worth. */

interface Gw { minutes: number; goals: number; assists: number; bonus: number; xg: number | null; xa: number | null; total_points: number; defensive_contribution: number | null; saves: number | null }
interface Note { rating: number; tags: string[]; note: string | null }
interface EyePlayer {
  player_id: number; name: string; photo_code: number | null; team_short: string; team_code: number; position: string
  group: 'squad' | 'target'; target_when: string | null; gw: Gw | null; note: Note | null; current_read: (Note & { event: number }) | null
}
interface EyePayload {
  status: string; event: number; players: EyePlayer[]; tags: string[]; ratings: { value: number; label: string }[]
  scorecard: { settled: number; total_notes: number; edge: number | null; groups: { rating: number; label: string; n: number; beat_projection_by: number }[] }
  events: number[]
}

const TONE: Record<number, string> = {
  [-2]: 'bg-alert-red text-alert-red-ink', [-1]: 'bg-[color-mix(in_srgb,var(--alert-red)_35%,var(--paper))] text-ink',
  0: 'bg-raised text-text', 1: 'bg-[color-mix(in_srgb,var(--pitch-green)_45%,var(--paper))] text-ink', 2: 'bg-pitch-green text-pitch-green-ink',
}

function Card({ p, event, tags, ratings }: { p: EyePlayer; event: number; tags: string[]; ratings: EyePayload['ratings'] }) {
  const [rating, setRating] = useState<number | null>(p.note?.rating ?? null)
  const [chosen, setChosen] = useState<string[]>(p.note?.tags ?? [])
  const [line, setLine] = useState(p.note?.note ?? '')
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>(p.note ? 'saved' : 'idle')
  const club = clubColors(p.team_code)
  const g = p.gw

  const save = async (r = rating, t = chosen, n = line) => {
    if (r === null) return
    setState('saving')
    const q = new URLSearchParams({ player: String(p.player_id), event: String(event), rating: String(r), tags: t.join(','), note: n })
    try {
      const res = await fetch(`/api/eye-note?${q}`, { method: 'POST', headers: { 'X-FPL-Refresh': '1' } })
      setState(res.ok ? 'saved' : 'error')
    } catch {
      setState('error')
    }
  }

  return (
    <div className={`border-[3px] border-ink bg-paper shadow-[5px_5px_0_var(--ink)] ${rating !== null ? '' : 'opacity-95'}`}>
      <div className="flex">
        <Link to={`/player/${p.player_id}`} className="relative w-28 shrink-0 overflow-hidden border-r-[3px] border-ink" style={{ background: `linear-gradient(160deg, ${club.primary}, color-mix(in srgb, ${club.primary} 60%, #17130e))` }}>
          <PlayerPhoto code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} className="mx-auto mt-2 h-28 w-24" />
          {p.group === 'target' && <span className="absolute left-0 top-0 bg-broadcast-gold px-1 font-display text-[11px] font-black uppercase text-ink">target {p.target_when}</span>}
        </Link>
        <div className="min-w-0 flex-1 px-3 py-2">
          <div className="flex items-baseline justify-between gap-2">
            <div className="truncate font-display text-2xl font-black uppercase leading-none text-text">{p.name}</div>
            <span className="text-[11px] font-bold uppercase text-text-faint">{p.team_short} · {p.position}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 text-[12px] text-text-muted">
            {g ? (
              <>
                <span><span className="tabular font-display text-lg font-black text-text">{g.total_points}</span> pts</span>
                <span>{g.minutes}′</span>
                {(g.goals > 0 || g.assists > 0) && <span>{g.goals}G {g.assists}A</span>}
                <span>xG+xA {((g.xg ?? 0) + (g.xa ?? 0)).toFixed(2)}</span>
                {g.bonus > 0 && <span>bonus {g.bonus}</span>}
              </>
            ) : <span>did not feature</span>}
          </div>
          <div className="mt-2 grid grid-cols-5 gap-1">
            {ratings.map((r) => (
              <button key={r.value} type="button"
                onClick={() => { setRating(r.value); save(r.value) }}
                className={`border-2 border-ink py-1 font-display text-[11.5px] font-black uppercase leading-tight transition-transform ${rating === r.value ? `${TONE[r.value]} -translate-y-0.5 shadow-[2px_2px_0_var(--ink)]` : 'bg-paper text-text-faint hover:text-text'}`}>
                {r.label}
              </button>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {tags.map((t) => {
              const on = chosen.includes(t)
              return (
                <button key={t} type="button"
                  onClick={() => { const next = on ? chosen.filter((x) => x !== t) : [...chosen, t]; setChosen(next); if (rating !== null) save(rating, next) }}
                  className={`border px-1.5 text-[11px] font-semibold ${on ? 'border-ink bg-ink text-paper' : 'border-ink/30 text-text-muted hover:border-ink'}`}>
                  {t}
                </button>
              )
            })}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <input value={line} onChange={(e) => setLine(e.target.value)} onBlur={() => rating !== null && save()} placeholder="one line on what you saw (optional)"
              className="min-w-0 flex-1 border-b-2 border-ink/30 bg-transparent py-0.5 text-[12.5px] outline-none focus:border-ink" />
            <span className={`text-[11px] font-bold uppercase ${state === 'saved' ? 'text-pitch-green' : state === 'error' ? 'text-alert-red' : 'text-text-faint'}`}>
              {state === 'saved' ? 'noted' : state === 'saving' ? 'saving' : state === 'error' ? 'not saved' : rating === null ? 'tap a rating' : ''}
            </span>
          </div>
          {p.current_read && p.current_read.event !== event && (
            <div className="mt-1 text-[11px] text-text-faint">your last read: GW{p.current_read.event} · {ratings.find((r) => r.value === p.current_read!.rating)?.label}</div>
          )}
        </div>
      </div>
    </div>
  )
}

export function EyeScreen() {
  const [event, setEvent] = useState<number | null>(null)
  const state = useFetch(() => getJson<EyePayload>(event ? `/api/eye?event=${event}` : '/api/eye'), [event])
  const [key, setKey] = useState(0)
  useEffect(() => setKey((k) => k + 1), [state.status])
  if (state.status === 'loading') return <div className="animate-pulse px-10 py-8"><Skel className="h-96 w-full" /></div>
  if (state.status === 'error') return <ScreenError title="The eye journal is unavailable" description="The gameweek could not be read." message={state.error.message} />
  const d = state.data
  if (d.status !== 'ok') return <p className="px-10 py-8 text-sm text-text-muted">No finished gameweek to look back on yet.</p>
  const sc = d.scorecard
  const squad = d.players.filter((p) => p.group === 'squad')
  const targets = d.players.filter((p) => p.group === 'target')
  return (
    <div className="data-in pb-16" key={key}>
      <Masthead right={<span>{sc.total_notes} notes so far</span>} />
      <section className="relative overflow-hidden !bg-ink px-10 py-8 text-paper">
        <div className="absolute inset-0 opacity-20 [background-image:radial-gradient(rgba(246,240,226,0.4)_1px,transparent_1.5px)] [background-size:7px_7px]" />
        <div className="relative grid grid-cols-1 items-end gap-8 xl:grid-cols-[minmax(0,1fr)_auto]">
          <div>
            <div className="voice text-xl text-paper/70">you watched it; the model didn't</div>
            <div className="font-display text-[5.5rem] font-black uppercase leading-[0.85] [text-shadow:5px_5px_0_var(--spot)]">The eye journal</div>
            <div className="mt-4 flex flex-wrap gap-2">
              {d.events.map((e) => (
                <button key={e} type="button" onClick={() => setEvent(e)}
                  className={`border-2 px-2 py-0.5 font-display text-[14px] font-black ${e === d.event ? 'border-spot bg-spot text-ink' : 'border-paper/40 text-paper/70 hover:text-paper'}`}>GW{e}</button>
              ))}
            </div>
          </div>
          <div className="max-w-md border-2 border-paper/30 p-4">
            <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-paper/60">your eye's record</div>
            {sc.settled === 0 ? (
              <p className="mt-1 text-[13.5px] leading-relaxed text-paper/80">
                Nothing settled yet. Every note is set against what the player does the gameweek after, against the projection frozen
                at that deadline; once a few settle, this says whether your eye beats the model and by how much.
              </p>
            ) : (
              <>
                <div className="mt-1 flex flex-wrap gap-3">
                  {sc.groups.map((g) => (
                    <span key={g.rating} className="text-[13px]"><span className="font-semibold">{g.label}</span> ({g.n}): <span className={g.beat_projection_by >= 0 ? 'text-[#7fe0a6]' : 'text-[#ff8a7a]'}>{g.beat_projection_by >= 0 ? '+' : ''}{g.beat_projection_by.toFixed(2)}</span></span>
                  ))}
                </div>
                {sc.edge !== null && <div className="mt-2 font-display text-3xl font-black">{sc.edge >= 0 ? '+' : ''}{sc.edge.toFixed(2)} <span className="text-[13px] font-normal text-paper/70">points a player between your ups and downs, next gameweek</span></div>}
              </>
            )}
          </div>
        </div>
      </section>
      <section className="px-8 pb-8 pt-7">
        <h2 className="font-display text-text">Your squad in GW{d.event}</h2>
        <p className="mt-1 max-w-3xl text-[13px] text-text-muted">
          One tap is enough. Sharp or outstanding protects a player from the plan selling him; off it or poor takes that protection
          away. Tags and a line are for you and the album.
        </p>
        <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2 2xl:grid-cols-3">
          {squad.map((p) => <Card key={`${d.event}-${p.player_id}`} p={p} event={d.event} tags={d.tags} ratings={d.ratings} />)}
        </div>
      </section>
      {targets.length > 0 && (
        <section className="px-8 pb-8 pt-7">
          <h2 className="font-display text-text">The players the plan wants</h2>
          <p className="mt-1 max-w-3xl text-[13px] text-text-muted">If you watched one and did not like what you saw, say so: off it or poor makes the plan ask more of him before it buys.</p>
          <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2 2xl:grid-cols-3">
            {targets.map((p) => <Card key={`${d.event}-${p.player_id}`} p={p} event={d.event} tags={d.tags} ratings={d.ratings} />)}
          </div>
        </section>
      )}
    </div>
  )
}
