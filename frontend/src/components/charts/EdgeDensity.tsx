import { useId } from 'react'

interface Series {
  key: string
  label: string
  hist: number[]
  color: string
}

const W = 720
const H = 200
const PAD = { l: 8, r: 8, t: 22, b: 26 }

/** The spread of "you minus the average manager" for one or more choices, drawn as smooth densities over the same axis. Right
 * of the vertical rule you beat the field in that trial; left of it you lose ground, and that side is drawn in red so the
 * two halves read at a glance. The share of trials on each side and the width of the hump are the point: two choices with the
 * same mean can be a narrow hump and a wide one. */
export function EdgeDensity({ series, min, max, height = H }: { series: Series[]; min: number; max: number; height?: number }) {
  const uid = useId().replace(/:/g, '')
  if (series.length === 0) return null
  const bins = series[0].hist.length
  const top = Math.max(...series.flatMap((s) => s.hist), 0.001) * 1.12
  const x = (v: number) => PAD.l + ((v - min) / (max - min)) * (W - PAD.l - PAD.r)
  const y = (v: number) => height - PAD.b - (v / top) * (height - PAD.t - PAD.b)
  const step = (max - min) / bins
  const baseY = y(0)

  const curve = (hist: number[]) => {
    const pts: [number, number][] = [[x(min), baseY], ...hist.map((v, i) => [x(min + (i + 0.5) * step), y(v)] as [number, number]), [x(max), baseY]]
    let d = `M ${pts[0][0]} ${pts[0][1]}`
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(i - 1, 0)]
      const p1 = pts[i]
      const p2 = pts[i + 1]
      const p3 = pts[Math.min(i + 2, pts.length - 1)]
      const c1: [number, number] = [p1[0] + (p2[0] - p0[0]) / 6, Math.min(p1[1] + (p2[1] - p0[1]) / 6, baseY)]
      const c2: [number, number] = [p2[0] - (p3[0] - p1[0]) / 6, Math.min(p2[1] - (p3[1] - p1[1]) / 6, baseY)]
      d += ` C ${c1[0]} ${c1[1]} ${c2[0]} ${c2[1]} ${p2[0]} ${p2[1]}`
    }
    return d
  }
  const ticks = [-40, -30, -20, -10, 0, 10, 20, 30, 40].filter((t) => t >= min && t <= max)
  const zeroX = x(0)
  const first = series[0]
  const total = first.hist.reduce((a, b) => a + b, 0) || 1
  const behind = first.hist.reduce((a, v, i) => (min + (i + 0.5) * step < 0 ? a + v : a), 0) / total

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="h-auto w-full select-none" role="img" aria-label="Distribution of points against the field">
      <defs>
        {series.map((s) => (
          <linearGradient key={s.key} id={`${uid}-g-${s.key}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={s.color} stopOpacity={series.length > 1 ? 0.5 : 0.7} />
            <stop offset="100%" stopColor={s.color} stopOpacity={0.04} />
          </linearGradient>
        ))}
        <linearGradient id={`${uid}-red`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--alert-red)" stopOpacity={0.6} />
          <stop offset="100%" stopColor="var(--alert-red)" stopOpacity={0.04} />
        </linearGradient>
        <clipPath id={`${uid}-right`}><rect x={zeroX} y={0} width={W - zeroX} height={height} /></clipPath>
        <clipPath id={`${uid}-left`}><rect x={0} y={0} width={zeroX} height={height} /></clipPath>
      </defs>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={PAD.t} y2={height - PAD.b} stroke="var(--divider)" strokeDasharray="3 4" strokeOpacity={t === 0 ? 0 : 0.7} />
          <text x={x(t)} y={height - 8} textAnchor="middle" fontSize={10} fill="var(--text-faint)" className="tabular">{t > 0 ? `+${t}` : t}</text>
        </g>
      ))}
      {series.map((s) => {
        const d = curve(s.hist)
        return (
          <g key={s.key}>
            <g clipPath={`url(#${uid}-right)`}>
              <path d={`${d} Z`} fill={`url(#${uid}-g-${s.key})`} />
              <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinecap="round" />
            </g>
            <g clipPath={`url(#${uid}-left)`}>
              <path d={`${d} Z`} fill={series.length === 1 ? `url(#${uid}-red)` : `url(#${uid}-g-${s.key})`} />
              <path d={d} fill="none" stroke={series.length === 1 ? 'var(--alert-red)' : s.color} strokeWidth={2} strokeLinecap="round" />
            </g>
          </g>
        )
      })}
      <line x1={zeroX} x2={zeroX} y1={PAD.t - 6} y2={height - PAD.b} stroke="var(--text)" strokeWidth={1.25} strokeDasharray="4 3" />
      <text x={zeroX + 8} y={PAD.t - 8} fontSize={11} fontWeight={600} fill="var(--text-muted)">
        ahead of the field {Math.round((1 - behind) * 100)}%
      </text>
      <text x={zeroX - 8} y={PAD.t - 8} fontSize={11} fontWeight={600} textAnchor="end" fill="var(--text-muted)">
        behind {Math.round(behind * 100)}%
      </text>
    </svg>
  )
}
