import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, ScreenError } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchReviewPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { ReviewPayload, ReviewPlayer, ReviewSwing } from '@/lib/types'

/** THE GAMEWEEK REPORT - a finished gameweek read back like the last page of a programme: the score against everyone and
 * against the top ten thousand, the rank move, the eleven as it scored, where the rank was won and lost, the armband, what
 * the plan of record would have scored, and how much of it was the model and how much luck. Every number is stored data
 * (`models/gw_review.py`); the plan's score has no automatic substitutions and says so. */

const signed = (v: number, d = 0) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`
const fmtRank = (r: number) => (r >= 1_000_000 ? `${(r / 1_000_000).toFixed(2)}m` : r >= 1_000 ? `${Math.round(r / 1_000)}k` : String(r))
const CHIP: Record<string, string> = { '3xc': 'Triple captain', bboost: 'Bench boost', freehit: 'Free hit', wildcard: 'Wildcard' }

function tone(points: number) {
  if (points >= 10) return 'bg-pitch-green text-pitch-green-ink'
  if (points >= 6) return 'bg-[color-mix(in_srgb,var(--pitch-green)_55%,var(--paper))] text-ink'
  if (points >= 3) return 'bg-paper text-ink'
  return 'bg-[color-mix(in_srgb,var(--alert-red)_22%,var(--paper))] text-ink'
}

function RankLine({ history, event }: { history: ReviewPayload['history']; event: number }) {
  const pts = history.filter((h) => h.rank)
  if (pts.length < 2) return null
  const logs = pts.map((h) => Math.log10(h.rank!))
  const lo = Math.min(...logs), hi = Math.max(...logs)
  const W = 320, H = 92
  const x = (i: number) => 8 + (i / (pts.length - 1)) * (W - 16)
  const y = (v: number) => 10 + ((v - lo) / Math.max(hi - lo, 0.01)) * (H - 26)
  const path = pts.map((_, i) => `${i ? "L" : "M"}${x(i)},${y(logs[i])}`).join(" ")
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[22rem]" role="img" aria-label="Overall rank by gameweek">
      <path d={path} fill="none" stroke="var(--paper)" strokeWidth={3} />
      {pts.map((h, i) => (
        <g key={h.event}>
          <circle cx={x(i)} cy={y(logs[i])} r={h.event === event ? 6 : 3.5} fill={h.event === event ? 'var(--spot)' : 'var(--paper)'} stroke="var(--ink)" strokeWidth={2} />
          <text x={x(i)} y={H - 2} textAnchor="middle" fontSize={10} fontWeight={800} fill="var(--paper)" opacity={h.event === event ? 1 : 0.6} fontFamily="var(--font-display)">{h.event}</text>
        </g>
      ))}
    </svg>
  )
}

function Hero({ d, pick }: { d: ReviewPayload; pick: (e: number) => void }) {
  const moved = d.rank && d.previous_rank ? d.previous_rank - d.rank : null
  const vs = [
    { label: 'GW average', value: d.average, delta: d.average !== null ? d.points - d.average : null },
    { label: 'Top-10k average', value: d.top10k_field, delta: d.top10k_field !== null ? d.points - d.top10k_field : null },
    { label: 'Best score', value: d.highest, delta: null },
  ]
  return (
    <section className="relative overflow-hidden !bg-ink text-paper">
      <div className="absolute inset-0 opacity-25 [background-image:radial-gradient(rgba(246,240,226,0.35)_1px,transparent_1.5px)] [background-size:7px_7px]" />
      <div className="pointer-events-none absolute -right-6 -top-16 select-none font-display text-[22rem] font-black leading-none text-paper/[0.06]">{d.event}</div>
      <div className="relative px-10 pb-8 pt-7">
        <div className="flex flex-wrap items-center gap-2">
          {d.events.map((e) => (
            <button key={e} type="button" onClick={() => pick(e)}
              className={`border-2 px-2 py-0.5 font-display text-[14px] font-black ${e === d.event ? 'border-spot bg-spot text-ink' : 'border-paper/40 text-paper/70 hover:border-paper hover:text-paper'}`}>
              GW{e}
            </button>
          ))}
        </div>
        <div className="mt-6 grid grid-cols-1 items-end gap-8 xl:grid-cols-[auto_minmax(0,1fr)_auto]">
          <div>
            <div className="voice text-xl text-paper/70">the gameweek {d.event} report{d.chip ? ` · ${CHIP[d.chip] ?? d.chip}` : ''}</div>
            <div className="flex items-end gap-4">
              <div className="tabular font-display text-[9.5rem] font-black leading-[0.78] [text-shadow:6px_6px_0_var(--spot)]">{d.points}</div>
              <div className="pb-3 font-display text-2xl font-black uppercase leading-none text-paper/80">points{d.hits ? <><br /><span className="text-alert-red">−{d.hits} hits</span></> : null}</div>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-[2px] self-end border-2 border-paper/30 bg-paper/30">
            {vs.map((v) => (
              <div key={v.label} className="bg-ink px-4 py-3">
                <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-paper/60">{v.label}</div>
                <div className="tabular font-display text-4xl font-black leading-none">{v.value ?? '—'}</div>
                {v.delta !== null && (
                  <div className={`tabular mt-1 font-display text-lg font-black ${v.delta >= 0 ? 'text-[#7fe0a6]' : 'text-[#ff8a7a]'}`}>{signed(v.delta, 1)} you</div>
                )}
              </div>
            ))}
          </div>
          <div className="min-w-[17rem]">
            <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-paper/60">overall rank</div>
            <div className="flex items-baseline gap-3">
              <span className="tabular font-display text-5xl font-black leading-none">{d.rank ? fmtRank(d.rank) : '—'}</span>
              {moved !== null && (
                <span className={`tabular font-display text-2xl font-black ${moved >= 0 ? 'text-[#7fe0a6]' : 'text-[#ff8a7a]'}`}>{moved >= 0 ? '▲' : '▼'} {fmtRank(Math.abs(moved))}</span>
              )}
            </div>
            <RankLine history={d.history} event={d.event} />
          </div>
        </div>
      </div>
    </section>
  )
}

function Tile({ p }: { p: ReviewPlayer }) {
  const counted = p.multiplier > 0
  return (
    <Link to={`/player/${p.player_id}`} className={`relative block w-[8.25rem] border-2 border-ink shadow-[4px_4px_0_var(--ink)] transition-transform hover:-translate-y-1 ${counted ? '' : 'opacity-55'}`}>
      <div className="relative h-24 overflow-hidden bg-raised">
        <PlayerPhoto code={p.photo_code} teamCode={p.team_code ?? null} isGkp={p.position === 'GKP'} className="mx-auto h-24 w-20" />
        {p.captain && <span className="absolute left-1 top-1 flex size-6 items-center justify-center rounded-full border-2 border-ink bg-broadcast-gold font-display text-[13px] font-black text-ink">C</span>}
        {p.subbed_on && <span className="absolute left-1 top-1 bg-pitch-green px-1 font-display text-[11px] font-black uppercase text-paper">on ▲</span>}
        {p.subbed_off && <span className="absolute left-1 top-1 bg-alert-red px-1 font-display text-[11px] font-black uppercase text-paper">off ▼</span>}
        <span className={`tabular absolute bottom-0 right-0 border-l-2 border-t-2 border-ink px-2 font-display text-3xl font-black leading-tight ${tone(p.points * Math.max(p.multiplier, 1))}`}>
          {p.points * Math.max(p.multiplier, 1)}
        </span>
      </div>
      <div className="border-t-2 border-ink bg-ink px-1.5 py-0.5 font-display text-[14px] font-black uppercase leading-tight text-paper">{p.name}</div>
      <div className="flex justify-between bg-paper px-1.5 py-0.5 text-[11px] text-text-muted">
        <span title="projected at the deadline">xP {p.predicted !== null ? p.predicted.toFixed(1) : '—'}</span>
        <span title="points with the finishing and goals-against luck taken out">fair {p.deserved !== null ? p.deserved.toFixed(1) : '—'}</span>
      </div>
    </Link>
  )
}

function Eleven({ d }: { d: ReviewPayload }) {
  const order = ['GKP', 'DEF', 'MID', 'FWD']
  const xi = d.squad.filter((p) => p.starting)
  const bench = d.squad.filter((p) => !p.starting)
  return (
    <section className="px-10 pb-8 pt-7">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="font-display text-text">The eleven, as it scored</h2>
        <div className="text-[13px] text-text-muted">
          projected {d.predicted.toFixed(1)} · fair {d.deserved.toFixed(1)} · scored <span className="font-semibold text-text">{d.counted}</span>
          {d.subs.length > 0 && <> · auto-subs: {d.subs.map((s) => `${s.out} → ${s.into}`).join(', ')}</>}
        </div>
      </div>
      <div className="mt-5 space-y-5">
        {order.map((pos) => (
          <div key={pos} className="flex items-center gap-4">
            <span className="w-10 shrink-0 font-display text-lg font-black text-text-faint">{pos}</span>
            <div className="flex flex-wrap gap-4">{xi.filter((p) => p.position === pos).map((p) => <Tile key={p.player_id} p={p} />)}</div>
          </div>
        ))}
        <div className="flex items-center gap-4 border-t-2 border-dashed border-ink/40 pt-5">
          <span className="w-10 shrink-0 font-display text-lg font-black text-text-faint">BEN</span>
          <div className="flex flex-wrap gap-4">{bench.map((p) => <Tile key={p.player_id} p={p} />)}</div>
          {d.bench_points !== null && <span className="ml-2 font-display text-lg font-black text-text-muted">{d.bench_points} on the bench</span>}
        </div>
      </div>
    </section>
  )
}

function SwingRow({ s, max }: { s: ReviewSwing; max: number }) {
  const w = `${(Math.abs(s.swing) / max) * 100}%`
  const gain = s.swing > 0
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_2.5rem_minmax(0,1fr)] items-center gap-2 py-1.5">
      <div className="flex justify-end">{!gain && <div className="h-7 border-2 border-ink bg-alert-red" style={{ width: w }} />}</div>
      <PlayerPhoto code={s.photo_code} teamCode={s.team_code ?? null} isGkp={s.position === 'GKP'} className="mx-auto h-10 w-8" />
      <div>{gain && <div className="h-7 border-2 border-ink bg-pitch-green" style={{ width: w }} />}</div>
      <div className={`col-span-3 -mt-1 flex text-[12.5px] ${gain ? 'justify-start pl-[calc(50%+1.5rem)]' : 'justify-end pr-[calc(50%+1.5rem)] text-right'}`}>
        <span>
          <span className="font-semibold text-text">{s.name}</span> {s.points} pts · {s.yours ? `you ×${s.yours}` : 'not yours'} · top 10k {s.field_eo.toFixed(2)}
          <span className={`ml-1.5 tabular font-display font-black ${gain ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(s.swing, 1)}</span>
        </span>
      </div>
    </div>
  )
}

