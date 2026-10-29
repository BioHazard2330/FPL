import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchPricesPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { chipName } from '@/components/ui/kit'
import type { WeekPlanPayload } from '@/lib/types'

const signed = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}`
type Week = NonNullable<WeekPlanPayload['road_ahead']>['weeks'][number]
type Move = Week['moves'][number]

function MoveCard({ m, event, plan, rise }: { m: Move; event: number; plan: WeekPlanPayload; rise?: number | null }) {
  const short = (m.why_later?.short_now_tenths ?? 0) > 0
  return (
    <div className="border-2 border-ink bg-paper shadow-[3px_3px_0_var(--ink)]">
      <div className="flex items-end">
        <Link to={m.out_id ? `/player/${m.out_id}` : '#'} className="relative flex-1 overflow-hidden bg-raised">
          <PlayerPhoto code={m.out_photo} teamCode={m.out_team_code ?? null} isGkp={m.position === 'GKP'} className="mx-auto h-14 w-11 opacity-60 grayscale" />
        </Link>
        <span className="px-1 pb-4 font-display text-xl font-black text-spot">→</span>
        <Link to={m.in_id ? `/player/${m.in_id}` : '#'} className="relative flex-1 overflow-hidden bg-[color-mix(in_srgb,var(--pitch-green)_18%,var(--paper))]">
          <PlayerPhoto code={m.in_photo} teamCode={m.in_team_code ?? null} isGkp={m.position === 'GKP'} className="mx-auto h-14 w-11" />
        </Link>
      </div>
      <div className="border-t-2 border-ink px-2 py-1">
        <div className="truncate text-[11.5px] text-text-faint line-through decoration-alert-red/60">{m.out}</div>
        <div className="truncate font-display text-[15px] font-black uppercase leading-tight text-text">{m.into}</div>
        {m.hit && <div className="text-[11px] font-bold uppercase text-alert-red">−4 hit</div>}
        {rise !== null && rise !== undefined && rise >= 0.1 && (
          <div className={`mt-0.5 inline-block px-1 text-[10.5px] font-bold uppercase ${rise >= 0.25 ? 'bg-broadcast-gold text-ink' : 'text-broadcast-gold'}`} title="Fitted chance he rises £0.1m at the next overnight price update">
            rise tonight {Math.round(rise * 100)}%
          </div>
        )}
        {m.why_later && (
          <div className="mt-0.5 text-[10.5px] leading-snug text-text-faint" title="What this move adds in each gameweek alone, and whether it can be paid for now at strict sale prices">
            GW{plan.event} {signed(m.why_later.gain_this_week)} · GW{event} {signed(m.why_later.gain_in_its_week)}
            {short && <span className="font-semibold text-broadcast-gold"> · £{(m.why_later.short_now_tenths / 10).toFixed(1)}m short</span>}
          </div>
        )}
      </div>
    </div>
  )
}

/** THE ROAD MAP - the plan for every gameweek of its horizon as stations on one line: the free transfers in hand at each,
 * the moves made there (who leaves, who arrives, what the move earns that week and this, and whether the bank can pay for it
 * now), and the rolls that bank a transfer. Every station after this week is re-solved each week with the injuries and
 * prices of the day; the map is a direction, not a promise. */
export function RoadMap({ plan }: { plan: WeekPlanPayload }) {
  const prices = useFetch(fetchPricesPayload, [])
  const road = plan.road_ahead
  if (!road || road.weeks.length === 0) return null
  const moves = plan.moves ?? []
  const rise = new Map<number, number | null>()
  if (prices.status === 'ready' && prices.data.status === 'ok') {
    for (const r of [...(prices.data.targets ?? []), ...(prices.data.risers ?? []), ...(prices.data.squad ?? [])]) rise.set(r.player_id, r.p_rise)
  }
  const totalMoves = road.weeks.reduce((n, w) => n + w.moves.length, 0)
  return (
    <section className="px-6 pb-7 pt-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="voice text-lg text-text-muted">the plan of record, as far as it can see</div>
          <h2 className="font-display text-text">GW{plan.event} and beyond</h2>
        </div>
        <div className="flex gap-[2px] border-2 border-ink bg-ink">
          {[
            ['this week', moves.length === 0 ? 'roll' : `${moves.length} move${moves.length > 1 ? 's' : ''}`],
            ['over the road', `${totalMoves} moves`],
            ['against rolling now', signed(road.gain_vs_roll)],
            ['banked at the end', `${road.final_free_transfers} FT`],
          ].map(([k, v]) => (
            <div key={k} className="bg-paper px-3 py-1.5">
              <div className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-text-faint">{k}</div>
              <div className="tabular font-display text-xl font-black text-text">{v}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="relative mt-6 overflow-x-auto pb-2">
        <div className="relative grid min-w-[60rem] gap-3" style={{ gridTemplateColumns: `repeat(${road.weeks.length}, minmax(7.5rem, 1fr))` }}>
          <div className="pointer-events-none absolute inset-x-6 top-[1.35rem] h-[4px] bg-ink" />
          {road.weeks.map((w, i) => {
            const now = i === 0
            const chips = (plan.chip_outlook?.plan ?? []).filter((c) => c.event === w.event)
            return (
              <div key={w.event} className="relative">
                <div className="relative z-10 flex flex-col items-center">
                  <div className={`flex h-11 min-w-[4.5rem] items-center justify-center border-[3px] border-ink px-2 font-display text-xl font-black ${now ? 'bg-spot text-ink' : w.moves.length ? 'bg-ink text-paper' : 'bg-paper text-text'}`}>
                    GW{w.event}
                  </div>
                  <div className="mt-1.5 flex gap-0.5" title={`${w.free_transfers ?? '?'} free transfer(s) before this week's moves`}>
                    {Array.from({ length: 5 }, (_, k) => (
                      <span key={k} className={`h-2.5 w-3.5 border border-ink ${k < (w.free_transfers ?? 0) ? 'bg-pitch-green' : 'bg-paper'}`} />
                    ))}
                  </div>
                  <div className="mt-0.5 text-[10.5px] font-bold uppercase tracking-[0.1em] text-text-faint">{w.free_transfers ?? '?'} FT</div>
                  {chips.map((c) => (
                    <div key={c.chip} className="mt-1.5 rotate-[-4deg] border-2 border-ink bg-broadcast-gold px-1.5 font-display text-[12px] font-black uppercase text-ink shadow-[2px_2px_0_var(--ink)]" title={`${chipName(c.chip)}: worth ${c.worth.toFixed(1)} that week`}>
                      {chipName(c.chip)} {c.worth.toFixed(1)}
                    </div>
                  ))}
                </div>
                <div className="mt-3 space-y-3">
                  {w.moves.length === 0 ? (
                    <div className="border-2 border-dashed border-ink/40 px-2 py-3 text-center font-display text-[15px] font-black uppercase text-text-faint">roll</div>
                  ) : (
                    w.moves.map((m) => <MoveCard key={`${m.out}-${m.into}`} m={m} event={w.event} plan={plan} rise={m.in_id ? rise.get(m.in_id) : null} />)
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
      <p className="mt-3 max-w-4xl text-[12.5px] text-text-faint">
        Each later move had to earn {plan.min_move_gain} points over the horizon; the whole road is re-solved every week with that
        day's injuries and prices.{!road.proven && ' Best plan found within the time limit; not proven optimal.'}
      </p>
    </section>
  )
}
