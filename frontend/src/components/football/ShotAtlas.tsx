import { useEffect, useMemo, useState } from 'react'
import type { AtlasShot } from '@/lib/types'

/** THE ATLAS PITCH - one attacking half of real turf, every shot as a dot
 * whose AREA is its xG, and a hero mode that hands the whole pitch to one
 * player.
 *
 * Geometry is drawn in metres: the SVG viewBox IS the pitch (x 48-105 along
 * the length, y 0-68 across), so FotMob's coordinates land on it untouched
 * and the markings sit at their real dimensions - penalty area 16.5m deep by
 * 40.32m wide, six-yard box 5.5m by 18.32m, penalty spot 11m, D arc 9.15m,
 * goal 7.32m with the net hatched behind the line.
 *
 * Three layers, bottom to top:
 *
 * 1. TURF. Alternating mown bands in two flat night-broadcast greens. It is
 *    a surface, not a data encoding, and it is flat - no gradient, no glow -
 *    per DESIGN.md. The chalk is warm off-white at low opacity.
 * 2. HEAT. Optional. A smoothed density of the shots on screen, painted on
 *    a canvas underneath the dots: every shot deposits a small gaussian
 *    weighted by its xG, the field is summed, then mapped through a
 *    three-stop flat ramp (transparent -> deep green -> pitch green). It is
 *    labelled as smoothed, because it is.
 * 3. SHOTS. Radius scales with sqrt(xG) so area is xG. Filled only for a
 *    goal. Ownership is the stroke - your players gold, the league blue - so
 *    a goal by one of yours is a filled gold dot and nothing else on the
 *    pitch looks like that. Woodwork is a hollow red ring.
 *
 * HERO MODE. When one shooter is selected the league drops to a whisper and
 * that player's shots are redrawn large in warm white with their minute
 * beside them, goals as a filled disc with a second ring, the biggest
 * chance of his season marked with a dashed gold halo. The pitch is his.
 *
 * ENTRANCE. On first mount the dots arrive over ~700ms in xG order, small
 * chances first, goals last - the season replays itself once, and never
 * again on a poll refresh. */

const X0 = 48
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
const NET_D = 2.4
const STRIPE = 5.7 // mown band width, metres

const TURF_A = '#0d2f1f'
const TURF_B = '#113a26'
const CHALK = 'rgba(245, 243, 238, 0.28)'
// Heat mode drains the turf so the density field is the only green on the pitch.
const SLATE_A = '#111418'
const SLATE_B = '#15191e'

function dArc(): string {
  const cx = L - SPOT
  const xEdge = L - PEN_D
  const dy = Math.sqrt(Math.max(0, R * R - (cx - xEdge) ** 2))
  return `M ${xEdge} ${CY - dy} A ${R} ${R} 0 0 0 ${xEdge} ${CY + dy}`
}

export type Hover = { shot: AtlasShot; px: number; py: number } | null

interface Props {
  shots: AtlasShot[]
  visible: (s: AtlasShot) => boolean
  heroId: number | null
  showHeat: boolean
  onHover: (h: Hover) => void
}

/** Smoothed shot density, repainted when the visible set changes.
 *
 * Painted on an offscreen canvas and placed as an SVG <image> so it lives
 * in the same metre-based viewBox as the dots. A <foreignObject> canvas
 * was tried first and Chrome placed it at the wrong scale and offset once
 * the viewBox was non-zero-origin - the field rendered a half-pitch off. */
