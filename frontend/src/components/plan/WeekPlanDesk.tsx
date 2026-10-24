import { RoadAhead } from '@/components/command/RoadAhead'
import { chipName, Panel, Pill } from '@/components/ui/kit'
import type { WeekPlanPayload } from '@/lib/types'

/** THE PLAN, as the exact solver sees it: this week's moves, the weeks after, then the chips and whether the fixture list gives
 * any of them a reason to be played. It is the same plan Command tells the manager to execute, extended. */
export function WeekPlanDesk({ plan }: { plan: WeekPlanPayload }) {
  const moves = plan.moves ?? []
  const chips = plan.chip_outlook

  return (
    <>
      <RoadAhead
        plan={plan}
        title={`GW${plan.event} and beyond`}
        lead={<>This week: {moves.length === 0 ? 'roll the transfer' : moves.map((m) => `${m.out.name} to ${m.into.name}`).join(', ')}. </>}
      />

      {chips && (
        <Panel title="Chips">
          <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
            <div className="flex flex-wrap gap-2">
              {chips.available.length === 0 ? (
                <span className="text-sm text-text-muted">None left in this window.</span>
              ) : (
                chips.available.map((c) => (
                  <Pill key={c} tone="gold">
                    {chipName(c)}
                  </Pill>
                ))
              )}
            </div>
            <p className="max-w-2xl text-[14px] leading-snug text-text-muted">
              {chips.double_gameweeks.length === 0
                ? `No double gameweek is scheduled in the next ${chips.horizon}. ${
                    chips.available.includes('bboost')
                      ? `A bench boost this week would add about ${chips.bench_boost_this_week.toFixed(1)} points, which is the bench's whole expected score. It is worth far more on a double gameweek, so it waits for one.`
                      : ''
                  }`
                : `Double gameweek${chips.double_gameweeks.length > 1 ? 's' : ''}: ${chips.double_gameweeks
                    .map((d) => `GW${d.event} (${d.teams.join(', ')})`)
                    .join('; ')}.`}
            </p>
          </div>
        </Panel>
      )}
    </>
  )
}
