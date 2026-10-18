import { RoadAhead } from '@/components/command/RoadAhead'
import type { WeekPlanPayload } from '@/lib/types'

const CHIP_NAME: Record<string, string> = { wildcard: 'Wildcard', freehit: 'Free Hit', bboost: 'Bench Boost', '3xc': 'Triple Captain' }

/** THE PLAN, as the exact solver sees it: this week's moves, then the weeks
 * after, then the chips and whether the fixture list gives any of them a
 * reason to be played.
 *
 * This is the top of PLAN because it is the same plan COMMAND tells the
 * manager to execute, extended. The beam-search desk below it plans a
 * different question - one transfer a gameweek, chips included - and is kept
 * as a second opinion rather than a competing answer. */
export function WeekPlanDesk({ plan }: { plan: WeekPlanPayload }) {
  const moves = plan.moves ?? []
  const road = plan.road_ahead
  const later = road ? road.weeks.slice(1).reduce((n, w) => n + w.moves.length, 0) : 0
  const chips = plan.chip_outlook
  const horizon = road?.horizon ?? plan.horizon ?? 5

  return (
    <div>
      <div className="relative overflow-hidden px-10 pb-8 pt-7">
        <span className="ghost-watermark pointer-events-none absolute -top-8 right-2 select-none font-display text-[11rem] font-bold uppercase leading-none">
          PLAN
        </span>
        <div className="relative text-[13px] font-bold uppercase tracking-[0.15em] text-text-faint">
          GW{plan.event} &middot; the plan the exact solver found
        </div>
        <div className="verdict-block relative mt-4 inline-block bg-pitch-green py-4 pl-6 pr-14">
          <h1 className="font-display text-5xl font-bold uppercase leading-[0.9] text-pitch-green-ink md:text-6xl">
            {moves.length} now &middot; {later} later
          </h1>
        </div>
        {road && (
          <p className="relative mt-4 max-w-3xl text-lg leading-snug text-text-muted">
            <span className="tabular font-display text-3xl font-bold text-pitch-green">
              {road.gain_vs_roll >= 0 ? '+' : ''}
              {road.gain_vs_roll.toFixed(1)}
            </span>{' '}
            points over the next {horizon} gameweeks against rolling this week. This week:{' '}
            {moves.length === 0 ? 'nothing' : moves.map((m) => `${m.out.name} to ${m.into.name}`).join(', ')}.
          </p>
        )}
      </div>

      <RoadAhead plan={plan} />

      {chips && (
        <section className="border-t border-divider bg-panel px-10 py-8">
          <div className="mb-3 text-[13px] font-bold uppercase tracking-[0.15em] text-text-faint">Chips</div>
          <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3">
            <div className="flex flex-wrap gap-2">
              {chips.available.length === 0 ? (
                <span className="text-sm text-text-muted">None left in this window.</span>
              ) : (
                chips.available.map((c) => (
                  <span key={c} className="bg-broadcast-gold px-2.5 py-1 text-[13px] font-bold uppercase tracking-[0.1em] text-broadcast-gold-ink">
                    {CHIP_NAME[c] ?? c}
                  </span>
                ))
              )}
            </div>
            <p className="max-w-2xl text-sm text-text-muted">
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
        </section>
      )}
    </div>
  )
}
