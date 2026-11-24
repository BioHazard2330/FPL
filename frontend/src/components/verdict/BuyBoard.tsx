import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJson } from '@/lib/api'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { LABEL_STYLE, Last6, LensBars, type Verdict } from '@/components/verdict/VerdictCard'

const POS = ['GKP', 'DEF', 'MID', 'FWD'] as const
const DOT: Record<string, string> = {
  Strong: 'var(--pitch-green)', Good: 'var(--broadcast-blue)', Mixed: 'var(--broadcast-gold)', Weak: 'var(--spot)', Avoid: 'var(--alert-red)',
}
const EXCLUDED_TEAMS = new Set(['MUN'])

/** The market as one picture per position: every judged player placed by price (across) and verdict (up), sized by his
 * projection over the horizon, your own players ringed. Beside it the best buys: the highest verdicts not already
 * owned, with no red pre-flight flag and no Man Utd player. */
export function BuyBoard() {
  const [rows, setRows] = useState<Verdict[] | null>(null)
  const [pos, setPos] = useState<(typeof POS)[number]>('MID')
  const [hover, setHover] = useState<Verdict | null>(null)
  useEffect(() => {
    getJson<{ players: Verdict[] }>('/api/verdicts').then((d) => setRows(d.players)).catch(() => setRows([]))
  }, [])
  const view = useMemo(() => (rows ?? []).filter((r) => r.position === pos && r.score != null && !EXCLUDED_TEAMS.has(r.team)), [rows, pos])
  const picks = useMemo(
    () => view.filter((r) => !r.mine && !r.flags.some((f) => f.level === 'red')).sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 5),
    [view],
  )
  if (!rows) return <div className="h-[420px] animate-pulse bg-raised/40" />
  if (!rows.length) return null

  const prices = view.map((r) => r.price)
  const lo = Math.floor(Math.min(...prices, 4)), hi = Math.ceil(Math.max(...prices, 6))
  const W = 640, H = 360, L = 40, B = 30, T = 14, R = 70
  const x = (p: number) => L + ((p - lo) / Math.max(1, hi - lo)) * (W - L - R)
  const y = (s: number) => T + (1 - s / 100) * (H - T - B)
  const xpMax = Math.max(...view.map((r) => r.facts.xp_horizon ?? 0), 1)
  const pickIds = new Set(picks.map((p) => p.player_id))
  const focus = hover ?? picks[0] ?? null

  return (
    <section className="px-8 py-7">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="font-display text-text">The buy board</h2>
          <p className="voice mt-1 text-[15px] text-text-muted">Up is a better verdict, left is cheaper. The top-left corner is where the market is wrong.</p>
        </div>
        <div className="flex border-2 border-ink">
          {POS.map((p) => (
            <button key={p} onClick={() => { setPos(p); setHover(null) }}
              className={`px-4 py-1.5 font-display text-[15px] font-black uppercase ${p === pos ? 'bg-ink text-paper' : 'text-text hover:bg-raised'}`}>
              {p === 'GKP' ? 'GK' : p}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="border-2 border-ink bg-paper">
          <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" onMouseLeave={() => setHover(null)}>
            <rect x={L} y={T} width={(W - L - R) / 2} height={(H - T - B) * 0.35} fill="var(--pitch-green)" opacity={0.08} />
            {[20, 35, 50, 65, 80].map((s) => (
              <g key={s}>
                <line x1={L} x2={W - R} y1={y(s)} y2={y(s)} stroke="var(--ink)" strokeOpacity={s === 50 ? 0.35 : 0.12} strokeDasharray={s === 50 ? '' : '3 4'} />
                <text x={L - 6} y={y(s) + 4} textAnchor="end" fontSize={11} fill="var(--text-faint)">{s}</text>
              </g>
            ))}
            {Array.from({ length: hi - lo + 1 }, (_, i) => lo + i).map((p) => (
              <text key={p} x={x(p)} y={H - 10} textAnchor="middle" fontSize={11} fill="var(--text-faint)">£{p}m</text>
            ))}
            {view.map((r) => {
              const rad = 4 + 9 * Math.sqrt(Math.max(0, r.facts.xp_horizon ?? 0) / xpMax)
              const on = focus?.player_id === r.player_id
              return (
                <g key={r.player_id} onMouseEnter={() => setHover(r)} className="cursor-pointer">
                  <circle cx={x(r.price)} cy={y(r.score ?? 0)} r={rad} fill={DOT[r.label] ?? 'var(--text-faint)'}
                    fillOpacity={pickIds.has(r.player_id) || on ? 0.95 : 0.45} stroke={r.mine ? 'var(--ink)' : on ? 'var(--ink)' : 'none'} strokeWidth={r.mine ? 3 : 2} />
                  {(pickIds.has(r.player_id) || r.mine || on) && (
                    <text x={x(r.price) + rad + 3} y={y(r.score ?? 0) + 4} fontSize={12} fontWeight={800} fill="var(--text)">{r.name}</text>
                  )}
                </g>
              )
            })}
          </svg>
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t-2 border-ink px-3 py-2 text-[11.5px] text-text-muted">
            {Object.entries(DOT).map(([k, c]) => <span key={k} className="flex items-center gap-1.5"><span className="size-2.5 rounded-full" style={{ background: c }} />{k}</span>)}
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full border-[2.5px] border-ink" />yours</span>
            <span>size = projection over the horizon</span>
          </div>
        </div>
        <div className="space-y-3">
          {focus && (
            <Link to={`/player/${focus.player_id}`} className="block border-2 border-ink bg-panel p-4 shadow-[4px_4px_0_var(--ink)] hover:bg-raised/40">
              <div className="flex items-center gap-3">
                <PlayerPhoto code={focus.photo_code ?? null} teamCode={focus.team_code ?? null} isGkp={focus.position === 'GKP'} className="h-16 w-14" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-display text-2xl font-black uppercase leading-none text-text">{focus.name}</div>
                  <div className="mt-1 text-[12.5px] text-text-muted">{focus.team} · £{focus.price.toFixed(1)}m · {focus.facts.xp_horizon?.toFixed(1) ?? '–'} xP</div>
                </div>
                <div className={`px-2 py-1 text-center ${LABEL_STYLE[focus.label] ?? ''}`}>
                  <div className="tabular font-display text-3xl font-black leading-none">{focus.score}</div>
                  <div className="text-[10px] font-black uppercase">{focus.label}</div>
                </div>
              </div>
              <div className="mt-3"><LensBars lenses={focus.lenses} compact /></div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <Last6 pts={focus.facts.last6} />
                {focus.flags[0] && <span className={`truncate text-[11.5px] font-bold ${focus.flags[0].level === 'red' ? 'text-alert-red' : 'text-broadcast-gold'}`}>{focus.flags[0].text}</span>}
              </div>
            </Link>
          )}
          <div className="border-2 border-ink">
            <div className="bg-ink px-3 py-1.5 font-display text-[13px] font-black uppercase tracking-[0.12em] text-paper">Best {pos === 'GKP' ? 'keepers' : pos.toLowerCase() + 's'} you don't own</div>
            {picks.map((p, i) => (
              <Link key={p.player_id} to={`/player/${p.player_id}`} onMouseEnter={() => setHover(p)}
                className="grid grid-cols-[1.4rem_minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-divider px-3 py-2 first:border-t-0 hover:bg-raised/50">
                <span className="font-display text-lg font-black text-text-faint">{i + 1}</span>
                <span className="min-w-0 truncate text-[14px] font-bold text-text">{p.name} <span className="font-normal text-text-faint">{p.team}</span></span>
                <span className="tabular text-[12.5px] text-text-muted">£{p.price.toFixed(1)}m</span>
                <span className={`tabular w-9 py-0.5 text-center text-[13px] font-black ${LABEL_STYLE[p.label] ?? ''}`}>{p.score}</span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