function HeatLayer({ shots, visible }: { shots: AtlasShot[]; visible: (s: AtlasShot) => boolean }) {
  const [href, setHref] = useState<string | null>(null)
  useEffect(() => {
    const cw = 228, ch = 272
    const canvas = document.createElement('canvas')
    canvas.width = cw; canvas.height = ch
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const field = new Float32Array(cw * ch)
    const sigma = 7
    const rad = Math.ceil(sigma * 2.5)
    let peak = 0
    for (const s of shots) {
      if (!visible(s)) continue
      const gx = ((s.x - X0) / (L - X0)) * cw
      const gy = (s.y / W) * ch
      const w = Math.max(s.xg ?? 0.02, 0.02)
      for (let dy = -rad; dy <= rad; dy++) {
        const yy = Math.round(gy) + dy
        if (yy < 0 || yy >= ch) continue
        for (let dx = -rad; dx <= rad; dx++) {
          const xx = Math.round(gx) + dx
          if (xx < 0 || xx >= cw) continue
          const v = w * Math.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma))
          const idx = yy * cw + xx
          field[idx] += v
          if (field[idx] > peak) peak = field[idx]
        }
      }
    }
    const img = ctx.createImageData(cw, ch)
    // Flat three-stop ramp: transparent -> deep green (#12a552) -> pitch
    // green (#1fce6b). The ramp IS the value; nothing glows.
    for (let i = 0; i < field.length; i++) {
      // Square-root compression: the six-yard box is an order of magnitude
      // denser than the edge of the area, and a linear ramp collapsed the
      // whole field into one hot spot. This keeps the peak where it is and
      // lets the shape of the rest read.
      const t = peak > 0 ? Math.sqrt(Math.min(1, field[i] / peak)) : 0
      if (t < 0.06) { img.data[i * 4 + 3] = 0; continue }
      const k = t < 0.5 ? t * 2 : (t - 0.5) * 2
      const r = t < 0.5 ? 18 * k : 18 + (31 - 18) * k
      const g = t < 0.5 ? 165 * k : 165 + (206 - 165) * k
      const b = t < 0.5 ? 82 * k : 82 + (107 - 82) * k
      img.data[i * 4] = r; img.data[i * 4 + 1] = g; img.data[i * 4 + 2] = b
      img.data[i * 4 + 3] = Math.round(200 * (t < 0.5 ? t * 2 : 1))
    }
    ctx.putImageData(img, 0, 0)
    setHref(canvas.toDataURL('image/png'))
  }, [shots, visible])
  if (!href) return null
  return <image href={href} x={X0} y={0} width={L - X0} height={W} preserveAspectRatio="none" opacity={0.95} />
}

