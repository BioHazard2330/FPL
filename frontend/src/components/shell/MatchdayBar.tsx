import { crestUrl } from '@/lib/api'
import { derivePhase, formatCountdown, useCountdown } from '@/lib/clock'
import { useLiveMeta } from '@/lib/useLiveMeta'

/** THE MATCHDAY BAR - the scoreboard bug of the whole application.
 *
 * One persistent broadcast strip, on every screen, answering the questions a
 * manager asks before any other: what time is it in the football week, how
 * long have I got, is anything happening right now, and are my players on
 * the pitch. Before this the app had no clock at all and no ambient sense of
 * the gameweek - you had to open Live to find out whether football was even
 * being played.
 *
 * Everything here rides the `useLiveMeta` poll that the nav rail and context
 * header already share, so the bar costs no additional fetch. The countdown
 * itself ticks locally against a real backend deadline.
 *
 * It is deliberately loud in the final hours and quiet the rest of the week -
 * the strip's own colour IS the phase signal, which is the entire point of a
 * scoreboard bug.
 */
export function MatchdayBar() {
  const live = useLiveMeta()
  const deadlineIso = live?.gw?.next_deadline_time ?? null
  const countdown = useCountdown(deadlineIso)
  const matches = live?.active_matches ?? []
  const info = derivePhase(live?.gw?.state, countdown?.totalMs ?? null, matches.length)

  // Real squad players actually on the pitch right now - a straight count of
  // the squad rows the live match blocks already carry, never an estimate.
  const playingNow = matches.reduce((n, m) => n + (m.my_players?.filter((p) => (p.minutes ?? 0) > 0).length ?? 0), 0)
  const squadGoals = matches.reduce(
    (n, m) => n + (m.my_players?.reduce((g, p) => g + (p.goals ?? 0), 0) ?? 0),
    0,
  )
  const squadAssists = matches.reduce(
    (n, m) => n + (m.my_players?.reduce((a, p) => a + (p.assists ?? 0), 0) ?? 0),
    0,
  )

  if (!live) return null

  return (
    <div className="flex flex-wrap items-stretch border-b-2 border-divider bg-panel">
      {/* PHASE - the strip's identity, and the loudest thing on it when it
          matters. A flat block, so the colour reads at a glance. */}
      <div className={`flex shrink-0 items-center gap-2.5 px-6 py-3 ${info.fill}`}>
        {info.live && <span className="size-2 animate-pulse-live rounded-full bg-current" />}
        <span className="font-display text-base font-bold uppercase tracking-[0.16em]">{info.label}</span>
      </div>

      {/* THE CLOCK - the single number this bar exists for. */}
      {countdown && !countdown.expired && (
        <div className="flex shrink-0 items-baseline gap-3 border-r-2 border-divider px-6 py-1.5">
          <span className="text-[9px] font-bold uppercase leading-tight tracking-[0.16em] text-text-faint">
            {live.gw?.next_deadline_name ? `${live.gw.next_deadline_name.replace('Gameweek', 'GW')} deadline` : 'Deadline'}
          </span>
          <span className={`tabular font-display text-4xl font-bold leading-none ${info.ink}`}>
            {formatCountdown(countdown)}
          </span>
        </div>
      )}

      {/* WHAT IT MEANS - one line, so a phase word is never just decoration. */}
      <div className="flex min-w-0 flex-1 items-center px-5 py-2">
        <span className="truncate text-[11px] text-text-faint">{info.sub}</span>
      </div>

      {/* LIVE FOOTBALL - only ever rendered when football is genuinely on. */}
      {matches.length > 0 && (
        <div className="flex shrink-0 items-center gap-4 border-l-2 border-divider px-5 py-1.5">
          <div className="flex items-center gap-2">
            {matches.slice(0, 6).map((m) => {
              const home = crestUrl(m.home_code)
              const away = crestUrl(m.away_code)
              return (
                <span
                  key={m.match_id}
                  className={`flex items-center gap-1 px-1.5 py-0.5 ${m.is_squad_match ? 'bg-broadcast-gold/20' : ''}`}
                  title={`${m.home_short} ${m.home_score ?? 0}-${m.away_score ?? 0} ${m.away_short}`}
                >
                  {home && <img src={home} alt="" className="h-3.5 w-3.5" />}
                  <span className="tabular text-xs font-bold text-text">
                    {m.home_score ?? 0}-{m.away_score ?? 0}
                  </span>
                  {away && <img src={away} alt="" className="h-3.5 w-3.5" />}
                </span>
              )
            })}
          </div>
          {playingNow > 0 && (
            <span className="text-[10px] font-bold uppercase tracking-wide text-text-faint">
              <span className="tabular text-sm text-text">{playingNow}</span> of mine playing
            </span>
          )}
          {(squadGoals > 0 || squadAssists > 0) && (
            <span className="flex items-center gap-2 text-xs font-bold">
              {squadGoals > 0 && <span className="text-pitch-green">{squadGoals}G</span>}
              {squadAssists > 0 && <span className="text-broadcast-gold">{squadAssists}A</span>}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
