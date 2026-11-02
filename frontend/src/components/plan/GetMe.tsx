import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchPlayersIndex, getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { PlayerIndexRow } from '@/lib/types'

/** GET ME X: name a player and the plan's own solver finds the best way to have him this gameweek with one, two or three
 * moves (his purchase included, hits charged past the free transfers): the supporting sales, the points over the horizon,
 * what insisting on him costs against the best plan without him, and the gap to the plan of record. */
interface Side { player_id: number; name: string; photo_code: number | null; team_code: number | null }
interface Route {
  moves: number; feasible: boolean; reason?: string; pairs?: { out: Side; into: Side }[]; hits?: number; total?: number
  cost_of_insisting?: number | null; vs_plan?: number | null; proven?: boolean
}
interface GetMePayload {
  status: string; target?: Side & { team_short: string }; event?: number; horizon?: number; free_transfers?: number
  plan_total?: number | null; routes?: Route[]; best?: number | null
}

const signed = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}`

function RouteCard({ r, best, target, horizon }: { r: Route; best: boolean; target: number; horizon: number }) {
  if (!r.feasible) {
    return (
      <div className="border-2 border-dashed border-ink/40 p-5 text-[13px] text-text-faint">
        <div className="font-display text-xl font-black uppercase text-text-faint">{r.moves} move{r.moves === 1 ? '' : 's'}</div>
        Not affordable with {r.moves === 1 ? 'one move' : `${r.moves} moves`} at strict sale prices.
      </div>
    )
  }
  const cost = r.cost_of_insisting ?? 0
  return (
    <div className={`relative border-2 border-ink p-5 ${best ? 'bg-paper shadow-[6px_6px_0_var(--spot)]' : 'bg-paper/70 shadow-[4px_4px_0_var(--ink)]'}`}>
      {best && <div className="absolute -top-3 right-4 bg-spot px-2 py-0.5 font-display text-[12px] font-black uppercase text-ink">best route</div>}
      <div className="flex items-baseline justify-between">
        <div className="font-display text-xl font-black uppercase text-text">{r.moves} move{r.moves === 1 ? '' : 's'}</div>
        <div className="tabular font-display text-3xl font-black text-text">{r.total?.toFixed(1)}</div>
      </div>
      <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">points over {horizon} gameweeks{r.hits ? ` · ${r.hits} in hits` : ''}</div>
      <div className="mt-3 space-y-2">
        {r.pairs!.map((p) => (
          <div key={p.into.player_id} className="grid grid-cols-[2rem_minmax(0,1fr)_1rem_2rem_minmax(0,1fr)] items-center gap-2">
            <PlayerPhoto code={p.out.photo_code} teamCode={p.out.team_code} className="h-9 w-7" muted />
            <span className="truncate text-[13px] text-text-muted line-through decoration-alert-red/60">{p.out.name}</span>
            <span className="text-text-faint">→</span>
            <PlayerPhoto code={p.into.photo_code} teamCode={p.into.team_code} className="h-9 w-7" />
            <span className={`truncate text-[13.5px] font-bold ${p.into.player_id === target ? 'text-spot' : 'text-text'}`}>{p.into.name}</span>
          </div>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 border-t-2 border-ink/15 pt-3 text-[12px]">
        <div>
          <div className="text-text-faint">cost of insisting</div>
          <div className={`tabular font-display text-xl font-black ${cost <= 0.5 ? 'text-pitch-green' : cost <= 2 ? 'text-broadcast-gold' : 'text-alert-red'}`}>
            {cost <= 0.05 ? 'free' : `−${cost.toFixed(1)}`}
          </div>
        </div>
        <div>
          <div className="text-text-faint">against the plan</div>
          <div className={`tabular font-display text-xl font-black ${(r.vs_plan ?? 0) >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{r.vs_plan !== null && r.vs_plan !== undefined ? signed(r.vs_plan) : '—'}</div>
        </div>
      </div>
      {r.proven === false && <div className="mt-2 text-[11px] text-text-faint">Solver stopped at its time limit: best found, not proven best.</div>}
    </div>
  )
}

