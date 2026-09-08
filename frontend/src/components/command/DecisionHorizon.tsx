import type { CheckpointBlock } from '@/lib/types'

/** THE DECISION MARGIN as a horizon trajectory, not a bar chart in a
 * section - a real trend line tracing the real edge values across GW
 * horizons, flat columns underneath (no shadow), a thick rule baseline.
 * Separated from the module above by a strong rule (one of several
 * deliberately different separator techniques across this page, per the
 * "not every section separated the same way" rule). */
export function DecisionHorizon({ checkpoint }: { checkpoint: CheckpointBlock }) {
  const lastEdge = checkpoint.edge[checkpoint.edge.length - 1]
  const lastHorizon = checkpoint.horizons[checkpoint.horizons.length - 1]
  const maxEdge = Math.max(...checkpoint.edge.map((e) => Math.abs(e)), 1)

  return (
    <section className="border-t-2 border-divider bg-void px-10 py-10">
      <div className="mb-6 flex items-baseline gap-4">
        <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Decision horizon</span>
        <span className="tabular font-display text-4xl font-bold text-pitch-green">
          {lastEdge >= 0 ? '+' : ''}
          {lastEdge.toFixed(1)}pts
        </span>
        <span className="text-xs text-text-faint">at the {lastHorizon}-GW horizon</span>
      </div>

      <div className="relative flex items-end gap-0">
        <svg className="pointer-events-none absolute inset-x-0 bottom-[calc(1.75rem+0.5rem)] h-24 w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polyline
            fill="none"
            stroke="var(--pitch-green)"
            strokeWidth="1.5"
            strokeOpacity="0.6"
            vectorEffect="non-scaling-stroke"
            points={checkpoint.horizons
              .map((_, i) => {
                const edge = checkpoint.edge[i]
                const barH = Math.max(6, (Math.abs(edge) / maxEdge) * 90)
                const x = ((i + 0.5) / checkpoint.horizons.length) * 100
                const y = 100 - (barH / 96) * 100
                return `${x},${y}`
              })
              .join(' ')}
          />
        </svg>
        {checkpoint.horizons.map((h, i) => {
          const edge = checkpoint.edge[i]
          const barH = Math.max(6, (Math.abs(edge) / maxEdge) * 90)
          return (
            <div key={h} className="flex flex-1 flex-col items-center gap-2">
              <div className="tabular text-sm font-bold text-text">
                {edge >= 0 ? '+' : ''}
                {edge.toFixed(1)}
              </div>
              <div className="flex h-24 w-full items-end justify-center">
                <div
                  className={`w-2/3 max-w-10 ${edge >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`}
                  style={{ height: `${barH}px` }}
                />
              </div>
              <div className="w-full border-t-2 border-divider pt-2 text-center text-[10px] font-bold uppercase tracking-wide text-text-faint">
                {h} GW
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
