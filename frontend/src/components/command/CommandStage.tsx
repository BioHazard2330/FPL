import { Link } from 'react-router-dom'
import { crestUrl, playerPhotoUrl, shirtUrl } from '@/lib/api'
import { clubColors } from '@/lib/clubs'
import { fdrFill } from '@/lib/fdr'
import type { ActionSquadBlock, ActionSquadPlayer, FixtureContext, WeekPlanPayload } from '@/lib/types'

/** THE STAGE: the week's team stood on a pitch drawn in perspective, the way a broadcast shows a line-up before kick-off,
 * with the armband pick in a spotlight beside it and the eleven's fixtures crawling along the top.
 *
 * The pitch is a real projection, not a CSS tilt: every line, box, circle and mowing band is a point on a 68 x 105 m
 * pitch run through a pinhole camera behind our goal (`project`), so the far end narrows and the stripes compress the
 * way they do on television. Players stand upright at their projected spot and shrink with distance. Every number on
 * it is the stored week plan's: expected points, the armband, the moves, the next opponent. */

const VW = 960
const VH = 540
const FOCAL = 1619
const CAM_H = 75.5
const Z_NEAR = 128
const LENGTH = 105
const HALF_W = 34
const HORIZON = -454

function project(x: number, y: number): [number, number, number] {
  const z = Z_NEAR + (LENGTH - y)
  const s = FOCAL / z
  return [VW / 2 + x * s, HORIZON + CAM_H * s, Z_NEAR / z]
}

