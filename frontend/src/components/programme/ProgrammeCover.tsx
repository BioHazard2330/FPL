import { forwardRef } from 'react'
import { crestUrl, playerPhotoUrl, shirtUrl } from '@/lib/api'
import type { WeekPlanLineup, WeekPlanLineupPlayer, WeekPlanPayload } from '@/lib/types'

/** THE MATCHDAY PROGRAMME - the gameweek printed as a programme cover: the masthead with the issue number and the
 * deadline, the captain as the cover star, the call, the eleven on the back-page team sheet, the fixtures and the chase.
 * Images go through the dashboard's own `/img` proxy so the cover can be saved as a picture. */

export const proxied = (url: string | null) => (url ? `/img?u=${encodeURIComponent(url)}` : null)

type Player = WeekPlanLineupPlayer

export const ProgrammeCover = forwardRef<HTMLDivElement, { plan: WeekPlanPayload; deadline: string | null }>(({ plan, deadline }, ref) => {
  const la = (plan.lineup_after ?? plan.lineup_now) as WeekPlanLineup
  const starting = la.starting as Player[]
  const bench = la.bench as Player[]
  const captain = starting.find((p) => p.player_id === la.captain_id)
  const moves = plan.moves ?? []
  const call = moves.length === 0 ? 'Roll the transfer' : moves.map((m) => `${m.out.name} out, ${m.into.name} in`).join(' · ')
  const top10k = plan.rank_targets?.targets.find((t) => t.rank === 10000)
  const rows = (['GKP', 'DEF', 'MID', 'FWD'] as const).map((pos) => starting.filter((p) => p.position === pos))
  const fixtureOf = (p: Player) => {
    const f = (plan.fixtures as Record<string, { event: number; opponent_short: string; is_home: boolean; difficulty: number }[]> | undefined)?.[String(p.team_code)]
    const next = f?.find((x) => x.event === plan.event)
    return next ? `${next.opponent_short} ${next.is_home ? 'H' : 'A'}` : ''
  }
  const date = deadline ? new Date(deadline) : null
  return (
    <div ref={ref} className="programme @container relative aspect-[1/1.414] w-full overflow-hidden bg-[#f3ead6] text-[#17130e]">
      <div className="programme-grain pointer-events-none absolute inset-0" />
      <div className="relative flex h-full flex-col">
        <div className="flex items-stretch border-b-[6px] border-[#17130e]">
          <div className="flex items-center bg-[#ff4614] px-[3.5%] py-[2.2%]">
            <span className="font-display text-[clamp(1rem,3.6cqw,2.6rem)] font-black uppercase leading-none">FPL</span>
          </div>
          <div className="flex flex-1 items-center justify-between px-[3%]">
            <div>
              <div className="font-display text-[clamp(0.5rem,1.4cqw,1rem)] font-black uppercase tracking-[0.3em]">Official matchday programme</div>
              <div className="font-display text-[clamp(0.9rem,3cqw,2.2rem)] font-black uppercase leading-none">Season 2026/27</div>
            </div>
            <div className="text-right">
              <div className="font-display text-[clamp(0.5rem,1.3cqw,1rem)] font-black uppercase tracking-[0.2em]">Issue</div>
              <div className="font-display text-[clamp(1.4rem,6cqw,4.6rem)] font-black leading-[0.8]">No.{plan.event}</div>
            </div>
          </div>
        </div>

        <div className="relative flex-1 overflow-hidden" style={{ background: 'radial-gradient(ellipse at 60% 30%, #ff6a3d 0%, #ff4614 35%, #c4300a 100%)' }}>
          <div className="absolute inset-0 opacity-25 [background-image:repeating-linear-gradient(115deg,#17130e_0_2px,transparent_2px_14px)]" />
          <div className="absolute left-[4%] top-[5%] z-10 max-w-[55%]">
            <div className="inline-block -rotate-2 bg-[#17130e] px-[3%] py-[1%] font-display text-[clamp(0.55rem,1.7cqw,1.3rem)] font-black uppercase tracking-[0.2em] text-[#ffc400]">Gameweek {plan.event} · the armband</div>
            <div className="mt-[4%] font-display text-[clamp(2rem,11cqw,8.5rem)] font-black uppercase leading-[0.78] text-[#f3ead6] [text-shadow:0.06em_0.06em_0_#17130e]">
              {captain?.name ?? '—'}
            </div>
            {captain && <div className="mt-[3%] font-display text-[clamp(0.7rem,2.6cqw,2rem)] font-black text-[#17130e]">{(captain.xp * 2).toFixed(1)} expected points, doubled · {fixtureOf(captain)}</div>}
          </div>
          {captain?.photo_code && (
            <img src={proxied(playerPhotoUrl(captain.photo_code, 'hero')) ?? ''} alt="" crossOrigin="anonymous"
              className="absolute bottom-0 right-[-4%] h-[96%] object-contain [filter:drop-shadow(0.6cqw_0.6cqw_0_#17130e)]" />
          )}
          <div className="absolute bottom-[4%] left-[4%] z-10 max-w-[52%] border-[3px] border-[#17130e] bg-[#f3ead6] px-[3%] py-[2%] shadow-[0.5cqw_0.5cqw_0_#17130e]">
            <div className="font-display text-[clamp(0.5rem,1.3cqw,1rem)] font-black uppercase tracking-[0.25em] text-[#ff4614]">The call</div>
            <div className="font-display text-[clamp(0.8rem,2.6cqw,2rem)] font-black uppercase leading-[0.95]">{call}</div>
            {moves.length > 0 && <div className="mt-[2%] text-[clamp(0.5rem,1.4cqw,1rem)] font-semibold">+{(plan.gain_vs_roll ?? 0).toFixed(1)} over {plan.horizon ?? 5} gameweeks against rolling</div>}
          </div>
        </div>

        <div className="grid grid-cols-[1.35fr_1fr] border-t-[6px] border-[#17130e]">
          <div className="border-r-[3px] border-[#17130e] px-[3%] py-[2.5%]" style={{ background: 'repeating-linear-gradient(0deg, #3d8a47 0 9%, #367d40 9% 18%)' }}>
            <div className="font-display text-[clamp(0.5rem,1.3cqw,1rem)] font-black uppercase tracking-[0.25em] text-[#f3ead6]">Today's team</div>
            <div className="mt-[2%] flex flex-col-reverse gap-[3%]">
              {rows.map((row, i) => (
                <div key={i} className="flex justify-around">
                  {row.map((p) => (
                    <div key={p.player_id} className="flex w-[18%] flex-col items-center">
                      {shirtUrl(p.team_code ?? null, p.position === 'GKP', 110) && (
                        <img src={proxied(shirtUrl(p.team_code ?? null, p.position === 'GKP', 110)) ?? ''} alt="" crossOrigin="anonymous" className="w-[62%]" />
                      )}
                      <div className="mt-[4%] w-full truncate bg-[#17130e] px-[3%] text-center font-display text-[clamp(0.4rem,1.15cqw,0.9rem)] font-black uppercase text-[#f3ead6]">
                        {p.name}{p.player_id === la.captain_id ? ' (C)' : ''}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <div className="mt-[3%] text-[clamp(0.45rem,1.1cqw,0.85rem)] font-semibold text-[#f3ead6]">Bench: {bench.map((b) => b.name).join(', ')}</div>
          </div>
          <div className="flex flex-col justify-between px-[4%] py-[2.5%]">
            <div>
              <div className="font-display text-[clamp(0.5rem,1.3cqw,1rem)] font-black uppercase tracking-[0.25em] text-[#ff4614]">Deadline</div>
              <div className="font-display text-[clamp(0.9rem,2.8cqw,2.2rem)] font-black uppercase leading-none">
                {date ? date.toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}
              </div>
            </div>
            {top10k && (
              <div>
                <div className="font-display text-[clamp(0.5rem,1.3cqw,1rem)] font-black uppercase tracking-[0.25em] text-[#ff4614]">The chase</div>
                <div className="font-display text-[clamp(0.9rem,2.8cqw,2.2rem)] font-black leading-none">{top10k.gap > 0 ? `${top10k.gap} behind the top 10k` : 'inside the top 10k'}</div>
                {top10k.gap > 0 && <div className="text-[clamp(0.45rem,1.15cqw,0.9rem)] font-semibold">{top10k.per_week?.toFixed(1)} a week over {plan.rank_targets?.weeks_left}</div>}
              </div>
            )}
            <div>
              <div className="font-display text-[clamp(0.5rem,1.3cqw,1rem)] font-black uppercase tracking-[0.25em] text-[#ff4614]">Expected from the eleven</div>
              <div className="font-display text-[clamp(1.2rem,4.6cqw,3.6rem)] font-black leading-none">{(la.xp_total ?? starting.reduce((n, p) => n + p.xp, 0)).toFixed(1)}</div>
            </div>
            <div className="flex flex-wrap gap-[2%]">
              {[...new Set(starting.map((p) => p.team_code))].slice(0, 8).map((c) => c !== null && c !== undefined && (
                <img key={c} src={crestUrl(c) ?? ''} alt="" className="size-[clamp(14px,3cqw,32px)]" onError={(e) => { e.currentTarget.style.display = 'none' }} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
})
ProgrammeCover.displayName = 'ProgrammeCover'
