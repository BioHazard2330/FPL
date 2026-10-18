import { Link } from 'react-router-dom'
import type { WeekPlanPayload } from '@/lib/types'

/** WHO WEARS THE ARMBAND, WEEK BY WEEK.
 *
 * The top three projections for each coming gameweek if the squad is the one
 * the plan leaves you with. A name that tops the column every week is a
 * captain you can build around; a name that leads once and drops to third is
 * a one-week answer. Same expected points as the lineup, no second model. */
export function CaptainLadder({ plan }: { plan: WeekPlanPayload }) {
  const ladder = plan.captain_ladder ?? []
  if (ladder.length === 0) return null
  const top = Math.max(...ladder.flatMap((w) => w.picks.map((p) => p.xp)), 1)
  const lead = ladder.map((w) => w.picks[0]?.player_id)
  return (
    <section className="bg-panel px-10 py-10">
      <div className="mb-1 text-[13px] font-bold uppercase tracking-[0.15em] text-text-faint">Armband ladder</div>
      <p className="mb-6 max-w-3xl text-sm text-text-muted">
        Top three projected points per gameweek for the squad this plan leaves you with. Ranked by projection alone: this week the armband rule can prefer a close second.
      </p>
      <div className="grid gap-px bg-divider" style={{ gridTemplateColumns: `repeat(${ladder.length}, minmax(0, 1fr))` }}>
        {ladder.map((w, wi) => (
          <div key={w.event} className="bg-void px-3 pb-3 pt-3">
            <div className="mb-2 font-display text-lg font-bold text-text-faint">GW{w.event}</div>
            {w.picks.map((p, i) => {
              const repeat = lead.filter((id) => id === p.player_id).length
              return (
                <div key={p.player_id} className="mb-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <Link to={`/player/${p.player_id}`} className={`truncate text-sm hover:text-pitch-green ${i === 0 ? 'font-bold text-text' : 'text-text-muted'}`}>
                      {p.name}
                    </Link>
                    <span className="tabular text-xs font-bold text-pitch-green">{p.xp.toFixed(1)}</span>
                  </div>
                  <div className="mt-0.5 h-1 bg-raised">
                    <div className={`bar-draw h-full ${i === 0 ? 'bg-pitch-green' : 'bg-text-faint'}`} style={{ width: `${(p.xp / top) * 100}%` }} />
                  </div>
                  {i === 0 && repeat > 1 && wi === lead.indexOf(p.player_id) && (
                    <div className="mt-0.5 font-mono text-[11px] uppercase text-text-faint">leads {repeat} of {ladder.length}</div>
                  )}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </section>
  )
}
