import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, SkelTable, ScreenError } from '@/components/shell/ScreenStates'
import { crestUrl, fetchTablePayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { TableRow } from '@/lib/types'

/** THE TABLE - the league as it stands, and the league as the chances say.
 *
 * Top: THE QUADRANT. Twenty crests plotted by xG created per match
 * (right = more) against xG allowed per match (up = fewer), the league
 * average splitting the pitch into four. A club in the top-right creates a
 * lot and allows little; bottom-left is the reverse. It is the one picture
 * that says which attacks are real and which defences to target, and it
 * is built from nothing but stored per-match xG.
 *
 * Below: the table itself, with real goals beside the xG that produced
 * them, so finishing luck and keeping luck sit in their own columns. */

type SortKey = 'points' | 'gd' | 'xgd' | 'finishing' | 'keeping' | 'xg' | 'xga'

const VW = 900
const VH = 560
const PAD = { l: 56, r: 40, t: 36, b: 44 }

function FormDots({ form }: { form: TableRow['form'] }) {
  return (
    <span className="inline-flex gap-0.5">
      {form.map((r, i) => (
        <span key={i} className={`inline-block h-3.5 w-3.5 text-center text-[9px] font-bold leading-[14px] ${r === 'W' ? 'bg-pitch-green text-pitch-green-ink' : r === 'D' ? 'bg-raised text-text-muted' : 'bg-alert-red text-alert-red-ink'}`}>{r}</span>
      ))}
    </span>
  )
}

/** A diverging cell: bar left for negative, right for positive, shared
 * scale, the number sitting outside the track on the side it points to. */
function Diverge({ v, scale }: { v: number | null; scale: number }) {
  if (v === null) return <span className="text-text-faint">—</span>
  const w = Math.min(1, Math.abs(v) / scale) * 50
  const num = `${v >= 0 ? '+' : ''}${v.toFixed(1)}`
  return (
    <span className="inline-grid grid-cols-[2.4rem_100px_2.4rem] items-center gap-1 align-middle">
      <span className={`tabular text-right text-[10px] font-semibold ${v < 0 ? 'text-alert-red' : 'text-transparent'}`}>{v < 0 ? num : ''}</span>
      <span className="relative h-3">
        <span className="absolute left-1/2 top-0 h-full w-px bg-divider" />
        <span
          className={`absolute top-0 h-full ${v >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`}
          style={v >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }}
        />
      </span>
      <span className={`tabular text-[10px] font-semibold ${v >= 0 ? 'text-pitch-green' : 'text-transparent'}`}>{v >= 0 ? num : ''}</span>
    </span>
  )
}

