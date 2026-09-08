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

  return (
    <div className="w-full max-w-2xl">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-text-faint">{checkpoint.chosen.name}</span>
        <span className="tabular font-display text-3xl font-bold text-pitch-green">
          <MetricNumber value={chosenTotal} />
        </span>
      </div>
      <div className="mt-1.5 h-5 w-full bg-panel">
        <div className="h-full bg-pitch-green transition-[width] duration-500" style={{ width: `${(chosenTotal / max) * 100}%` }} />
      </div>

      <div className="mt-4 flex items-baseline justify-between">
        <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-text-faint">{checkpoint.alt.name}</span>
        <span className="tabular text-xl font-bold text-text-muted">
          <MetricNumber value={altTotal} />
        </span>
      </div>
      <div className="mt-1.5 h-5 w-full bg-panel">
        <div className="h-full bg-text-faint/60 transition-[width] duration-500" style={{ width: `${(altTotal / max) * 100}%` }} />
      </div>

      <div className="mt-4 flex items-baseline gap-2 border-t-2 border-divider pt-3">
        <span className="tabular font-display text-2xl font-bold text-text">
          {delta >= 0 ? '+' : ''}
          {delta.toFixed(1)}
        </span>
        <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-text-faint">pts over {horizonGw} GW</span>
      </div>
    </div>
  )
}
