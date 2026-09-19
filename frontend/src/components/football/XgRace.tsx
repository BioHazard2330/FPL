import { useMemo, useState } from 'react'
import type { CareerMatch } from '@/lib/types'

/** THE RACE - cumulative goals against cumulative xG, every match he has
 * played across every season this database holds.
 *
 * The xG line is what the chances he got were worth; the goals step is what
 * he made of them. The gap between the two is the whole story of a
 * finisher: filled green while he runs above his chances, red while he
 * runs below. Nothing is smoothed and nothing is projected - the last
 * point is the last match he played.
 *
 * Season boundaries are drawn because a reader would otherwise treat a gap
 * of three months as a run of matches. */

type Mode = 'goals' | 'assists'

const VW = 960
const VH = 300
const PAD = { l: 44, r: 20, t: 18, b: 30 }

function shortDate(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getDate()} ${d.toLocaleString([], { month: 'short' })} ${String(d.getFullYear()).slice(2)}`
}

export function XgRace({ career, thisSeason }: { career: CareerMatch[]; thisSeason: string | null }) {
  const [mode, setMode] = useState<Mode>('goals')
  const [hover, setHover] = useState<number | null>(null)

  const rows = useMemo(() => {
    let g = 0, x = 0
    return career.map((m, i) => {
      g += mode === 'goals' ? m.goals : m.assists
      x += mode === 'goals' ? m.xg : m.xa
      return { i, m, actual: g, expected: x }
    })
  }, [career, mode])

  const n = rows.length
  const max = Math.max(1, ...rows.map((r) => Math.max(r.actual, r.expected))) * 1.06
  const sx = (i: number) => PAD.l + (n <= 1 ? 0 : (i / (n - 1)) * (VW - PAD.l - PAD.r))
  const sy = (v: number) => VH - PAD.b - (v / max) * (VH - PAD.t - PAD.b)

  const seasons = useMemo(() => {
    const out: { season: string; from: number; to: number }[] = []
    rows.forEach((r) => {
      const last = out[out.length - 1]
      if (last && last.season === r.m.season) last.to = r.i
      else out.push({ season: r.m.season, from: r.i, to: r.i })
    })
    return out
  }, [rows])

  // Step path for the actual count: horizontal to the next index, then up.
  const stepPath = useMemo(() => {
    if (!n) return ''
    let d = `M ${sx(0)} ${sy(0)}`
    rows.forEach((r) => { d += ` L ${sx(r.i)} ${sy(r.actual)}` })
    return d
  }, [rows, n, max])
  const linePath = useMemo(() => {
    if (!n) return ''
    return rows.map((r, k) => `${k === 0 ? 'M' : 'L'} ${sx(r.i)} ${sy(r.expected)}`).join(' ')
  }, [rows, n, max])

  // The gap: two polygons clipped by sign. Above = actual > expected.
  const bandAbove = useMemo(() => {
    if (!n) return ''
    const top = rows.map((r) => `${sx(r.i)},${sy(Math.max(r.actual, r.expected))}`)
    const bottom = rows.slice().reverse().map((r) => `${sx(r.i)},${sy(r.expected)}`)
    return [...top, ...bottom].join(' ')
  }, [rows, n, max])
  const bandBelow = useMemo(() => {
    if (!n) return ''
    const top = rows.map((r) => `${sx(r.i)},${sy(r.expected)}`)
    const bottom = rows.slice().reverse().map((r) => `${sx(r.i)},${sy(Math.min(r.actual, r.expected))}`)
    return [...top, ...bottom].join(' ')
  }, [rows, n, max])

  const last = rows[n - 1]
  const seasonRows = rows.filter((r) => r.m.season === thisSeason)
  const seasonActual = seasonRows.reduce((a, r) => a + (mode === 'goals' ? r.m.goals : r.m.assists), 0)
  const seasonExpected = seasonRows.reduce((a, r) => a + (mode === 'goals' ? r.m.xg : r.m.xa), 0)

  const ticks = useMemo(() => {
    const step = max > 80 ? 20 : max > 40 ? 10 : max > 16 ? 5 : 2
    const out: number[] = []
    for (let v = 0; v <= max; v += step) out.push(v)
    return out
  }, [max])

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * VW
    const i = Math.round(((px - PAD.l) / (VW - PAD.l - PAD.r)) * (n - 1))
    setHover(Math.max(0, Math.min(n - 1, i)))
  }
  const h = hover !== null ? rows[hover] : null
  const label = mode === 'goals' ? { a: 'goals', e: 'xG' } : { a: 'assists', e: 'xA' }

  if (!n) return null

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-4">
        <div className="flex border border-divider">
          {(['goals', 'assists'] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] transition-colors ${mode === m ? 'bg-text text-void' : 'text-text-muted hover:text-text'}`}
            >
              {m === 'goals' ? 'Goals v xG' : 'Assists v xA'}
            </button>
          ))}
        </div>
        <span className="flex items-center gap-1.5 text-[11px] text-text-muted"><span className="h-0.5 w-4 bg-text" /> {label.a}</span>
        <span className="flex items-center gap-1.5 text-[11px] text-text-muted"><span className="h-0.5 w-4 bg-pitch-green" /> {label.e}</span>
        <span className="flex items-center gap-1.5 text-[11px] text-text-muted"><span className="h-2 w-3 bg-pitch-green/30" /> above his chances</span>
        <span className="flex items-center gap-1.5 text-[11px] text-text-muted"><span className="h-2 w-3 bg-alert-red/30" /> below</span>
        <span className="ml-auto text-[11px] text-text-faint">{n} matches, {seasons.length} seasons</span>
      </div>

      <div className="grid grid-cols-[1fr_240px] gap-8">
        <svg viewBox={`0 0 ${VW} ${VH}`} className="h-auto w-full select-none" role="img"
             aria-label={`Cumulative ${label.a} against cumulative ${label.e} across every match`}
             onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
          {seasons.map((s, k) => (
            <g key={s.season}>
              {k > 0 && <line x1={sx(s.from) - 0.5} y1={PAD.t} x2={sx(s.from) - 0.5} y2={VH - PAD.b} stroke="var(--divider)" strokeWidth={1} />}
              <text x={sx(s.from) + 4} y={PAD.t + 9} fontSize={9} fill="var(--text-faint)" letterSpacing="1.2" fontWeight={700}>
                {s.season.toUpperCase()}
              </text>
            </g>
          ))}
          {ticks.map((v) => (
            <g key={v}>
              <line x1={PAD.l} y1={sy(v)} x2={VW - PAD.r} y2={sy(v)} stroke="var(--divider)" strokeOpacity={0.5} />
              <text x={PAD.l - 8} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="var(--text-faint)" className="tabular">{v}</text>
            </g>
          ))}
          <polygon points={bandAbove} fill="var(--pitch-green)" fillOpacity={0.28} />
          <polygon points={bandBelow} fill="var(--alert-red)" fillOpacity={0.28} />
          <path d={linePath} fill="none" stroke="var(--pitch-green)" strokeWidth={1.8} strokeLinejoin="round" />
          <path d={stepPath} fill="none" stroke="var(--text)" strokeWidth={2} strokeLinejoin="round" />
          {rows.map((r, k) => {
            const scored = mode === 'goals' ? r.m.goals : r.m.assists
            return scored > 0 ? <circle key={k} cx={sx(r.i)} cy={sy(r.actual)} r={2.4} fill="var(--text)" /> : null
          })}
          {h && (
            <g>
              <line x1={sx(h.i)} y1={PAD.t} x2={sx(h.i)} y2={VH - PAD.b} stroke="var(--text)" strokeOpacity={0.5} strokeDasharray="3 3" />
              <circle cx={sx(h.i)} cy={sy(h.actual)} r={4} fill="var(--text)" stroke="var(--void)" strokeWidth={1.5} />
              <circle cx={sx(h.i)} cy={sy(h.expected)} r={4} fill="var(--pitch-green)" stroke="var(--void)" strokeWidth={1.5} />
            </g>
          )}
          <line x1={PAD.l} y1={VH - PAD.b} x2={VW - PAD.r} y2={VH - PAD.b} stroke="var(--divider)" />
          <text x={PAD.l} y={VH - 8} fontSize={9} fill="var(--text-faint)" className="tabular">{shortDate(rows[0].m.match_date)}</text>
          <text x={VW - PAD.r} y={VH - 8} fontSize={9} fill="var(--text-faint)" textAnchor="end" className="tabular">{shortDate(last.m.match_date)}</text>
        </svg>

        <div className="space-y-5">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">All matches on record</div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="tabular font-display text-4xl font-bold text-text">{last.actual}</span>
              <span className="text-[10px] uppercase tracking-wide text-text-faint">{label.a}</span>
              <span className="tabular font-display text-2xl font-bold text-pitch-green">{last.expected.toFixed(1)}</span>
              <span className="text-[10px] uppercase tracking-wide text-text-faint">{label.e}</span>
            </div>
            <Delta value={last.actual - last.expected} />
          </div>
          {thisSeason && seasonRows.length > 0 && (
            <div>
              <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">This season, {seasonRows.length} matches</div>
              <div className="mt-1 flex items-baseline gap-3">
                <span className="tabular font-display text-4xl font-bold text-text">{seasonActual}</span>
                <span className="text-[10px] uppercase tracking-wide text-text-faint">{label.a}</span>
                <span className="tabular font-display text-2xl font-bold text-pitch-green">{seasonExpected.toFixed(1)}</span>
                <span className="text-[10px] uppercase tracking-wide text-text-faint">{label.e}</span>
              </div>
              <Delta value={seasonActual - seasonExpected} />
            </div>
          )}
          <div className="border-t border-divider pt-4">
            {h ? (
              <div>
                <div className="text-sm font-semibold text-text">{shortDate(h.m.match_date)} <span className="text-text-faint">{h.m.season}</span></div>
                <div className="tabular mt-1 text-xs text-text-muted">
                  this match: <span className="font-semibold text-text">{mode === 'goals' ? h.m.goals : h.m.assists}</span> {label.a}
                  {' from '}<span className="font-semibold text-pitch-green">{(mode === 'goals' ? h.m.xg : h.m.xa).toFixed(2)}</span> {label.e}
                  {' · '}{h.m.minutes}'{h.m.shots ? ` · ${h.m.shots} shots` : ''}
                </div>
                <div className="tabular mt-1 text-xs text-text-muted">
                  to date: <span className="font-semibold text-text">{h.actual}</span> v <span className="font-semibold text-pitch-green">{h.expected.toFixed(1)}</span>
                  {' '}<span className={h.actual - h.expected >= 0 ? 'text-pitch-green' : 'text-alert-red'}>({h.actual - h.expected >= 0 ? '+' : ''}{(h.actual - h.expected).toFixed(1)})</span>
                </div>
              </div>
            ) : (
              <div className="text-[10px] uppercase tracking-wide text-text-faint">hover the race</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Delta({ value }: { value: number }) {
  const up = value >= 0
  return (
    <div className={`tabular mt-1 text-xs font-semibold ${up ? 'text-pitch-green' : 'text-alert-red'}`}>
      {up ? '+' : ''}{value.toFixed(1)} <span className="font-normal text-text-faint">{up ? 'above his chances' : 'below his chances'}</span>
    </div>
  )
}
