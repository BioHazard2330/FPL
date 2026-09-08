import { MetricNumber } from '@/components/shell/MetricNumber'
import type { EdgeBlock, WhyLine } from '@/lib/types'

interface ConfidenceGraphicProps {
  why: WhyLine[]
  fragileCount: number
  edge: EdgeBlock | null
  robustness: string | null
  isStale: boolean
  staleReason: string | null
  degradedSources: number
}

const LABEL_COLOR: Record<string, string> = {
  ROBUST: 'text-pitch-green', WATCH: 'text-broadcast-gold', FRAGILE: 'text-alert-red',
}

/** DECISION CONFIDENCE as one composition, not three KPI boxes - a single
 * dominant real label (the SAME real `ROBUST`/`FRAGILE` tag vocabulary
 * `why[]` already carries from the backend's own `robustness_class` field;
 * derived from the real fragile-dependency count only when no explicit tag
 * is present - never an invented word), with the supporting real numbers
 * arranged around it by typography alone. Separated from Evidence above
 * purely by whitespace - no rule, no colour change, the last of this
 * page's deliberately varied separator techniques. */
export function ConfidenceGraphic({ why, fragileCount, edge, robustness, isStale, staleReason, degradedSources }: ConfidenceGraphicProps) {
  const explicitTag = why.find((w) => w.tag === 'FRAGILE' || w.tag === 'ROBUST')?.tag
  const label = explicitTag ?? (fragileCount === 0 ? 'ROBUST' : fragileCount <= 1 ? 'WATCH' : 'FRAGILE')

  return (
    <section className="bg-void px-10 pb-20 pt-16">
      <div className="mb-6 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Decision confidence</div>
      <div className="flex flex-col gap-8 md:flex-row md:items-end">
        <div className={`font-display text-7xl font-bold leading-none ${LABEL_COLOR[label] ?? 'text-text'}`}>{label}</div>

        <div className="flex flex-1 flex-col gap-3 border-l-2 border-divider pl-8">
          {edge && (
            <div className="flex items-baseline gap-3">
              <span className="tabular font-display text-2xl font-bold text-pitch-green">
                <MetricNumber value={edge.value} suffix="pt" />
              </span>
              <span className="text-xs text-text-faint">
                edge vs {edge.alt_label} &middot; {edge.horizon}
              </span>
            </div>
          )}
          <div className="text-sm text-text-muted">
            {fragileCount === 0 ? 'No fragile dependencies flagged' : `${fragileCount} fragile dependenc${fragileCount === 1 ? 'y' : 'ies'} flagged`}
          </div>
          {robustness && <div className="text-xs uppercase tracking-wide text-text-faint">Captain robustness: {robustness}</div>}
          {isStale && <div className="text-sm font-semibold text-broadcast-gold">Stale &mdash; {staleReason ?? 'recomputing'}</div>}
          {degradedSources > 0 && (
            <div className="flex items-center gap-2 text-xs text-alert-red">
              <span className="size-1.5 rounded-full bg-alert-red" />
              {degradedSources} source{degradedSources === 1 ? '' : 's'} degraded
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
