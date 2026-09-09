/** Real FotMob momentum, drawn as a two-sided pressure band off the
 * baseline: above = home, below = away, on the raw -100..100 scale the
 * feed already reports. No smoothing and no interpolation across minutes
 * the feed never sent - the polyline only connects real samples.
 *
 * `markers` (optional) overlays real goal/card events at their real minute
 * directly on the band - the "one timeline instead of two panels" fix: a
 * match report used to need a separate events list underneath this band to
 * say when anything happened; now the band itself shows it, at the exact
 * moment the pressure shifted. Every marker is a real, already-parsed
 * timeline event - never inferred from the momentum shape itself. */
export interface MomentumMarker {
  minute: number
  isHome: boolean
  kind: 'Goal' | 'Card' | 'OwnGoal' | 'MissedPenalty' | 'Penalty' | 'VAR'
}

const MARKER_COLOR: Record<MomentumMarker['kind'], string> = {
  Goal: 'var(--pitch-green)',
  Penalty: 'var(--pitch-green)',
  OwnGoal: 'var(--alert-red)',
  MissedPenalty: 'var(--alert-red)',
  Card: 'var(--broadcast-gold)',
  VAR: 'var(--broadcast-blue)',
}

export function MomentumBand({ points, markers = [], maxMinuteOverride }: {
  points: { minute: number; value: number }[]
  markers?: MomentumMarker[]
  maxMinuteOverride?: number
}) {
  if (points.length < 2) return null
  const maxMinute = maxMinuteOverride ?? Math.max(...points.map((p) => p.minute), 1)
  const W = 100
  const H = 34
  const mid = H / 2
  const xy = points.map((p) => [
    (p.minute / maxMinute) * W,
    mid - (Math.max(-100, Math.min(100, p.value)) / 100) * mid,
  ] as const)
  const line = xy.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ')
  const homeArea = `0,${mid} ${xy.map(([x, y]) => `${x.toFixed(2)},${Math.min(y, mid).toFixed(2)}`).join(' ')} ${W},${mid}`
  const awayArea = `0,${mid} ${xy.map(([x, y]) => `${x.toFixed(2)},${Math.max(y, mid).toFixed(2)}`).join(' ')} ${W},${mid}`
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">Momentum</span>
        <span className="text-[9px] uppercase tracking-wide text-text-faint">to {maxMinute}&prime;</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-9 w-full" role="img" aria-label="Match momentum: home pressure above the line, away below, with real goal/card markers">
        <polygon points={homeArea} fill="var(--pitch-green)" opacity="0.35" />
        <polygon points={awayArea} fill="var(--broadcast-blue)" opacity="0.35" />
        <line x1="0" y1={mid} x2={W} y2={mid} stroke="var(--divider)" strokeWidth="0.6" vectorEffect="non-scaling-stroke" />
        <polyline points={line} fill="none" stroke="var(--text-muted)" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
        {markers.map((m, i) => {
          const x = Math.max(0, Math.min(W, (m.minute / maxMinute) * W))
          const y = m.isHome ? mid * 0.35 : mid * 1.65
          return (
            <g key={i}>
              <line x1={x} y1="0" x2={x} y2={H} stroke={MARKER_COLOR[m.kind]} strokeWidth="0.5" opacity="0.5" vectorEffect="non-scaling-stroke" />
              <circle cx={x} cy={y} r="1.6" fill={MARKER_COLOR[m.kind]}>
                <title>{m.kind} {m.minute}&apos;</title>
              </circle>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
