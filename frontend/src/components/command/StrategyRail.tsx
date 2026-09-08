import type { MonitorRow, TrajectoryBlock } from '@/lib/types'

/** STRATEGY DEPENDENCY as a spatial route through upcoming gameweeks - a
 * real horizontal rail (dots + connectors), each leg's own real
 * fragile-dependency flag driving its weight, not a row of rounded cards.
 * Sits on the flat void field, separated from the module above purely by
 * a generous top gap (typography/whitespace separation - no rule, no
 * colour change - one more deliberately different technique). */
export function StrategyRail({ trajectory, monitor }: { trajectory: TrajectoryBlock; monitor: MonitorRow[] }) {
  return (
    <section className="bg-void px-10 pb-10 pt-16">
      <div className="mb-6 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Strategy path — what breaks this</div>
      <div className="flex gap-0 overflow-x-auto pb-2">
        <div className="flex min-w-fit flex-col items-center gap-2 pr-6">
          <div className="flex size-3 items-center justify-center rounded-full bg-pitch-green" />
          <div className="w-28 text-center text-[11px] font-bold uppercase tracking-wide text-pitch-green">
            {trajectory.now.gw ? `GW${trajectory.now.gw}` : 'Now'}
          </div>
          <div className="w-28 text-center text-xs text-text-muted">{trajectory.now.action}</div>
        </div>
        {trajectory.future_legs.map((leg, i) => (
          <div key={i} className="flex min-w-fit items-center">
            <div className={`h-px w-8 ${leg.fragile_dependency ? 'border-t-2 border-dashed border-broadcast-gold' : 'bg-divider'}`} />
            <div className="flex flex-col items-center gap-2 px-4">
              <div className={`flex size-3 items-center justify-center rounded-full ${leg.fragile_dependency ? 'bg-broadcast-gold' : 'bg-divider'}`} />
              <div
                className={`w-28 text-center text-[11px] font-bold uppercase tracking-wide ${leg.fragile_dependency ? 'text-broadcast-gold' : 'text-text-faint'}`}
              >
                {leg.gw ? `GW${leg.gw}` : `Step ${i + 1}`}
              </div>
              <div className="w-28 text-center text-xs text-text-muted">{leg.action}</div>
            </div>
          </div>
        ))}
      </div>

      {monitor.length > 0 && (
        <div className="mt-8 divide-y divide-divider border-t-2 border-divider">
          {monitor.map((r, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 py-3 text-sm">
              <span className="font-semibold text-text">{r.current}</span>
              <span className="text-text-faint">&rarr;</span>
              <span className="text-text-muted">{r.trigger}</span>
              <span className="text-text-faint">&rarr;</span>
              <span className="font-semibold text-pitch-green">{r.consequence}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
