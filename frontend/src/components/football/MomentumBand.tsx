/** Real FotMob momentum, drawn as a two-sided pressure band off the
 * baseline: above = home, below = away, on the raw -100..100 scale the
 * feed already reports. No smoothing and no interpolation across minutes
 * the feed never sent - the polyline only connects real samples.
 *
 * Redesigned 2026-09-12 (direct user comparison against FotMob's own match
 * page: "the fucking momentum tab is so fucking bad compared to fotmob") -
 * the prior version was a 34px-tall sliver at 35% fill opacity, reading as
 * decorative background rather than the real per-minute pressure signal it
 * is. FotMob's own chart is a full-height, near-opaque, jagged mountain
 * band with real 0'/HT/FT axis labels and a live "now" marker - this
 * matches that visual weight with this project's own palette (never
 * FotMob's literal blue/orange), same real data, no fabrication.
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

const MARKER_RADIUS: Record<MomentumMarker['kind'], number> = {
  Goal: 2.6, Penalty: 2.6, OwnGoal: 2.6, MissedPenalty: 1.8, Card: 1.4, VAR: 1.6,
}

export function MomentumBand({ points, markers = [], maxMinuteOverride, isLive = false }: {
  points: { minute: number; value: number }[]
  markers?: MomentumMarker[]
  maxMinuteOverride?: number
  /** Draws a "now" marker at the last real sample - only meaningful while
   * the match is genuinely still being played. */
  isLive?: boolean
}) {
  if (points.length < 2) return null
  const maxMinute = maxMinuteOverride ?? Math.max(...points.map((p) => p.minute), 1)
  const W = 100
  const H = 140
  const mid = H / 2
  const xy = points.map((p) => [
    (p.minute / maxMinute) * W,
    mid - (Math.max(-100, Math.min(100, p.value)) / 100) * mid,
  ] as const)
  const homeArea = `0,${mid} ${xy.map(([x, y]) => `${x.toFixed(2)},${Math.min(y, mid).toFixed(2)}`).join(' ')} ${W},${mid}`
  const awayArea = `0,${mid} ${xy.map(([x, y]) => `${x.toFixed(2)},${Math.max(y, mid).toFixed(2)}`).join(' ')} ${W},${mid}`
  const lastPoint = xy[xy.length - 1]
  const htX = 45 <= maxMinute ? (45 / maxMinute) * W : null

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">Momentum</span>
        <span className="text-[9px] uppercase tracking-wide text-text-faint">to {maxMinute}&prime;</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-[150px] w-full" role="img" aria-label="Match momentum: home pressure above the line, away below, with real goal/card markers">
        <polygon points={homeArea} fill="var(--pitch-green)" opacity="0.9" />
        <polygon points={awayArea} fill="var(--broadcast-blue)" opacity="0.9" />
        {/* `--void` (near-black) was the original bug here - it matches the
            panel background almost exactly, so the zero baseline and HT
            divider were both effectively invisible, leaving the shape read
            as noise with no reference line. `--divider` is this app's own
            real, visible rule color. */}
        <line x1="0" y1={mid} x2={W} y2={mid} stroke="var(--divider)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {htX !== null && (
          <line x1={htX} y1="0" x2={htX} y2={H} stroke="var(--divider)" strokeWidth="0.8" strokeDasharray="2,2" vectorEffect="non-scaling-stroke" />
        )}
        {isLive && lastPoint && (
          <>
            <line x1={lastPoint[0]} y1="0" x2={lastPoint[0]} y2={H} stroke="var(--text)" strokeWidth="0.8" strokeDasharray="1.5,1.5" vectorEffect="non-scaling-stroke" />
            <circle cx={lastPoint[0]} cy={lastPoint[1]} r="2.2" fill="var(--text)" />
          </>
        )}
        {markers.map((m, i) => {
          const x = Math.max(0, Math.min(W, (m.minute / maxMinute) * W))
          const y = m.isHome ? mid * 0.18 : mid * 1.82
          return (
            <g key={i}>
              <line x1={x} y1="0" x2={x} y2={H} stroke={MARKER_COLOR[m.kind]} strokeWidth="0.6" opacity="0.5" vectorEffect="non-scaling-stroke" />
              <circle cx={x} cy={y} r={MARKER_RADIUS[m.kind] + 0.6} fill={MARKER_COLOR[m.kind]} stroke="var(--void)" strokeWidth="0.8">
                <title>{m.kind} {m.minute}&apos;</title>
              </circle>
            </g>
          )
        })}
      </svg>
      <div className="mt-1.5 flex justify-between text-[10px] font-semibold uppercase tracking-wide text-text-faint">
        <span>0&prime;</span>
        {htX !== null && <span>HT</span>}
        <span>{isLive ? `${points[points.length - 1].minute}′` : 'FT'}</span>
      </div>
    </div>
  )
}
