import type { WeekPlanPayload } from '@/lib/types'

/** THE ROAD AHEAD - how this week's plan continues, a gameweek per column.
 *
 * Every column after the first is a projection, not an instruction: each week
 * is re-solved with that week's injuries, prices and team news. It is drawn
 * anyway because the weeks a plan chooses to leave empty are as much of the
 * plan as the ones it fills - a roll is how free transfers are banked, and a
 * manager reading a week-by-week plan wants to see where the quiet weeks are.
 *
 * Every transfer here was charged the same minimum a move has to earn this
 * week, so a later week is not padded with swaps worth a fraction of a point. */
export function RoadAhead({ plan, compact = false }: { plan: WeekPlanPayload; compact?: boolean }) {
  const road = plan.road_ahead
  if (!road) return null
  const weeks = road.weeks.slice(1)
  if (weeks.length === 0) return null
  const busiest = Math.max(...weeks.map((w) => w.moves.length), 1)

  return (
    <section className={`bg-void ${compact ? 'px-10 py-10' : 'px-10 pb-10 pt-8'}`}>
      <div className="mb-1 flex flex-wrap items-baseline gap-x-5">
        <span className="text-[13px] font-bold uppercase tracking-[0.15em] text-text-faint">The road ahead</span>
        <span className="font-mono text-[12px] uppercase tracking-[0.1em] text-text-faint">
          {road.horizon} gameweeks &middot; projected, re-solved every week
        </span>
      </div>
      <p className="mb-6 max-w-3xl text-sm text-text-muted">
        Continuing this plan is worth{' '}
        <span className="tabular font-bold text-pitch-green">
          {road.gain_vs_roll >= 0 ? '+' : ''}
          {road.gain_vs_roll.toFixed(1)}
        </span>{' '}
        points over rolling this week and starting from next. Each later move had to earn {plan.min_move_gain} points to appear.
      </p>

      <div className="grid gap-px bg-divider" style={{ gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))` }}>
        {weeks.map((w) => (
          <div key={w.event} className="bg-panel px-3 pb-4 pt-3" style={{ minHeight: 56 + busiest * 34 }}>
            <div className="mb-2 font-display text-lg font-bold text-text-faint">GW{w.event}</div>
            {w.moves.length === 0 ? (
              <div className="text-[13px] font-bold uppercase tracking-[0.1em] text-text-faint">Roll</div>
            ) : (
              <div className="space-y-1.5">
                {w.moves.map((m) => (
                  <div key={`${m.out}-${m.into}`} className="border-l border-pitch-green pl-2 text-[13px] leading-tight">
                    <div className="truncate text-text-muted">{m.out}</div>
                    <div className="truncate font-semibold text-text">&rarr; {m.into}</div>
                    {m.hit && <div className="text-[11px] font-bold uppercase text-alert-red">costs a hit</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="mt-3 text-xs text-text-faint">
        {road.final_free_transfers} free transfer{road.final_free_transfers === 1 ? '' : 's'} banked at the end of the horizon.
        {!road.proven && ' Best plan found within the time limit; not proven optimal.'}
      </div>
    </section>
  )
}
