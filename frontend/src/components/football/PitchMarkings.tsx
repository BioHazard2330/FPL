/** Real pitch geometry, drawn to scale.
 *
 * The squad pitch previously had mowed stripes, a halfway line and a centre
 * circle - enough to read as "green rectangle", not enough to read as a
 * football pitch. This draws the actual markings at real proportions
 * (a 68m x 105m pitch, penalty area 40.32m x 16.5m, six-yard box 18.32m x
 * 5.5m, centre circle and D arc both 9.15m radius, corner arcs 1m), in a
 * portrait orientation because a squad list runs goalkeeper-at-the-top.
 *
 * Purely decorative in the honest sense: it encodes no data and claims
 * nothing. It is geometry, so it is drawn once as flat hairlines and never
 * animated. `preserveAspectRatio="none"` lets it stretch to whatever box the
 * squad rows need without the markings drifting out of the container.
 */
const W = 680
const H = 1050
const CX = W / 2

const PEN_W = 403.2
const PEN_H = 165
const SIX_W = 183.2
const SIX_H = 55
const SPOT = 110
const R = 91.5
const GOAL_W = 73.2

const penX = CX - PEN_W / 2
const sixX = CX - SIX_W / 2
const goalX = CX - GOAL_W / 2

/** The D: the part of a 9.15m circle around the penalty spot that falls
 * outside the penalty area. Drawn as an explicit arc rather than a clipped
 * circle so it stays a single hairline path at any stretch factor. */
function dArc(top: boolean): string {
  const y = top ? PEN_H : H - PEN_H
  const dx = Math.sqrt(Math.max(0, R * R - (PEN_H - SPOT) ** 2))
  const sweep = top ? 1 : 0
  return `M ${CX - dx} ${y} A ${R} ${R} 0 0 ${sweep} ${CX + dx} ${y}`
}

export function PitchMarkings({ className = '' }: { className?: string }) {
  const line = 'var(--pitch-line, color-mix(in srgb, var(--text) 12%, transparent))'
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      className={`pointer-events-none absolute inset-0 h-full w-full ${className}`}
      fill="none"
      stroke={line}
      strokeWidth="2.5"
      vectorEffect="non-scaling-stroke"
    >
      <rect x="6" y="6" width={W - 12} height={H - 12} />
      <line x1="6" y1={H / 2} x2={W - 6} y2={H / 2} />
      <circle cx={CX} cy={H / 2} r={R} />
      <circle cx={CX} cy={H / 2} r="6" fill={line} stroke="none" />

      {/* top third */}
      <rect x={penX} y="6" width={PEN_W} height={PEN_H} />
      <rect x={sixX} y="6" width={SIX_W} height={SIX_H} />
      <circle cx={CX} cy={SPOT} r="6" fill={line} stroke="none" />
      <path d={dArc(true)} />
      <rect x={goalX} y="0" width={GOAL_W} height="6" />

      {/* bottom third */}
      <rect x={penX} y={H - PEN_H - 6} width={PEN_W} height={PEN_H} />
      <rect x={sixX} y={H - SIX_H - 6} width={SIX_W} height={SIX_H} />
      <circle cx={CX} cy={H - SPOT} r="6" fill={line} stroke="none" />
      <path d={dArc(false)} />
      <rect x={goalX} y={H - 6} width={GOAL_W} height="6" />

      {/* corner arcs */}
      <path d={`M 6 26 A 20 20 0 0 0 26 6`} />
      <path d={`M ${W - 26} 6 A 20 20 0 0 0 ${W - 6} 26`} />
      <path d={`M 26 ${H - 6} A 20 20 0 0 0 6 ${H - 26}`} />
      <path d={`M ${W - 6} ${H - 26} A 20 20 0 0 0 ${W - 26} ${H - 6}`} />
    </svg>
  )
}