export function TableScreen() {
  const state = useFetch(fetchTablePayload, [], 300000)
  const [hover, setHover] = useState<number | null>(null)
  const [sort, setSort] = useState<SortKey>('points')

  const rows = state.status === 'ready' ? state.data.rows : []
  const plotted = useMemo(() => rows.filter((r) => r.xg_per_match !== null && r.xga_per_match !== null), [rows])
  const xs = plotted.map((r) => r.xg_per_match as number)
  const ys = plotted.map((r) => r.xga_per_match as number)
  const xMin = Math.min(...xs, 0.6), xMax = Math.max(...xs, 2.0)
  const yMin = Math.min(...ys, 0.6), yMax = Math.max(...ys, 2.0)
  const xAvg = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0
  const yAvg = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 0
  const sx = (v: number) => PAD.l + ((v - xMin) / (xMax - xMin)) * (VW - PAD.l - PAD.r)
  // Fewer conceded is better, so it goes up.
  const sy = (v: number) => PAD.t + ((v - yMin) / (yMax - yMin)) * (VH - PAD.t - PAD.b)

  const sorted = useMemo(() => {
    const arr = rows.slice()
    if (sort === 'points') return arr
    arr.sort((a, b) => ((b[sort] ?? -99) as number) - ((a[sort] ?? -99) as number))
    return arr
  }, [rows, sort])
  const divScale = Math.max(1, ...rows.map((r) => Math.max(Math.abs(r.finishing ?? 0), Math.abs(r.keeping ?? 0))))

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="px-10 py-8"><Skel className="h-[520px] w-full" /></div>
        <div className="px-10"><SkelTable rows={20} cols={12} /></div>
      </div>
    )
  }
  if (state.status === 'error') {
    return <ScreenError title="Table unavailable" description="The table could not be fetched." message={state.error.message} />
  }
  const d = state.data
  if (!d.has_table) {
    return (
      <div className="pb-16">
        <Masthead edition="The Table" title="No finished fixture yet" />
        <p className="px-10 py-8 text-sm text-text-muted">The table starts when the first fixture finishes.</p>
      </div>
    )
  }
  const h = hover !== null ? rows.find((r) => r.team_id === hover) ?? null : null

  const ticks = (min: number, max: number) => {
    const out: number[] = []
    for (let v = Math.ceil(min * 4) / 4; v <= max; v += 0.25) out.push(Number(v.toFixed(2)))
    return out
  }

  return (
    <div className="data-in pb-16">
      <Masthead
        edition="The Table"
        title="As it stands, and as the chances say"
        right={<span className="text-text-muted">through GW{d.through_event} · {d.matches} matches, {d.matches_with_xg} with xG</span>}
      />

      {/* THE QUADRANT */}
      <div className="grid grid-cols-[1fr_300px] border-b-2 border-divider">
        <div className="border-r border-divider px-8 py-6">
          <svg viewBox={`0 0 ${VW} ${VH}`} className="h-auto w-full select-none" role="img"
               aria-label="Every club by xG created per match against xG allowed per match"
               onMouseLeave={() => setHover(null)}>
            {ticks(xMin, xMax).map((v) => (
              <g key={`x${v}`}>
                <line x1={sx(v)} y1={PAD.t} x2={sx(v)} y2={VH - PAD.b} stroke="var(--divider)" strokeOpacity={0.5} />
                <text x={sx(v)} y={VH - PAD.b + 14} textAnchor="middle" fontSize={9} fill="var(--text-faint)" className="tabular">{v.toFixed(2)}</text>
              </g>
            ))}
            {ticks(yMin, yMax).map((v) => (
              <g key={`y${v}`}>
                <line x1={PAD.l} y1={sy(v)} x2={VW - PAD.r} y2={sy(v)} stroke="var(--divider)" strokeOpacity={0.5} />
                <text x={PAD.l - 8} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="var(--text-faint)" className="tabular">{v.toFixed(2)}</text>
              </g>
            ))}
            <line x1={sx(xAvg)} y1={PAD.t} x2={sx(xAvg)} y2={VH - PAD.b} stroke="var(--text)" strokeOpacity={0.35} strokeDasharray="4 4" />
            <line x1={PAD.l} y1={sy(yAvg)} x2={VW - PAD.r} y2={sy(yAvg)} stroke="var(--text)" strokeOpacity={0.35} strokeDasharray="4 4" />

            <text x={VW - PAD.r - 4} y={PAD.t + 12} textAnchor="end" fontSize={10} fontWeight={700} letterSpacing="1.5" fill="var(--pitch-green)">CREATE A LOT · ALLOW LITTLE</text>
            <text x={PAD.l + 4} y={PAD.t + 12} fontSize={10} fontWeight={700} letterSpacing="1.5" fill="var(--text-faint)">CREATE LITTLE · ALLOW LITTLE</text>
            <text x={VW - PAD.r - 4} y={VH - PAD.b - 6} textAnchor="end" fontSize={10} fontWeight={700} letterSpacing="1.5" fill="var(--text-faint)">CREATE A LOT · ALLOW A LOT</text>
            <text x={PAD.l + 4} y={VH - PAD.b - 6} fontSize={10} fontWeight={700} letterSpacing="1.5" fill="var(--alert-red)">CREATE LITTLE · ALLOW A LOT</text>

            <text x={(PAD.l + VW - PAD.r) / 2} y={VH - 6} textAnchor="middle" fontSize={9} fill="var(--text-faint)" letterSpacing="1.5">xG CREATED PER MATCH →</text>
            <text x={12} y={(PAD.t + VH - PAD.b) / 2} textAnchor="middle" fontSize={9} fill="var(--text-faint)" letterSpacing="1.5" transform={`rotate(-90 12 ${(PAD.t + VH - PAD.b) / 2})`}>← xG ALLOWED PER MATCH</text>

            {plotted.map((r) => {
              const cx = sx(r.xg_per_match as number), cy = sy(r.xga_per_match as number)
              const dim = hover !== null && hover !== r.team_id
              const crest = crestUrl(r.code)
              return (
                <Link key={r.team_id} to={`/club/${r.team_id}`}>
                  <g
                    style={{ opacity: dim ? 0.3 : 1, transition: 'opacity 150ms' }}
                    className="cursor-pointer"
                    onMouseEnter={() => setHover(r.team_id)}
                  >
                    {r.mine && <circle cx={cx} cy={cy} r={20} fill="none" stroke="var(--broadcast-gold)" strokeWidth={2} />}
                    {hover === r.team_id && <circle cx={cx} cy={cy} r={22} fill="none" stroke="var(--text)" strokeWidth={1} />}
                    {crest ? (
                      <image href={crest} x={cx - 15} y={cy - 15} width={30} height={30} />
                    ) : (
                      <circle cx={cx} cy={cy} r={12} fill="var(--raised)" />
                    )}
                    <text x={cx} y={cy + 27} textAnchor="middle" fontSize={9} fontWeight={700} fill="var(--text)" fillOpacity={0.8} letterSpacing="0.8">{r.short}</text>
                  </g>
                </Link>
              )
            })}
          </svg>
        </div>

        <div className="px-6 py-6">
          {h ? (
            <div className="data-in">
              <div className="flex items-center gap-3">
                {crestUrl(h.code) && <img src={crestUrl(h.code) as string} alt="" className="h-10 w-10" />}
                <div>
                  <div className="font-display text-3xl font-bold uppercase leading-none text-text">{h.short}</div>
                  <div className="text-[10px] uppercase tracking-[0.16em] text-text-faint">{h.position}{ordinal(h.position)} · {h.points} pts · {h.played} played</div>
                </div>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-y-4">
                <Stat label="xG per match" v={(h.xg_per_match ?? 0).toFixed(2)} tone="text-pitch-green" />
                <Stat label="xG allowed" v={(h.xga_per_match ?? 0).toFixed(2)} tone="text-alert-red" />
                <Stat label="scored" v={String(h.gf)} sub={`from ${h.xg.toFixed(1)} xG`} />
                <Stat label="conceded" v={String(h.ga)} sub={`from ${h.xga.toFixed(1)} allowed`} />
              </div>
              <div className="mt-5 space-y-2 border-t border-divider pt-4 text-xs">
                <div className="flex items-baseline justify-between">
                  <span className="text-text-faint">finishing</span>
                  <span className={`tabular font-semibold ${(h.finishing ?? 0) >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{(h.finishing ?? 0) >= 0 ? '+' : ''}{(h.finishing ?? 0).toFixed(1)} <span className="font-normal text-text-faint">goals over xG</span></span>
                </div>
                <div className="flex items-baseline justify-between">
                  <span className="text-text-faint">keeping</span>
                  <span className={`tabular font-semibold ${(h.keeping ?? 0) >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{(h.keeping ?? 0) >= 0 ? '+' : ''}{(h.keeping ?? 0).toFixed(1)} <span className="font-normal text-text-faint">fewer conceded than allowed</span></span>
                </div>
                <div className="flex items-baseline justify-between">
                  <span className="text-text-faint">form</span>
                  <FormDots form={h.form} />
                </div>
              </div>
              <Link to={`/club/${h.team_id}`} className="mt-5 inline-block text-[10px] font-bold uppercase tracking-[0.14em] text-broadcast-blue hover:underline">Open the club file</Link>
            </div>
          ) : (
            <div>
              <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">The quadrant</div>
              <p className="mt-2 text-sm leading-relaxed text-text-muted">
                Every club by the chances it creates against the chances it allows, per match. The dashed lines are the league average. Hover a crest.
              </p>
              <div className="mt-5 space-y-2 text-[11px] text-text-faint">
                <div className="flex items-center gap-2"><span className="inline-block size-3 rounded-full border-2 border-broadcast-gold" /> a club you own players from</div>
              </div>
              <div className="mt-6 text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">League average</div>
              <div className="tabular mt-1 text-sm text-text-muted">{xAvg.toFixed(2)} xG created · {yAvg.toFixed(2)} allowed, per match</div>
            </div>
          )}
        </div>
      </div>

      {/* THE TABLE */}
      <div className="px-10 py-8">
        <div className="mb-3 flex flex-wrap items-center gap-4">
          <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Sort by</span>
          {([['points', 'Points'], ['gd', 'Goal difference'], ['xgd', 'xG difference'], ['xg', 'xG'], ['xga', 'xG allowed'], ['finishing', 'Finishing'], ['keeping', 'Keeping']] as [SortKey, string][]).map(([k, label]) => (
            <button key={k} type="button" onClick={() => setSort(k)}
              className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] transition-colors ${sort === k ? 'bg-text text-void' : 'bg-raised text-text-muted hover:text-text'}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[64rem] text-left text-sm">
            <thead>
              <tr className="border-b-2 border-divider text-[10px] uppercase tracking-[0.14em] text-text-faint">
                <th className="py-2 pr-3 font-bold">#</th>
                <th className="py-2 pr-4 font-bold">Club</th>
                <th className="tabular py-2 pr-3 text-right font-bold">P</th>
                <th className="tabular py-2 pr-3 text-right font-bold">W</th>
                <th className="tabular py-2 pr-3 text-right font-bold">D</th>
                <th className="tabular py-2 pr-3 text-right font-bold">L</th>
                <th className="tabular py-2 pr-3 text-right font-bold">GF</th>
                <th className="tabular py-2 pr-3 text-right font-bold">GA</th>
                <th className="tabular py-2 pr-3 text-right font-bold">GD</th>
                <th className="tabular py-2 pr-4 text-right font-bold text-text">Pts</th>
                <th className="py-2 pr-4 font-bold">Form</th>
                <th className="tabular py-2 pr-3 text-right font-bold text-pitch-green">xG</th>
                <th className="tabular py-2 pr-3 text-right font-bold text-alert-red">xGA</th>
                <th className="tabular py-2 pr-4 text-right font-bold">xGD</th>
                <th className="py-2 pr-4 font-bold">Finishing</th>
                <th className="py-2 font-bold">Keeping</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.team_id}
                    className={`border-b border-divider transition-colors hover:bg-raised/60 ${r.mine ? 'border-l-2 border-l-broadcast-gold' : ''}`}
                    onMouseEnter={() => setHover(r.team_id)} onMouseLeave={() => setHover(null)}>
                  <td className="tabular py-2 pr-3 text-text-faint">{r.position}</td>
                  <td className="py-2 pr-4">
                    <Link to={`/club/${r.team_id}`} className="flex items-center gap-2 font-bold text-text hover:underline">
                      {crestUrl(r.code) && <img src={crestUrl(r.code) as string} alt="" className="h-5 w-5" />}
                      {r.name}
                    </Link>
                  </td>
                  <td className="tabular py-2 pr-3 text-right text-text-muted">{r.played}</td>
                  <td className="tabular py-2 pr-3 text-right text-text-muted">{r.won}</td>
                  <td className="tabular py-2 pr-3 text-right text-text-muted">{r.drawn}</td>
                  <td className="tabular py-2 pr-3 text-right text-text-muted">{r.lost}</td>
                  <td className="tabular py-2 pr-3 text-right text-text">{r.gf}</td>
                  <td className="tabular py-2 pr-3 text-right text-text">{r.ga}</td>
                  <td className={`tabular py-2 pr-3 text-right ${r.gd > 0 ? 'text-pitch-green' : r.gd < 0 ? 'text-alert-red' : 'text-text-muted'}`}>{r.gd > 0 ? '+' : ''}{r.gd}</td>
                  <td className="tabular py-2 pr-4 text-right font-display text-lg font-bold text-text">{r.points}</td>
                  <td className="py-2 pr-4"><FormDots form={r.form} /></td>
                  <td className="tabular py-2 pr-3 text-right text-pitch-green">{r.xg.toFixed(1)}</td>
                  <td className="tabular py-2 pr-3 text-right text-alert-red">{r.xga.toFixed(1)}</td>
                  <td className={`tabular py-2 pr-4 text-right font-semibold ${r.xgd > 0 ? 'text-pitch-green' : r.xgd < 0 ? 'text-alert-red' : 'text-text-muted'}`}>{r.xgd > 0 ? '+' : ''}{r.xgd.toFixed(1)}</td>
                  <td className="py-2 pr-4"><Diverge v={r.finishing} scale={divScale} /></td>
                  <td className="py-2"><Diverge v={r.keeping} scale={divScale} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 max-w-3xl text-[11px] leading-relaxed text-text-faint">{d.method}</p>
      </div>
    </div>
  )
}

function Stat({ label, v, sub, tone = 'text-text' }: { label: string; v: string; sub?: string; tone?: string }) {
  return (
    <div>
      <div className={`tabular font-display text-2xl font-bold ${tone}`}>{v}</div>
      <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">{label}</div>
      {sub && <div className="tabular text-[10px] text-text-muted">{sub}</div>}
    </div>
  )
}

function ordinal(n: number) {
  const s = ['th', 'st', 'nd', 'rd'], v = n % 100
  return s[(v - 20) % 10] ?? s[v] ?? s[0]
}
