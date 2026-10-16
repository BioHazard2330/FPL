interface Series {
  key: string
  label: string
  hist: number[]
  color: string
}

const W = 720
const H = 200
const PAD = { l: 8, r: 8, t: 14, b: 26 }

/** The spread of "you minus the average manager" for one or more choices, drawn
 * as filled densities over the same axis. Right of the vertical rule you beat
 * the field in that trial; left of it you lose ground. The mass on each side and
 * the width of the hump are the point: two choices with the same mean can be a
 * narrow hump and a wide one. Flat fills, one rule, no decoration. */
export function EdgeDensity({ series, min, max, height = H }: { series: Series[]; min: number; max: number; height?: number }) {
  if (series.length === 0) return null
  const bins = series[0].hist.length
  const top = Math.max(...series.flatMap((s) => s.hist), 0.001) * 1.1
  const x = (v: number) => PAD.l + ((v - min) / (max - min)) * (W - PAD.l - PAD.r)
  const y = (v: number) => height - PAD.b - (v / top) * (height - PAD.t - PAD.b)
  const step = (max - min) / bins
  const path = (hist: number[]) => {
    let d = `M ${x(min)} ${y(0)}`
    hist.forEach((v, i) => {
      d += ` L ${x(min + i * step)} ${y(v)} L ${x(min + (i + 1) * step)} ${y(v)}`
    })
    return `${d} L ${x(max)} ${y(0)} Z`
  }
  const ticks = [-40, -30, -20, -10, 0, 10, 20, 30, 40].filter((t) => t >= min && t <= max)
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="h-auto w-full select-none" role="img" aria-label="Distribution of points against the field">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={PAD.t} y2={height - PAD.b} stroke="var(--divider)" strokeOpacity={t === 0 ? 0 : 0.5} />
          <text x={x(t)} y={height - 8} textAnchor="middle" fontSize={10} fill="var(--text-faint)" className="tabular">{t > 0 ? `+${t}` : t}</text>
        </g>
      ))}
      {series.map((s) => (
        <path key={s.key} d={path(s.hist)} fill={s.color} fillOpacity={series.length > 1 ? 0.35 : 0.6} stroke={s.color} strokeWidth={1.5} />
      ))}
      <line x1={x(0)} x2={x(0)} y1={PAD.t - 4} y2={height - PAD.b} stroke="var(--text)" strokeWidth={1.5} />
      <text x={x(0) + 6} y={PAD.t + 4} fontSize={10} fill="var(--text-muted)">beat the field</text>
      <text x={x(0) - 6} y={PAD.t + 4} fontSize={10} textAnchor="end" fill="var(--text-muted)">lose ground</text>
    </svg>
  )
}