export function GetMe() {
  const [params, setParams] = useSearchParams()
  const index = useFetch(fetchPlayersIndex, [])
  const [q, setQ] = useState('')
  const target = Number(params.get('getme')) || null
  const [data, setData] = useState<GetMePayload | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const anchor = useRef<HTMLElement>(null)

  const players: PlayerIndexRow[] = useMemo(() => (index.status === 'ready' ? index.data.players : []), [index])
  const hits = q.length >= 2 ? players.filter((p) => p.name.toLowerCase().includes(q.toLowerCase())).slice(0, 6) : []

  useEffect(() => {
    if (!target) { setData(null); return }
    anchor.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    let alive = true
    setBusy(true)
    setElapsed(0)
    const t0 = Date.now()
    const tick = window.setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 500)
    getJson<GetMePayload>(`/api/getme?player=${target}`).then((d) => alive && setData(d)).catch(() => alive && setData({ status: 'error' }))
      .finally(() => { window.clearInterval(tick); if (alive) setBusy(false) })
    return () => { alive = false; window.clearInterval(tick) }
  }, [target])

  return (
    <section ref={anchor} className="scroll-mt-4 px-10 py-8">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <div className="voice text-lg text-text-muted">name the player; the solver finds the money</div>
          <h2 className="font-display text-text">Get me…</h2>
        </div>
        <div className="relative w-[22rem]">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Type a player"
            className="w-full border-2 border-ink bg-paper px-3 py-2 text-[15px] font-semibold text-text shadow-[3px_3px_0_var(--ink)] outline-none placeholder:text-text-faint"
          />
          {hits.length > 0 && (
            <div className="absolute inset-x-0 top-full z-30 mt-1 border-2 border-ink bg-paper shadow-[4px_4px_0_var(--ink)]">
              {hits.map((p) => (
                <button key={p.player_id} type="button" onClick={() => { setParams((s) => { s.set('getme', String(p.player_id)); return s }); setQ('') }}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13.5px] hover:bg-raised">
                  <PlayerPhoto code={p.photo_code} teamCode={p.team_code} className="h-8 w-6" />
                  <span className="font-semibold text-text">{p.name}</span>
                  <span className="ml-auto text-[12px] text-text-faint">{p.team_short} · £{p.price?.toFixed(1)}m</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      {busy && (
        <div className="mt-6 flex items-center gap-4 border-2 border-ink bg-ink px-5 py-4 text-paper">
          <div className="size-5 animate-spin rounded-full border-[3px] border-paper/30 border-t-spot" />
          <div className="font-display text-lg font-black uppercase">Solving six plans</div>
          <div className="tabular text-[13px] text-paper/60">{elapsed}s · about a minute: one, two and three moves, each with and without him</div>
        </div>
      )}
      {!busy && data && data.status === 'owned' && <p className="mt-5 text-text-muted">{data.target?.name} is already in your squad.</p>}
      {!busy && data && (data.status === 'unaffordable' || data.status === 'not_in_pool') && (
        <p className="mt-5 text-text-muted">{data.target?.name}: no route with up to three moves this gameweek{data.status === 'not_in_pool' ? ' (outside the buyable pool: flagged out, or from an excluded club)' : ' at strict sale prices'}.</p>
      )}
      {!busy && data && data.status === 'ok' && data.target && (
        <div className="mt-6">
          <div className="mb-4 flex items-center gap-3">
            <PlayerPhoto code={data.target.photo_code} teamCode={data.target.team_code} className="h-14 w-11" />
            <div>
              <Link to={`/player/${data.target.player_id}`} className="font-display text-2xl font-black uppercase text-text hover:text-spot">{data.target.name}</Link>
              <div className="text-[12.5px] text-text-muted">
                GW{data.event} · {data.free_transfers} free transfer{data.free_transfers === 1 ? '' : 's'} · plan of record {data.plan_total?.toFixed(1)} over {data.horizon} GW
              </div>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            {(data.routes ?? []).map((r) => <RouteCard key={r.moves} r={r} best={r.moves === data.best} target={data.target!.player_id} horizon={data.horizon ?? 5} />)}
          </div>
          <p className="mt-3 text-[12px] text-text-faint">
            Cost of insisting: the best plan with the same number of moves and no constraint, minus this one. Both use the plan's projections, its
            trust in a player's record and the eye's gate, so a route can come out level or a fraction ahead.
          </p>
        </div>
      )}
    </section>
  )
}