export function ShotAtlas({ shots, visible, heroId, showHeat, onHover }: Props) {
  const [entered, setEntered] = useState(false)
  useEffect(() => { const t = setTimeout(() => setEntered(true), 40); return () => clearTimeout(t) }, [])

  // Draw order: low-xG misses first, goals later, the hero's shots last of
  // all so nothing ever sits on top of them.
  const ordered = useMemo(() => {
    const arr = shots.slice()
    arr.sort((a, b) => {
      const ha = a.player_id === heroId ? 1 : 0, hb = b.player_id === heroId ? 1 : 0
      if (ha !== hb) return ha - hb
      const ga = a.outcome === 'Goal' ? 1 : 0, gb = b.outcome === 'Goal' ? 1 : 0
      if (ga !== gb) return ga - gb
      return (a.xg ?? 0) - (b.xg ?? 0)
    })
    return arr
  }, [shots, heroId])

  const heroBiggest = useMemo(() => {
    if (heroId === null) return null
    return shots.reduce<AtlasShot | null>(
      (best, s) => (s.player_id === heroId && (s.xg ?? 0) > (best?.xg ?? -1) ? s : best), null,
    )
  }, [shots, heroId])

  const stripes = useMemo(() => {
    const out: number[] = []
    for (let x = X0; x < L; x += STRIPE) out.push(x)
    return out
  }, [])

  return (
    <svg
      viewBox={`${X0} 0 ${L - X0 + NET_D} ${W}`}
      className="mx-auto block h-full w-auto max-h-[68vh] select-none"
      role="img"
      aria-label="Every shot this season, plotted on the attacking half"
      onMouseLeave={() => onHover(null)}
    >
      {stripes.map((x, i) => (
        <rect key={x} x={x} y={0} width={Math.min(STRIPE, L - x)} height={W} fill={showHeat ? (i % 2 ? SLATE_A : SLATE_B) : (i % 2 ? TURF_A : TURF_B)} />
      ))}
      <rect x={L} y={0} width={NET_D} height={W} fill="var(--void)" />

      {showHeat && <HeatLayer shots={shots} visible={visible} />}

      <g fill="none" stroke={CHALK} strokeWidth={0.22}>
        <rect x={X0} y={0.15} width={L - X0 - 0.11} height={W - 0.3} />
        <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
        <circle cx={L / 2} cy={CY} r={R} />
        <rect x={L - PEN_D} y={CY - PEN_W / 2} width={PEN_D} height={PEN_W} />
        <rect x={L - SIX_D} y={CY - SIX_W / 2} width={SIX_D} height={SIX_W} />
        <circle cx={L - SPOT} cy={CY} r={0.35} fill={CHALK} stroke="none" />
        <path d={dArc()} />
        <path d={`M ${L} 0 L ${L} ${W}`} strokeWidth={0.3} />
        <path d={`M ${L - 1} 0 A 1 1 0 0 0 ${L} 1`} />
        <path d={`M ${L} ${W - 1} A 1 1 0 0 0 ${L - 1} ${W}`} />
      </g>
      <g>
        <rect x={L} y={CY - GOAL_W / 2} width={NET_D} height={GOAL_W} fill="rgba(245,243,238,0.06)" stroke="rgba(245,243,238,0.7)" strokeWidth={0.28} />
        {Array.from({ length: 7 }, (_, i) => (
          <line key={`nv${i}`} x1={L + 0.3 + i * 0.3} y1={CY - GOAL_W / 2} x2={L + 0.3 + i * 0.3} y2={CY + GOAL_W / 2} stroke="rgba(245,243,238,0.22)" strokeWidth={0.05} />
        ))}
        {Array.from({ length: 12 }, (_, i) => (
          <line key={`nh${i}`} x1={L} y1={CY - GOAL_W / 2 + 0.6 * (i + 0.5)} x2={L + NET_D} y2={CY - GOAL_W / 2 + 0.6 * (i + 0.5)} stroke="rgba(245,243,238,0.22)" strokeWidth={0.05} />
        ))}
      </g>

      {ordered.map((s, i) => {
        const isHero = heroId !== null && s.player_id === heroId
        const shown = visible(s)
        const goal = s.outcome === 'Goal'
        const post = s.outcome === 'Post'
        const base = Math.max(0.3, Math.sqrt(Math.max(s.xg ?? 0.01, 0.01)) * 1.9)
        const r = isHero ? base * 1.55 + 0.25 : base
        const stroke = isHero ? '#f5f3ee' : post ? 'var(--alert-red)' : s.mine ? 'var(--broadcast-gold)' : 'var(--broadcast-blue)'
        // In heat mode the field is the reading; dots step back so it shows.
        const opacity = heroId !== null ? (isHero ? 1 : 0.05) : shown ? (showHeat ? 0.22 : 0.9) : 0.05
        const cx = Math.min(L - 0.3, Math.max(X0 + 0.3, s.x))
        const cy = Math.min(W - 0.3, Math.max(0.3, s.y))
        return (
          <g
            key={`${s.match}-${s.player_id}-${s.minute}-${i}`}
            style={{ opacity: entered ? opacity : 0, transition: `opacity 260ms ease-out ${Math.min(700, i * 0.6)}ms` }}
          >
            {isHero && goal && (
              <circle cx={cx} cy={cy} r={r + 0.9} fill="none" stroke="#f5f3ee" strokeOpacity={0.55} strokeWidth={0.18} />
            )}
            {isHero && heroBiggest === s && (
              <circle cx={cx} cy={cy} r={r + 1.8} fill="none" stroke="var(--broadcast-gold)" strokeWidth={0.22} strokeDasharray="0.6 0.5" />
            )}
            <circle
              cx={cx} cy={cy} r={r}
              fill={goal ? (isHero ? '#f5f3ee' : stroke) : 'transparent'}
              fillOpacity={goal ? 0.92 : 0}
              stroke={stroke}
              strokeWidth={isHero ? 0.32 : post ? 0.45 : 0.25}
              className="cursor-crosshair"
              onMouseEnter={(e) => onHover({ shot: s, px: e.clientX, py: e.clientY })}
              onMouseMove={(e) => onHover({ shot: s, px: e.clientX, py: e.clientY })}
            />
            {isHero && s.minute !== null && (
              <text
                x={cx + r + 0.5} y={cy + 0.55}
                fontSize={1.5} fontWeight={700} fill="#f5f3ee" fillOpacity={0.85}
                fontFamily="var(--font-display)"
                className="pointer-events-none"
              >
                {s.minute}'
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
