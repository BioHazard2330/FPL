import { useState } from 'react'

/** A real CSS 3D flip - `perspective` + `transform-style: preserve-3d` +
 * `backface-visibility: hidden`, not a fade/crossfade pretending to be one.
 * Click toggles between `front` and `back`; both render at all times (the
 * "hidden" face is really there, just rotated away), so nothing pops in
 * late. No WebGL needed for this one - a real 3D transform is a real
 * browser feature, not a simulation. */
export function FlipCard({ front, back, className = '', ariaLabel }: {
  front: React.ReactNode
  back: React.ReactNode
  className?: string
  ariaLabel: string
}) {
  const [flipped, setFlipped] = useState(false)
  return (
    <button
      type="button"
      onClick={() => setFlipped((f) => !f)}
      aria-label={ariaLabel}
      aria-pressed={flipped}
      className={`group [perspective:1000px] focus:outline-none focus-visible:ring-1 focus-visible:ring-pitch-green ${className}`}
    >
      <div
        className="relative h-full w-full transition-transform duration-500 [transform-style:preserve-3d] motion-reduce:transition-none"
        style={{ transform: flipped ? 'rotateY(180deg)' : 'rotateY(0deg)' }}
      >
        <div className="absolute inset-0 [backface-visibility:hidden]">{front}</div>
        <div className="absolute inset-0 [backface-visibility:hidden]" style={{ transform: 'rotateY(180deg)' }}>
          {back}
        </div>
      </div>
    </button>
  )
}
