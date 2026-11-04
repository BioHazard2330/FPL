import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { Info } from '@/components/ui/Info'
import type { WeekPlanPayload } from '@/lib/types'

/** LINED UP: the moves the plan already has in mind for the coming weeks, so a player it wants later does not look ignored.
 * The whole road is re-solved every week, so these are intentions, not calls. */
interface RoadMove { out: string; into: string; in_id: number; in_photo: number | null; in_team_code: number | null; why_later?: { gain_this_week?: number; gain_in_its_week?: number; short_now_tenths?: number } }
interface RoadWeek { event: number; moves: RoadMove[] }

export function LinedUp({ plan }: { plan: WeekPlanPayload }) {
  const weeks = ((plan.road_ahead as { weeks?: RoadWeek[] } | null | undefined)?.weeks ?? []).filter((w) => w.event > (plan.event ?? 0) && w.moves.length > 0)
  if (!weeks.length) return null
  return (
    <div className="bare flex flex-wrap items-center gap-x-5 gap-y-2 border-2 border-ink bg-paper px-5 py-3 shadow-[4px_4px_0_var(--ink)]">
      <span className="flex items-center gap-2 font-display text-[14px] font-black uppercase tracking-[0.08em] text-text">
        Lined up
        <Info label="Lined up">Moves the plan expects to make in later weeks. It re-solves the whole road every week, so injuries, prices and news can change them.</Info>
      </span>
      {weeks.flatMap((w) => w.moves.map((m) => {
        const short = m.why_later?.short_now_tenths ?? 0
        return (
          <Link key={`${w.event}-${m.in_id}`} to={`/player/${m.in_id}`} className="flex items-center gap-2 hover:opacity-80"
            title={short > 0 ? `£${(short / 10).toFixed(1)}m short to do it now` : `${(m.why_later?.gain_this_week ?? 0).toFixed(1)} this week, ${(m.why_later?.gain_in_its_week ?? 0).toFixed(1)} in GW${w.event}`}>
            <span className="bg-ink px-1 font-display text-[11px] font-black text-paper">GW{w.event}</span>
            <PlayerPhoto code={m.in_photo} teamCode={m.in_team_code} className="h-8 w-6" />
            <span className="font-display text-[15px] font-black uppercase text-text">{m.into}</span>
            <span className="text-[11.5px] text-text-faint line-through">{m.out}</span>
          </Link>
        )
      }))}
    </div>
  )
}
