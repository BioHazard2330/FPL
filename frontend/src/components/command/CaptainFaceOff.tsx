import { MetricNumber } from '@/components/shell/MetricNumber'
import { shirtUrl } from '@/lib/api'
import { NextFixture } from '@/components/football/FixtureRun'
import type { CaptainBlock, FixtureContext } from '@/lib/types'

/** THE CAPTAIN BATTLE as a true face-off, not two option cards - a real
 * central VS axis, real shirts, and a real bar-magnitude read under each
 * name keyed to the same median xP the numbers already show. Flat colour
 * fields (no `atmosphere-green` gradient wash, no drop-shadow glow on the
 * shirts) - the split itself, not a gradient, is what signals "versus."
 *
 * Real 3D depth (2026-09-10), deliberately STATIC, never animated: a real
 * `perspective` + `translateZ` composition pushes the real leading
 * candidate's shirt/card literal millimetres toward the camera while the
 * second option recedes, a genuine broadcast-camera depth read rather than
 * a bigger font size standing in for "this one matters more." This project's
 * own `DESIGN.md` motion law bans exactly the animated version of this idea
 * ("page-load flourishes", "parallax" are both explicitly forbidden) - a
 * one-time camera push-in on mount would violate that rule outright, so the
 * depth is baked into the layout itself instead of triggered by an
 * animation. Real 3D substance without a single new frame of motion. */
export function CaptainFaceOff({ block, fixtures }: { block: CaptainBlock; fixtures?: FixtureContext }) {
  // Captaincy is a fixture decision before it is a projection decision -
  // the face-off used to name two players and two numbers with no
  // opponent anywhere in the graphic.
  const bestRun = block.best.team_code !== null ? fixtures?.[String(block.best.team_code)] : undefined
  const secondRun = block.second?.team_code != null ? fixtures?.[String(block.second.team_code)] : undefined
  const bestShirt = block.best.team_code !== null ? shirtUrl(block.best.team_code, block.best.position === 'GKP', 220) : null
  const secondShirt =
    block.second && block.second.team_code !== null ? shirtUrl(block.second.team_code, block.second.position === 'GKP', 180) : null
  const max = Math.max(block.best.median, block.second?.median ?? 0, 1)

  return (
    <section className="bg-void px-10 py-10">
      <div className="mb-6 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Captain battle</div>

      <div className="grid grid-cols-1 items-center gap-6 md:[perspective:1200px] md:grid-cols-[1fr_auto_1fr]">
        {/* best - right-aligned into the axis, real static Z-depth pushing
            it toward the camera (see module docstring: static, never
            animated, per this project's own motion law) */}
        <div className="flex items-center justify-end gap-6 text-right md:[transform:translateZ(40px)]">
          {bestShirt && <img src={bestShirt} alt="" className="h-28 w-28 shrink-0 object-contain md:h-36 md:w-36" />}
          <div className="min-w-0">
            <div className="truncate font-display text-4xl font-bold uppercase text-text md:text-5xl">{block.best.name}</div>
            <div className="tabular mt-1 text-4xl font-bold text-pitch-green">
              <MetricNumber value={block.best.median} suffix=" xP" />
            </div>
            <div className="mt-1.5 flex justify-end">
              <NextFixture fixtures={bestRun} />
            </div>
            <div className="mt-2 h-2 w-full bg-panel">
              <div className="bar-draw-right ml-auto h-full bg-pitch-green" style={{ width: `${(block.best.median / max) * 100}%` }} />
            </div>
            {(block.best.floor !== null || block.best.ceiling !== null) && (
              <div className="tabular mt-1 text-xs text-text-faint">
                {block.best.floor?.toFixed(1) ?? '—'}&ndash;{block.best.ceiling?.toFixed(1) ?? '—'} range
              </div>
            )}
          </div>
        </div>

        {/* the axis - a sharp rotated square, not a rounded roundel */}
        <div className="flex items-center justify-center py-4">
          <div className="flex size-14 rotate-45 items-center justify-center border-2 border-broadcast-gold bg-void">
            <span className="-rotate-45 font-display text-sm font-bold text-broadcast-gold">VS</span>
          </div>
        </div>

        {/* second option - recedes on the same real Z axis, the other half
            of the static depth read */}
        {block.second ? (
          <div className="flex items-center gap-6 md:[transform:translateZ(-50px)]">
            {secondShirt && <img src={secondShirt} alt="" className="h-20 w-20 shrink-0 object-contain opacity-80 md:h-24 md:w-24" />}
            <div className="min-w-0">
              <div className="truncate font-display text-2xl font-bold uppercase text-text-muted md:text-3xl">{block.second.name}</div>
              <div className="tabular mt-1 text-2xl font-bold text-text-muted">{block.second.median.toFixed(1)} xP</div>
              <div className="mt-1.5">
                <NextFixture fixtures={secondRun} />
              </div>
              <div className="mt-2 h-2 w-full bg-panel">
                <div className="bar-draw h-full bg-text-faint/60" style={{ width: `${(block.second.median / max) * 100}%` }} />
              </div>
              {(block.second.floor !== null || block.second.ceiling !== null) && (
                <div className="tabular mt-1 text-xs text-text-faint">
                  {block.second.floor?.toFixed(1) ?? '—'}&ndash;{block.second.ceiling?.toFixed(1) ?? '—'} range
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="text-sm text-text-faint">No genuine second option this week.</div>
        )}
      </div>

      {block.edge_driver && (
        <div className="mt-8 border-t-2 border-divider pt-4 text-center text-sm text-text-muted">
          Edge driven by <span className="font-semibold text-text">{block.edge_driver.label}</span>{' '}
          <span className="font-bold text-pitch-green">(+{block.edge_driver.value.toFixed(1)})</span>
          {block.robustness && <span className="ml-4 text-xs uppercase tracking-wide text-text-faint">{block.robustness}</span>}
        </div>
      )}
    </section>
  )
}