function path(points: [number, number][], close = false): string {
  return points.map(([x, y], i) => {
    const [px, py] = project(x, y)
    return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)},${py.toFixed(1)}`
  }).join(' ') + (close ? ' Z' : '')
}

function rect(x0: number, y0: number, x1: number, y1: number): string {
  return path([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], true)
}

function circle(cx: number, cy: number, r: number, from = 0, to = Math.PI * 2): string {
  const pts: [number, number][] = []
  for (let i = 0; i <= 48; i++) {
    const a = from + ((to - from) * i) / 48
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
  }
  return path(pts)
}

function Pitch() {
  const bands = Array.from({ length: 10 }, (_, i) => i)
  const line = 'color-mix(in srgb, #edf0f5 34%, transparent)'
  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid meet" aria-hidden>
      <defs>
        <linearGradient id="stage-fade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0b0e13" stopOpacity="0.85" />
          <stop offset="0.35" stopColor="#0b0e13" stopOpacity="0" />
        </linearGradient>
      </defs>
      {bands.map((i) => (
        <path
          key={i}
          d={rect(-HALF_W - 3, i * 10.5, HALF_W + 3, (i + 1) * 10.5)}
          fill={i % 2 === 0 ? '#16402c' : '#1b4a33'}
        />
      ))}
      <g fill="none" stroke={line} strokeWidth="1.6">
        <path d={rect(-HALF_W, 0, HALF_W, LENGTH)} />
        <path d={path([[-HALF_W, 52.5], [HALF_W, 52.5]])} />
        <path d={circle(0, 52.5, 9.15)} />
        <path d={rect(-20.16, 0, 20.16, 16.5)} />
        <path d={rect(-9.16, 0, 9.16, 5.5)} />
        <path d={rect(-20.16, LENGTH - 16.5, 20.16, LENGTH)} />
        <path d={rect(-9.16, LENGTH - 5.5, 9.16, LENGTH)} />
        <path d={circle(0, LENGTH - 11, 9.15, Math.PI + 0.93, Math.PI * 2 - 0.93)} />
        <path d={circle(0, 11, 9.15, 0.93, Math.PI - 0.93)} />
        <path d={rect(-3.66, LENGTH, 3.66, LENGTH + 1.6)} />
      </g>
      <rect x="0" y="0" width={VW} height={VH} fill="url(#stage-fade)" />
    </svg>
  )
}

const DEPTH: Record<string, number> = { GKP: 98, DEF: 78, MID: 55, FWD: 30 }

function spots(players: ActionSquadPlayer[]): { p: ActionSquadPlayer; left: number; top: number; scale: number }[] {
  const out: { p: ActionSquadPlayer; left: number; top: number; scale: number }[] = []
  for (const pos of ['FWD', 'MID', 'DEF', 'GKP']) {
    const row = players.filter((p) => p.position === pos)
    row.forEach((p, i) => {
      const spread = row.length === 1 ? 0 : (i / (row.length - 1) - 0.5) * (pos === 'MID' ? 60 : pos === 'DEF' ? (row.length >= 5 ? 58 : 48) : 26)
      const depth = DEPTH[pos] + (row.length >= 4 ? (i % 2 === 1 ? 7 : -4) : 0)
      const [x, y, s] = project(spread, depth)
      out.push({ p, left: (x / VW) * 100, top: (y / VH) * 100, scale: 0.72 + 0.28 * s })
    })
  }
  return out
}

function Player({ p, block, fixtures, scale, moveIn }: { p: ActionSquadPlayer; block: ActionSquadBlock; fixtures?: FixtureContext; scale: number; moveIn?: string }) {
  const next = p.team_code !== null ? fixtures?.[String(p.team_code)]?.[0] : undefined
  const shirt = shirtUrl(p.team_code, p.position === 'GKP', 220)
  const captain = p.player_id === block.captain_id
  const vice = p.player_id === block.vice_id
  return (
    <div className="flex w-44 flex-col items-center" style={{ transform: `translate(-50%, -82%) scale(${scale})`, transformOrigin: '50% 82%' }}>
      <div className="relative">
        {shirt && <img src={shirt} alt="" className="h-[3.6rem] w-[3.6rem] object-contain drop-shadow-[0_10px_8px_rgba(0,0,0,0.6)]" />}
        {captain && <span className="absolute -right-2 top-1 flex size-6 items-center justify-center rounded-full bg-broadcast-gold font-display text-[13px] font-bold text-broadcast-gold-ink ring-2 ring-[#0b0e13]">C</span>}
        {vice && <span className="absolute -right-2 top-1 flex size-6 items-center justify-center rounded-full bg-raised font-display text-[13px] font-bold text-text ring-2 ring-[#0b0e13]">V</span>}
        {p.is_new && <span className="absolute -left-3 top-1 bg-pitch-green px-1.5 font-display text-[12px] font-bold uppercase text-pitch-green-ink">in</span>}
      </div>
      <Link to={`/player/${p.player_id}`} className="-mt-1 flex items-stretch whitespace-nowrap shadow-[0_8px_18px_-6px_rgba(0,0,0,0.8)] hover:brightness-125">
        <span className="max-w-[5.6rem] truncate bg-[#0b0e13]/92 px-2 py-0.5 text-[13px] font-semibold text-text">{p.name}</span>
        <span className="bg-pitch-green px-1.5 py-0.5 font-display text-[14px] font-bold tabular text-pitch-green-ink">{p.median.toFixed(1)}</span>
        {next && (
          <span className={`flex items-center px-1.5 text-[10.5px] font-bold ${fdrFill(next.difficulty)}`}>
            {next.opponent_short} {next.is_home ? 'H' : 'A'}
          </span>
        )}
      </Link>
      {moveIn && <span className="mt-1 bg-alert-red px-1.5 text-[11px] font-bold uppercase tracking-wide text-alert-red-ink">off · {moveIn} on</span>}
    </div>
  )
}

function Spotlight({ plan }: { plan: WeekPlanPayload }) {
  const cap = plan.captain?.best
  if (!cap) return null
  const c = clubColors(cap.team_code)
  const next = cap.team_code !== null ? plan.fixtures?.[String(cap.team_code)]?.[0] : undefined
  const crest = crestUrl(cap.team_code)
  const second = plan.captain?.second
  return (
    <div
      className="relative flex h-full min-h-[470px] flex-col justify-end overflow-hidden"
      style={{ background: `linear-gradient(160deg, color-mix(in srgb, ${c.primary} 78%, #0b0e13) 0%, color-mix(in srgb, ${c.primary} 30%, #0b0e13) 55%, #0b0e13 100%)` }}
    >
      {crest && <img src={crest} alt="" className="absolute -right-10 top-6 size-64 opacity-[0.13]" />}
      <div className="absolute inset-y-0 left-0 w-[7px]" style={{ background: c.accent }} />
      {cap.photo_code && (
        <img
          src={playerPhotoUrl(cap.photo_code, 'hero')}
          alt=""
          referrerPolicy="no-referrer"
          className="absolute bottom-[7.5rem] right-0 h-[24rem] w-[24rem] object-contain object-bottom drop-shadow-[0_20px_30px_rgba(0,0,0,0.6)]"
        />
      )}
      <div className="absolute left-6 top-5 flex items-center gap-2">
        <span className="flex size-8 items-center justify-center rounded-full bg-broadcast-gold font-display text-base font-bold text-broadcast-gold-ink">C</span>
        <span className="text-[11.5px] font-bold uppercase tracking-[0.16em] text-text/80">The armband · GW{plan.event}</span>
      </div>
      <div className="relative bg-gradient-to-t from-[#0b0e13] via-[#0b0e13]/90 to-transparent px-6 pb-5 pt-10">
        <Link to={`/player/${cap.player_id}`} className="block font-display text-[3.6rem] font-bold uppercase leading-[0.85] text-text hover:text-pitch-green">
          {cap.name}
        </Link>
        <div className="mt-3 flex items-baseline gap-4">
          <span className="font-display text-4xl font-bold tabular text-pitch-green">{cap.median.toFixed(1)}</span>
          <span className="text-[13px] text-text-muted">expected points, doubled</span>
          {next && <span className={`ml-auto px-2 py-0.5 text-[12px] font-bold ${fdrFill(next.difficulty)}`}>{next.opponent_short} {next.is_home ? 'H' : 'A'}</span>}
        </div>
        {second && <div className="mt-2 text-[13px] text-text-faint">Next best {second.name} on {second.median.toFixed(1)}</div>}
      </div>
    </div>
  )
}

function Ticker({ block, fixtures, event }: { block: ActionSquadBlock; fixtures?: FixtureContext; event?: number }) {
  const items = [...block.starting].sort((a, b) => b.median - a.median).map((p) => {
    const next = p.team_code !== null ? fixtures?.[String(p.team_code)]?.[0] : undefined
    return { p, next }
  })
  const row = (key: string) => (
    <div key={key} className="flex shrink-0 items-center">
      {items.map(({ p, next }) => (
        <span key={`${key}-${p.player_id}`} className="flex items-center gap-2 px-5 text-[13px]">
          <span className="font-semibold text-text">{p.name}</span>
          {next && (
            <>
              {crestUrl(next.opponent_code) && <img src={crestUrl(next.opponent_code)!} alt="" className="size-4" />}
              <span className="text-text-muted">{next.is_home ? 'v' : '@'} {next.opponent_short}</span>
            </>
          )}
          <span className="font-display font-bold tabular text-pitch-green">{p.median.toFixed(1)}</span>
          <span className="text-text-faint/50">/</span>
        </span>
      ))}
    </div>
  )
  return (
    <div className="relative flex overflow-hidden border-b border-divider bg-[#0b0e13]/80 py-2">
      <span className="absolute inset-y-0 left-0 z-10 flex items-center bg-[#0b0e13] pr-4">
        <span className="flex h-full items-center bg-pitch-green px-3 pr-5 font-display text-[13px] font-bold uppercase tracking-[0.1em] text-pitch-green-ink [clip-path:polygon(0_0,100%_0,86%_100%,0_100%)]">
          GW{event} fixtures
        </span>
      </span>
      <div className="ticker-track flex">{row('a')}{row('b')}</div>
    </div>
  )
}

export function CommandStage({ plan }: { plan: WeekPlanPayload }) {
  const block = plan.action_squad
  if (!block || block.starting.length === 0) return null
  const moveIn: Record<number, string> = {}
  for (const m of plan.moves ?? []) moveIn[m.out.player_id] = m.into.name
  const placed = spots(block.starting)
  const total = block.starting.reduce((s, p) => s + p.median, 0)
  const formation = ['DEF', 'MID', 'FWD'].map((k) => block.starting.filter((p) => p.position === k).length).join('-')
  return (
    <section className="!p-0">
      <Ticker block={block} fixtures={plan.fixtures} event={plan.event} />
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_25rem]">
        <div className="relative overflow-hidden bg-[radial-gradient(120%_80%_at_50%_0%,#13241c_0%,#0b0e13_70%)]">
          <div className="absolute left-6 top-5 z-10">
            <h2 className="font-display text-xl font-semibold text-text">Your GW{plan.event} eleven</h2>
            <div className="mt-1 text-[13px] text-text-muted">
              {formation} · <span className="font-semibold text-text">{total.toFixed(1)}</span> xP from the eleven
              {(plan.moves ?? []).length > 0 ? ' · after the moves' : ''}
            </div>
          </div>
          <div className="relative mx-auto w-full" style={{ aspectRatio: `${VW} / ${VH}` }}>
            <Pitch />
            {placed.map(({ p, left, top, scale }) => (
              <div key={p.player_id} className="absolute" style={{ left: `${left}%`, top: `${top}%`, zIndex: Math.round(top) }}>
                <Player p={p} block={block} fixtures={plan.fixtures} scale={scale} moveIn={moveIn[p.player_id]} />
              </div>
            ))}
          </div>
          {block.bench.length > 0 && (
            <div className="flex items-center gap-4 border-t border-divider/70 bg-[#0b0e13]/70 px-6 py-3">
              <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-text-faint">Bench</span>
              {block.bench.map((p, i) => (
                <Link key={p.player_id} to={`/player/${p.player_id}`} className="flex items-center gap-2 opacity-85 hover:opacity-100">
                  <span className="font-display text-[13px] text-text-faint">{i + 1}</span>
                  {shirtUrl(p.team_code, p.position === 'GKP', 64) && <img src={shirtUrl(p.team_code, p.position === 'GKP', 64)!} alt="" className="size-7 object-contain" />}
                  <span className="text-[13px] font-semibold text-text-muted">{p.name}</span>
                  <span className="font-display text-[13px] font-bold tabular text-text-faint">{p.median.toFixed(1)}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
        <Spotlight plan={plan} />
      </div>
    </section>
  )
}
