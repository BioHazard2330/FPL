import { useMemo, useState } from 'react'
import type { CalibrationBlock, CalibrationPoint } from '@/lib/types'

/** MODEL vs REALITY - every prediction the model has committed to,
 * against what happened.
 *
 * The horizontal axis is what the model said before the deadline; the
 * vertical is what the player actually scored. A perfect model is the
 * diagonal. The shaded band either side of it is one standard deviation of
 * the model's own measured error - the exact figure the transfer
 * materiality bar is derived from - so "inside the noise" is something you
 * can see against real dots instead of taking as a number.
 *
 * Nothing here flatters. Dots above the line are players the model
 * undersold; below, players it oversold. The vertical whisker on hover is
 * the floor-to-ceiling range the model stated for that player that week,
 * and the coverage figure says how often reality landed inside it. */

const PAD = { l: 40, r: 16, t: 14, b: 34 }
const VW = 640
const VH = 380

export function ModelVsReality({ block }: { block: CalibrationBlock }) {
  const [hover, setHover] = useState<CalibrationPoint | null>(null)

  const max = useMemo(
    () => Math.max(...block.points.map((p) => Math.max(p.predicted, p.actual, p.ceiling ?? 0)), 6) + 1,
    [block.points],
  )
  const sx = (v: number) => PAD.l + (v / max) * (VW - PAD.l - PAD.r)
  const sy = (v: number) => VH - PAD.b - (v / max) * (VH - PAD.t - PAD.b)
  const ticks = useMemo(() => {
    const step = max > 20 ? 5 : 2
    const out: number[] = []
    for (let v = 0; v <= max; v += step) out.push(v)
    return out
  }, [max])

  // The band polygon: y = x ± stdev, clipped to the plot.
  const sd = block.error_stdev
  const band = [
    [0, sd], [max, max + sd], [max, max - sd], [0, -sd],
  ].map(([x, y]) => `${sx(x).toFixed(1)},${sy(Math.max(0, Math.min(max, y))).toFixed(1)}`).join(' ')

  return (
    <div className="grid grid-cols-[1fr_260px] gap-8">
      <div className="relative">
        <svg viewBox={`0 0 ${VW} ${VH}`} className="h-auto w-full" role="img"
             aria-label="Predicted points against actual points, one dot per player-gameweek"
             onMouseLeave={() => setHover(null)}>
          <polygon points={band} fill="var(--broadcast-gold)" fillOpacity={0.10} />
          <line x1={sx(0)} y1={sy(0)} x2={sx(max)} y2={sy(max)} stroke="var(--text)" strokeOpacity={0.35} strokeWidth={1} strokeDasharray="4 4" />

          {ticks.map((v) => (
            <g key={v}>
              <line x1={sx(v)} y1={sy(0)} x2={sx(v)} y2={sy(0) + 4} stroke="var(--divider)" />
              <text x={sx(v)} y={sy(0) + 14} textAnchor="middle" fontSize={9} fill="var(--text-faint)">{v}</text>
              <line x1={sx(0) - 4} y1={sy(v)} x2={sx(0)} y2={sy(v)} stroke="var(--divider)" />
              <text x={sx(0) - 7} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="var(--text-faint)">{v}</text>
            </g>
          ))}
          <line x1={sx(0)} y1={sy(0)} x2={sx(max)} y2={sy(0)} stroke="var(--divider)" />
          <line x1={sx(0)} y1={sy(0)} x2={sx(0)} y2={sy(max)} stroke="var(--divider)" />
          <text x={sx(max / 2)} y={VH - 4} textAnchor="middle" fontSize={9} fill="var(--text-faint)" letterSpacing="1.5">PREDICTED BEFORE THE DEADLINE</text>
          <text x={10} y={sy(max / 2)} textAnchor="middle" fontSize={9} fill="var(--text-faint)" letterSpacing="1.5" transform={`rotate(-90 10 ${sy(max / 2)})`}>ACTUAL POINTS</text>

          {hover && hover.floor !== null && hover.ceiling !== null && (
            <line x1={sx(hover.predicted)} y1={sy(hover.floor)} x2={sx(hover.predicted)} y2={sy(hover.ceiling)}
                  stroke="var(--broadcast-gold)" strokeWidth={2} strokeOpacity={0.8} />
          )}

          {block.points.map((p, i) => {
            const above = p.actual > p.predicted
            const dim = hover !== null && hover !== p
            return (
              <circle
                key={`${p.player_id}-${p.event}-${i}`}
                cx={sx(p.predicted)} cy={sy(p.actual)} r={hover === p ? 6 : 4}
                fill={above ? 'var(--pitch-green)' : 'var(--alert-red)'}
                fillOpacity={dim ? 0.25 : 0.85}
                stroke="var(--void)" strokeWidth={1}
                className="cursor-crosshair transition-opacity duration-150"
                onMouseEnter={() => setHover(p)}
                onMouseMove={() => setHover(p)}
              />
            )
          })}
        </svg>
      </div>

      <div className="space-y-5">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">Measured error</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="tabular font-display text-3xl font-bold text-text">{block.mae.toFixed(2)}</span>
            <span className="text-[10px] uppercase tracking-wide text-text-faint">pts off, on average</span>
          </div>
          <div className="mt-1 text-xs text-text-muted">
            per player per gameweek, over <span className="tabular font-semibold text-text">{block.n}</span> settled predictions
          </div>
        </div>

        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">Lean</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className={`tabular font-display text-3xl font-bold ${block.bias > 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
              {block.bias > 0 ? '+' : ''}{block.bias.toFixed(2)}
            </span>
            <span className="text-[10px] uppercase tracking-wide text-text-faint">
              {block.bias > 0 ? 'it undersells' : 'it oversells'}
            </span>
          </div>
          <div className="mt-1 text-xs text-text-muted">
            reality minus prediction, averaged. Positive means players score more than it says.
          </div>
        </div>

        {block.band_coverage_pct !== null && (
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">Its own range held</div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="tabular font-display text-3xl font-bold text-text">{block.band_coverage_pct}%</span>
              <span className="text-[10px] uppercase tracking-wide text-text-faint">of the time</span>
            </div>
            <div className="mt-1 text-xs text-text-muted">
              how often the real score fell inside the floor-to-ceiling range it stated. Hover a dot to see that range.
            </div>
          </div>
        )}

        <div className="border-t border-divider pt-4">
          {hover ? (
            <div>
              <div className="text-sm font-semibold text-text">{hover.player} <span className="text-text-faint">GW{hover.event}</span></div>
              <div className="tabular mt-1 text-xs text-text-muted">
                said <span className="font-semibold text-text">{hover.predicted.toFixed(1)}</span>
                {hover.floor !== null && hover.ceiling !== null && <span className="text-text-faint"> ({hover.floor.toFixed(0)}–{hover.ceiling.toFixed(0)})</span>}
                {' · '}got <span className={`font-semibold ${hover.actual > hover.predicted ? 'text-pitch-green' : 'text-alert-red'}`}>{hover.actual.toFixed(0)}</span>
                {hover.minutes !== null && <span className="text-text-faint"> · {hover.minutes}'</span>}
              </div>
              <div className="mt-1 text-[10px] uppercase tracking-wide text-text-faint">
                {hover.confidence ? `${hover.confidence} confidence` : ''}{hover.inside_band ? ' · inside its range' : ' · outside its range'}
              </div>
            </div>
          ) : (
            <div className="text-[10px] uppercase tracking-wide text-text-faint">hover a dot</div>
          )}
        </div>

        <div className="text-[10px] leading-relaxed text-text-faint">
          <span className="mr-1 inline-block size-2 rounded-full bg-pitch-green align-middle" />scored more than predicted
          <span className="ml-3 mr-1 inline-block size-2 rounded-full bg-alert-red align-middle" />scored less
          <span className="ml-3 mr-1 inline-block h-2 w-3 bg-broadcast-gold/30 align-middle" />±1 sd of measured error
        </div>
      </div>
    </div>
  )
}
