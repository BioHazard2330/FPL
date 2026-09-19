import { MetricNumber } from '@/components/shell/MetricNumber'
import type { CheckpointBlock } from '@/lib/types'

interface ComparisonGraphicProps {
  checkpoint: CheckpointBlock
}

/** CHOSEN vs ALTERNATIVE as a real broadcast stat graphic - two horizontal
 * bars keyed to the real final-horizon totals, not two cards side by side.
 * The bars themselves ARE the interface: flat fill, no shadow, no panel
 * wrapper. Real values only (`checkpoint_table`'s own last-horizon totals -
 * the same numbers the old vertical-bar version read). */
export function ComparisonGraphic({ checkpoint }: ComparisonGraphicProps) {
  const last = checkpoint.horizons.length - 1
  const chosenTotal = checkpoint.chosen.totals[last]
  const altTotal = checkpoint.alt.totals[last]
  if (chosenTotal === undefined || altTotal === undefined) return null
  const max = Math.max(chosenTotal, altTotal, 1)
  const delta = chosenTotal - altTotal
  const horizonGw = checkpoint.horizons[last]
  const noise = checkpoint.noise_bar ?? null
  const insideNoise = noise !== null && Math.abs(delta) < noise
  // Axis spans at least the noise band and the delta, so both always fit.
  const axisMax = Math.max(noise ?? 0, Math.abs(delta), 1) * 1.25

  return (
    <div className="w-full max-w-2xl">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-text-faint">{checkpoint.chosen.name}</span>
        <span className="tabular font-display text-3xl font-bold text-pitch-green">
          <MetricNumber value={chosenTotal} />
        </span>
      </div>
      <div className="mt-1.5 h-5 w-full bg-panel">
        <div className="bar-draw h-full bg-pitch-green transition-[width] duration-500" style={{ width: `${(chosenTotal / max) * 100}%` }} />
      </div>

      <div className="mt-4 flex items-baseline justify-between">
        <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-text-faint">{checkpoint.alt.name}</span>
        <span className="tabular text-xl font-bold text-text-muted">
          <MetricNumber value={altTotal} />
        </span>
      </div>
      <div className="mt-1.5 h-5 w-full bg-panel">
        <div className="bar-draw h-full bg-text-faint/60 transition-[width] duration-500" style={{ width: `${(altTotal / max) * 100}%` }} />
      </div>

      <div className="mt-4 flex items-baseline gap-2 border-t-2 border-divider pt-3">
        <span className={`tabular font-display text-2xl font-bold ${insideNoise ? 'text-text-faint' : 'text-text'}`}>
          {delta >= 0 ? '+' : ''}
          {delta.toFixed(1)}
        </span>
        <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-text-faint">pts over {horizonGw} GW</span>
        {noise !== null && (
          <span className={`ml-2 text-[10px] uppercase tracking-wide ${insideNoise ? 'text-broadcast-gold' : 'text-text-faint'}`}>
            {insideNoise ? `inside the ±${noise.toFixed(1)} noise band` : `clears the ±${noise.toFixed(1)} noise band`}
          </span>
        )}
      </div>

      {/* NOISE BAND - the delta drawn on a zero-centred axis against the
          measured error band. This is the reading the two absolute bars
          above cannot give: 283.6 vs 283.2 render as near-identical bars,
          while the entire question is whether 0.4 means anything. A delta
          inside the band sits within the gold; a real edge clears it. */}
      {noise !== null && (
        <div className="mt-3">
          <div className="relative h-3 w-full">
            <div
              className="absolute top-0 h-full bg-broadcast-gold/15"
              style={{ left: `${50 - (noise / axisMax) * 50}%`, width: `${(noise / axisMax) * 100}%` }}
            />
            <div className="absolute left-1/2 top-0 h-full w-px bg-divider" />
            <div
              className={`absolute top-0.5 h-2 ${delta < 0 ? 'bg-alert-red/80' : 'bg-pitch-green'}`}
              style={delta < 0
                ? { right: '50%', width: `${(Math.abs(delta) / axisMax) * 50}%` }
                : { left: '50%', width: `${(delta / axisMax) * 50}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[9px] uppercase tracking-wide text-text-faint">
            <span>−{axisMax.toFixed(0)}</span>
            <span>{checkpoint.alt.name} ← 0 → {checkpoint.chosen.name}</span>
            <span>+{axisMax.toFixed(0)}</span>
          </div>
        </div>
      )}
    </div>
  )
}
