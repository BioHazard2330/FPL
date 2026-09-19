import { useMemo, useState } from 'react'
import type { AtlasShot, AtlasZone } from '@/lib/types'

/** THE ATLAS PITCH - one attacking half, real proportions, every shot as a
 * dot whose AREA is its xG.
 *
 * Geometry is drawn in metres: the SVG viewBox IS the pitch (x 40-105 along
 * the length, y 0-68 across), so FotMob's coordinates land on it with no
 * transform at all and the markings are placed at their real dimensions -
 * penalty area 16.5m deep by 40.32m wide, six-yard box 5.5m by 18.32m,
 * penalty spot 11m, D arc 9.15m. The goal is on the right, the classic
 * analytics orientation, because 1,100 dots need the width.
 *
 * Encoding, per DESIGN.md's shot-map rule: radius scaled to real xG (area,
 * not radius, so a 0.4 chance reads as four times a 0.1 chance rather than
 * twice), filled only for a goal. Ownership is the stroke colour - your
 * players gold, the league blue - so a goal by one of yours is a filled
 * gold dot and there is exactly one thing on this pitch that looks like
 * that. A shot that hit the post is a hollow red ring: it is neither a
 * miss nor a save and deserves to be told apart.
 *
 * The zone layer is the mean xG of shots inside each cell, drawn as a flat
 * green tint at an opacity proportional to that mean. It is chance quality
 * by location, from the same dots, not a model - which is why the cell's
 * own shot count is shown when hovered. */

const X0 = 48 // how far back from the goal line the view starts (m) - just past the centre circle's edge
const L = 105
const W = 68
const CY = W / 2
const PEN_D = 16.5
const PEN_W = 40.32
const SIX_D = 5.5
const SIX_W = 18.32
const SPOT = 11
const R = 9.15
const GOAL_W = 7.32

function dArc(): string {
  // The part of the 9.15m circle around the spot that lies OUTSIDE the box.
  const cx = L - SPOT
  const xEdge = L - PEN_D
  const dy = Math.sqrt(Math.max(0, R * R - (cx - xEdge) ** 2))
  return `M ${xEdge} ${CY - dy} A ${R} ${R} 0 0 0 ${xEdge} ${CY + dy}`
}

export type Hover = { shot: AtlasShot; px: number; py: number } | null

interface Props {
  shots: AtlasShot[]
  zones: AtlasZone[]
  showZones: boolean
  dim: (s: AtlasShot) => boolean
  onHover: (h: Hover) => void
}

export function ShotAtlas({ shots, zones, showZones, dim, onHover }: Props) {
  const [zoneHover, setZoneHover] = useState<AtlasZone | null>(null)
  const maxZone = useMemo(() => Math.max(...zones.map((z) => z.mean_xg ?? 0), 0.05), [zones])
  const line = 'color-mix(in srgb, var(--text) 14%, transparent)'

  // Larger, lower-xG shots drawn first so a big goal never buries a small
  // one; goals last so they always sit on top.
  const ordered = useMemo(() => {
    const arr = shots.slice()
    arr.sort((a, b) => {
      const ga = a.outcome === 'Goal' ? 1 : 0
      const gb = b.outcome === 'Goal' ? 1 : 0
      if (ga !== gb) return ga - gb
      return (b.xg ?? 0) - (a.xg ?? 0)
    })
    return arr
  }, [shots])

  return (
    <svg
      viewBox={`${X0} 0 ${L - X0} ${W}`}
      className="mx-auto block h-full w-auto max-h-[66vh] select-none"
      role="img"
      aria-label="Every shot this season, plotted on the attacking half"
      onMouseLeave={() => { onHover(null); setZoneHover(null) }}
    >
      <rect x={X0} y={0} width={L - X0} height={W} fill="var(--panel)" />

      {showZones && zones.map((z) => (
        <rect
          key={`${z.col}-${z.row}`}
          x={z.x0} y={z.y0} width={z.x1 - z.x0} height={z.y1 - z.y0}
          fill="var(--pitch-green)"
          fillOpacity={z.mean_xg === null ? 0 : 0.08 + 0.55 * (z.mean_xg / maxZone)}
          stroke="var(--void)" strokeWidth={0.15}
          onMouseEnter={() => setZoneHover(z)}
          onMouseLeave={() => setZoneHover(null)}
        />
      ))}

      {/* markings, in metres */}
      <g fill="none" stroke={line} strokeWidth={0.25}>
        <rect x={X0} y={0.2} width={L - X0 - 0.2} height={W - 0.4} />
        <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
        <circle cx={L / 2} cy={CY} r={R} />
        <rect x={L - PEN_D} y={CY - PEN_W / 2} width={PEN_D} height={PEN_W} />
        <rect x={L - SIX_D} y={CY - SIX_W / 2} width={SIX_D} height={SIX_W} />
        <circle cx={L - SPOT} cy={CY} r={0.35} fill={line} stroke="none" />
        <path d={dArc()} />
        <rect x={L} y={CY - GOAL_W / 2} width={2} height={GOAL_W} stroke="var(--text)" strokeOpacity={0.5} />
      </g>

      {ordered.map((s, i) => {
        const r = Math.max(0.3, Math.sqrt(Math.max(s.xg ?? 0.01, 0.01)) * 1.9)
        const faded = dim(s)
        const goal = s.outcome === 'Goal'
        const post = s.outcome === 'Post'
        const stroke = post ? 'var(--alert-red)' : s.mine ? 'var(--broadcast-gold)' : 'var(--broadcast-blue)'
        const cx = Math.min(L - 0.3, Math.max(X0 + 0.3, s.x))
        const cy = Math.min(W - 0.3, Math.max(0.3, s.y))
        return (
          <circle
            key={`${s.match}-${s.player_id}-${s.minute}-${i}`}
            cx={cx} cy={cy} r={r}
            fill={goal ? stroke : 'transparent'}
            fillOpacity={faded ? 0.12 : 0.85}
            stroke={stroke}
            strokeOpacity={faded ? 0.12 : 0.9}
            strokeWidth={post ? 0.45 : 0.25}
            className="cursor-crosshair transition-opacity duration-200"
            onMouseEnter={(e) => onHover({ shot: s, px: e.clientX, py: e.clientY })}
            onMouseMove={(e) => onHover({ shot: s, px: e.clientX, py: e.clientY })}
          />
        )
      })}

      {showZones && zoneHover && zoneHover.mean_xg !== null && (
        <text
          x={(zoneHover.x0 + zoneHover.x1) / 2} y={(zoneHover.y0 + zoneHover.y1) / 2}
          textAnchor="middle" dominantBaseline="middle"
          fontSize={2.2} fontWeight={700} fill="var(--text)"
          className="pointer-events-none"
        >
          {zoneHover.mean_xg.toFixed(2)} xG · {zoneHover.n}
        </text>
      )}
    </svg>
  )
}