function Swings({ d }: { d: ReviewPayload }) {
  if (!d.gains.length && !d.losses.length) return null
  const max = Math.max(...[...d.gains, ...d.losses].map((s) => Math.abs(s.swing)), 1)
  const net = d.top10k_field !== null ? d.points - d.top10k_field : null
  return (
    <section className="px-10 pb-8 pt-7">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="font-display text-text">Where the rank was won and lost</h2>
        {net !== null && <span className={`tabular font-display text-2xl font-black ${net >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(net, 1)} on the top 10k</span>}
      </div>
      <p className="mt-1 max-w-3xl text-[13px] text-text-muted">
        Each player's points times your multiplier minus the top ten thousand's effective ownership of him: green moved you up on them, red moved you down.
      </p>
      <div className="mt-4 grid grid-cols-2 gap-x-10">
        <div className="text-center font-display text-[13px] font-black uppercase tracking-[0.06em] text-alert-red">lost ground</div>
        <div className="text-center font-display text-[13px] font-black uppercase tracking-[0.06em] text-pitch-green">gained ground</div>
      </div>
      <div className="mt-2 divide-y divide-divider">
        {[...d.gains, ...d.losses].sort((a, b) => Math.abs(b.swing) - Math.abs(a.swing)).slice(0, 10).map((s) => <SwingRow key={s.player_id} s={s} max={max} />)}
      </div>
    </section>
  )
}

function Verdicts({ d }: { d: ReviewPayload }) {
  const c = d.captain
  const luck = d.counted - d.deserved
  const card = 'border-2 border-ink bg-paper p-5 shadow-[5px_5px_0_var(--ink)]'
  const label = 'font-display text-[13px] font-black uppercase tracking-[0.08em] text-text-faint'
  return (
    <section className="grid grid-cols-1 gap-6 px-10 pb-8 pt-7 xl:grid-cols-3">
      <div className={card}>
        <div className={label}>The armband</div>
        {c ? (
          <>
            <div className="mt-1 font-display text-3xl font-black uppercase text-text">{c.captain.name}</div>
            <div className="tabular font-display text-5xl font-black leading-none text-text">{c.captain.actual * c.multiplier}<span className="ml-2 text-lg text-text-muted">pts ×{c.multiplier}</span></div>
            <p className="mt-3 text-[13.5px] leading-snug text-text-muted">
              Best in your eleven: <span className="font-semibold text-text">{c.best_actual.name}</span> ({c.best_actual.actual}).
              {c.cost > 0 ? <> The armband left <span className="font-semibold text-alert-red">{c.cost}</span> on the table, </> : <> Nothing left on the table, </>}
              and on the chances it was worth {c.captain.deserved.toFixed(1)} a go.
            </p>
          </>
        ) : <p className="mt-2 text-sm text-text-muted">No captain record for this gameweek.</p>}
      </div>
      <div className={`${card} ${d.plan && d.plan.score > d.counted - d.hits ? '!bg-[color-mix(in_srgb,var(--broadcast-gold)_14%,var(--paper))]' : ''}`}>
        <div className={label}>The plan of record</div>
        {d.plan ? (
          <>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="tabular font-display text-5xl font-black leading-none text-text">{d.plan.score}</span>
              <span className={`tabular font-display text-2xl font-black ${d.plan.score - d.points > 0 ? 'text-alert-red' : 'text-pitch-green'}`}>
                {d.plan.score - d.points > 0 ? `${d.plan.score - d.points} more than you` : d.plan.score === d.points ? 'same as you' : `${d.points - d.plan.score} fewer than you`}
              </span>
            </div>
            <ul className="mt-3 space-y-1 text-[13.5px] text-text-muted">
              {d.plan.moves.length === 0 && <li>It said roll.</li>}
              {d.plan.moves.map((m) => (
                <li key={m.into.player_id ?? 0}>
                  {m.out.name} <span className="tabular">({m.out.points})</span> → <span className="font-semibold text-text">{m.into.name}</span>{' '}
                  <span className={`tabular font-semibold ${m.into.points - m.out.points >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>({m.into.points}, {signed(m.into.points - m.out.points)})</span>
                </li>
              ))}
              <li>Armband: {d.plan.captain.name} ({d.plan.captain.points}){d.plan.hits ? ` · ${d.plan.hits} in hits` : ''}</li>
            </ul>
            <p className="mt-2 text-[11.5px] text-text-faint">Its eleven on the real points, no automatic substitutions.</p>
            {(d.plan.eye_held_back ?? []).length > 0 && (
              <div className="mt-3 border-t-2 border-ink pt-2">
                <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">the football eye held back</div>
                <ul className="mt-1 space-y-1 text-[13px] text-text-muted">
                  {d.plan.eye_held_back!.map((m) => (
                    <li key={`${m.out.player_id}-${m.into.player_id}`}>
                      {m.out.name} <span className="tabular">({m.out.points})</span> → {m.into.name} <span className="tabular">({m.into.points})</span>{' '}
                      <span className={`tabular font-semibold ${m.gate_won >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
                        {m.gate_won > 0 ? `eye right by ${m.gate_won}` : m.gate_won < 0 ? `eye cost ${-m.gate_won}` : 'level'}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(() => {
              const scored = (d.ledger ?? []).filter((r) => r.eye_won !== null && r.eye_won !== undefined)
              if (scored.length === 0) return null
              const net = scored.reduce((n, r) => n + (r.eye_won ?? 0), 0)
              return (
                <div className="mt-1 text-[12.5px] text-text-muted">
                  The eye's gate over {scored.length} gameweek{scored.length === 1 ? '' : 's'}:{' '}
                  <span className={`tabular font-semibold ${net >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{net >= 0 ? '+' : ''}{net} points</span>
                </div>
              )
            })()}
            {(d.ledger ?? []).length > 1 && (() => {
              const L = d.ledger ?? []
              const you = L.reduce((n, r) => n + r.you, 0), planned = L.reduce((n, r) => n + r.plan, 0)
              return (
                <div className="mt-3 border-t-2 border-ink pt-2">
                  <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">every week a plan existed</div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    {L.map((r) => (
                      <span key={r.event} className="tabular text-[12.5px] text-text-muted">
                        GW{r.event} <span className={r.plan > r.you ? 'font-semibold text-alert-red' : r.plan < r.you ? 'font-semibold text-pitch-green' : ''}>{r.you}–{r.plan}</span>
                      </span>
                    ))}
                  </div>
                  <div className="mt-1 font-display text-lg font-black text-text">
                    you {you} · plan {planned} <span className={you >= planned ? 'text-pitch-green' : 'text-alert-red'}>({you >= planned ? '+' : ''}{you - planned} you)</span>
                  </div>
                </div>
              )
            })()}
          </>
        ) : <p className="mt-2 text-sm text-text-muted">No plan was stored before this deadline.</p>}
      </div>
      <div className={card}>
        <div className={label}>Model and luck</div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-center">
          {[['projected', d.predicted.toFixed(1)], ['fair', d.deserved.toFixed(1)], ['scored', String(d.counted)]].map(([k, v]) => (
            <div key={k} className="border-2 border-ink bg-raised py-2">
              <div className="tabular font-display text-3xl font-black leading-none text-text">{v}</div>
              <div className="mt-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">{k}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[13.5px] leading-snug text-text-muted">
          {luck >= 0 ? <>Finishing and goals-against luck added <span className="font-semibold text-pitch-green">{luck.toFixed(1)}</span></> : <>Finishing and goals-against luck cost <span className="font-semibold text-alert-red">{(-luck).toFixed(1)}</span></>}
          ; the model's projection for the eleven that played was {Math.abs(d.counted - d.predicted).toFixed(1)} {d.counted >= d.predicted ? 'under' : 'over'} the result.
        </p>
      </div>
    </section>
  )
}

function Stars({ d }: { d: ReviewPayload }) {
  const mine = new Set(d.squad.map((p) => p.player_id))
  return (
    <section className="px-10 pb-8 pt-7">
      <h2 className="font-display text-text">The week's best</h2>
      <div className="mt-4 flex flex-wrap gap-5">
        {d.stars.map((s, i) => (
          <Link key={s.player_id ?? i} to={`/player/${s.player_id}`} className="relative w-40 border-2 border-ink bg-paper shadow-[4px_4px_0_var(--ink)] transition-transform hover:-translate-y-1">
            <span className="absolute left-0 top-0 z-10 bg-ink px-2 font-display text-lg font-black text-paper">{i + 1}</span>
            {s.player_id !== null && mine.has(s.player_id) && <span className="absolute right-1 top-1 z-10 border-2 border-ink bg-broadcast-gold px-1 font-display text-[11px] font-black uppercase text-ink">yours</span>}
            <PlayerPhoto code={s.photo_code} teamCode={s.team_code ?? null} isGkp={s.position === 'GKP'} className="mx-auto h-28 w-24" />
            <div className="flex items-center justify-between border-t-2 border-ink bg-ink px-2 py-1 text-paper">
              <span className="font-display text-[15px] font-black uppercase">{s.name}</span>
              <span className="tabular font-display text-xl font-black text-[#7fe0a6]">{s.points}</span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  )
}

export function ReviewScreen() {
  const [event, setEvent] = useState<number | null>(null)
  const state = useFetch(() => fetchReviewPayload(event), [event])
  return (
    <div className="data-in pb-16">
      <Masthead right={state.status === 'ready' && state.data.status === 'ok' ? <span>{state.data.total} points after GW{state.data.event}</span> : undefined} />
      {state.status === 'loading' && <div className="animate-pulse px-10 py-8"><Skel className="h-72 w-full" /><Skel className="mt-6 h-96 w-full" /></div>}
      {state.status === 'error' && <ScreenError title="The report is unavailable" description="The gameweek could not be read back." message={state.error.message} />}
      {state.status === 'ready' && state.data.status !== 'ok' && <p className="px-10 py-8 text-sm text-text-muted">No finished gameweek with your picks and FPL's per-player points yet.</p>}
      {state.status === 'ready' && state.data.status === 'ok' && (
        <>
          <Hero d={state.data} pick={setEvent} />
          <Verdicts d={state.data} />
          <Eleven d={state.data} />
          <Swings d={state.data} />
          <Stars d={state.data} />
        </>
      )}
    </div>
  )
}
