import { RoadAhead } from '@/components/command/RoadAhead'
import { chipName, Panel, Pill } from '@/components/ui/kit'
import type { ChipPlan, WeekPlanPayload } from '@/lib/types'

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
                ? `No double gameweek is scheduled in the next ${chips.horizon}.`
                : `Double gameweek${chips.double_gameweeks.length > 1 ? 's' : ''}: ${chips.double_gameweeks
                    .map((d) => `GW${d.event} (${d.teams.join(', ')})`)
                    .join('; ')}.`}
            </p>
          </div>
          {(chips.plan ?? []).map((c) => (
            <ChipLadder key={c.chip} plan={c} />
          ))}
        </Panel>
      )}
    </>
  )
}

/** The chip's worth in every gameweek left in its window, along the squad the plan expects to hold: the best week is the
 * recommendation, and the spread shows how much choosing it matters. */
function ChipLadder({ plan }: { plan: ChipPlan }) {
  const max = Math.max(...plan.ladder.map((w) => w.worth), 0.1)
  const min = Math.min(...plan.ladder.map((w) => w.worth))
  const what = plan.chip === 'bboost' ? 'bench' : 'captain'
  return (
    <div className="mt-5 border-t border-divider pt-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-display text-lg text-text">
          {chipName(plan.chip)}: GW{plan.event}
        </span>
        <span className="text-[14px] text-text-muted">
          {what} projected {plan.worth.toFixed(1)} that week ({plan.players.map((p) => `${p.name} ${p.xp.toFixed(1)}`).join(', ')}),{' '}
          {plan.this_week.toFixed(1)} this week. Expires after GW{plan.window_ends}; unplayed, it is worth nothing.
          {max - min < 3 ? ' Every week in the window is within 3 points, so play it whenever the bench is fit.' : ''}
        </span>
      </div>
      <div className="mt-3 flex items-end gap-1.5" role="img" aria-label={`${chipName(plan.chip)} worth by gameweek`}>
        {plan.ladder.map((w) => (
          <div key={w.event} className="flex w-10 flex-col items-center gap-1">
            <span className="font-mono text-[11px] tabular-nums text-text-muted">{w.worth.toFixed(1)}</span>
            <div className="flex h-16 w-full items-end">
              <div
                className={`bar-draw w-full rounded-t-sm ${
                  w.event === plan.event ? 'bg-broadcast-gold' : w.beyond_plan ? 'bg-text-faint/30' : 'bg-text-faint/60'
                }`}
                style={{ height: `${Math.max(6, (w.worth / max) * 100)}%` }}
                title={w.beyond_plan ? 'Squad beyond the planned horizon: the last planned squad is assumed' : undefined}
              />
            </div>
            <span className="text-[11px] text-text-faint">GW{w.event}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
