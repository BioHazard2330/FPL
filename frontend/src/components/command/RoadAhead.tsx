import { Panel } from '@/components/ui/kit'
import type { WeekPlanPayload } from '@/lib/types'

const signed = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}`

/** BEYOND THIS WEEK - how the plan continues, a gameweek per column. Only the next three are shown: past that the planner is
 * guessing at injuries and prices that do not exist yet, and a row of empty "roll" columns says nothing. Every column after
 * this week is a projection, re-solved each week; the quiet weeks are shown because a roll is how free transfers are banked. */
export function RoadAhead({ plan, title = 'Beyond this week (indicative)', lead }: { plan: WeekPlanPayload; compact?: boolean; title?: string; lead?: React.ReactNode }) {
  const road = plan.road_ahead
  if (!road) return null
  const weeks = road.weeks.slice(1, 4)
  if (weeks.length === 0) return null
  const busiest = Math.max(...weeks.map((w) => w.moves.length), 1)

  return (
    <Panel
      title={title}
      sub={
        <>
          {lead}
          Carrying the plan on is worth{' '}
          <span className="tabular font-semibold text-pitch-green">
            {road.gain_vs_roll >= 0 ? '+' : ''}
            {road.gain_vs_roll.toFixed(1)}
          </span>{' '}
          points over {road.horizon} gameweeks against rolling now. Each later move had to earn {plan.min_move_gain} points; they are re-solved with every week&rsquo;s injuries and prices.
        </>
      }
    >
      <div className="grid gap-px overflow-hidden rounded-lg bg-divider" style={{ gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))` }}>
        {weeks.map((w) => (
          <div key={w.event} className="bg-void px-4 pb-4 pt-3" style={{ minHeight: 56 + busiest * 38 }}>
            <div className="mb-2 font-display text-base font-semibold text-text-faint">GW{w.event}</div>
            {w.moves.length === 0 ? (
              <div className="text-[13px] text-text-faint">Roll</div>
            ) : (
              <div className="space-y-2">
                {w.moves.slice(0, 3).map((m) => (
                  <div key={`${m.out}-${m.into}`} className="tone border-pitch-green pl-2.5 text-[13px] leading-tight">
                    <div className="truncate text-text-muted">{m.out}</div>
                    <div className="truncate font-semibold text-text">&rarr; {m.into}</div>
                    {m.hit && <div className="text-[12px] font-semibold text-alert-red">costs a hit</div>}
                    {m.why_later && (
                      <div
                        className="mt-0.5 text-[11.5px] leading-snug text-text-faint"
                        title="What this move adds in each gameweek alone, and whether it can be paid for now on its own at strict sale prices"
                      >
                        GW{plan.event} {signed(m.why_later.gain_this_week)} · GW{w.event} {signed(m.why_later.gain_in_its_week)}
                        {m.why_later.short_now_tenths > 0 && <span className="text-broadcast-gold"> · £{(m.why_later.short_now_tenths / 10).toFixed(1)}m short now</span>}
                      </div>
                    )}
                  </div>
                ))}
                {w.moves.length > 3 && <div className="text-[12px] text-text-faint">and {w.moves.length - 3} more</div>}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="mt-3 text-[13px] text-text-faint">
        {road.final_free_transfers} free transfer{road.final_free_transfers === 1 ? '' : 's'} banked by the end of the horizon.
        {!road.proven && ' Best plan found within the time limit; not proven optimal.'}
      </div>
    </Panel>
  )
}
