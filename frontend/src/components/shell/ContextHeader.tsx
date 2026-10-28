import { useLocation } from 'react-router-dom'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { crestUrl } from '@/lib/api'
import { currentDestination } from '@/lib/nav'
import { derivePhase, formatCountdown, useCountdown } from '@/lib/clock'
import { useLiveMeta } from '@/lib/useLiveMeta'
import { relativeTime } from '@/lib/time'
import { SyncButton } from '@/components/shell/SyncButton'

/** THE ONE BAR ABOVE EVERY SCREEN.
 *
 * It used to be three stacked strips (page title and signal count, a phase
 * pill with a countdown, and a breadcrumb inside each screen) saying "GW8" and
 * "live" three times. This is one: where you are, how long until the next
 * deadline, which matches are on, and how fresh the data is. Everything rides
 * the single `useLiveMeta` poll; the countdown ticks locally against FPL's own
 * deadline time. */
export function ContextHeader() {
  const { pathname } = useLocation()
  const dest = currentDestination(pathname)
  const live = useLiveMeta()
  const countdown = useCountdown(live?.gw?.next_deadline_time ?? null)
  const matches = live?.active_matches ?? []
  const phase = derivePhase(live?.gw?.state, countdown?.totalMs ?? null, matches.length)

  const updated = relativeTime(live?.generated_at)
  const ageMs = live?.generated_at ? Date.now() - new Date(live.generated_at).getTime() : null
  const isFresh = ageMs !== null && ageMs < 5 * 60 * 1000
  const deadlineName = (live?.gw?.next_deadline_name?.replace(/Gameweek\s*/, 'GW') ?? 'Next') + ' deadline'
  const urgent = phase.phase === 'FINAL_CALL' || phase.phase === 'IMMINENT'

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 whitespace-nowrap border-b border-divider bg-panel/80 px-5 shadow-[0_8px_24px_-16px_rgba(0,0,0,0.9)] backdrop-blur-none">
      <SidebarTrigger />
      <dest.icon strokeWidth={2} className="size-4 text-text-faint" />
      <h1 className="font-display text-xl font-semibold uppercase leading-none tracking-[0.04em] text-text">{dest.label}</h1>

      <div className="ml-4 flex items-center gap-3 border-l border-divider pl-4 text-[13px]">
        {matches.length > 0 ? (
          <span className="flex items-center gap-1.5 font-semibold text-alert-red">
            <span className="size-1.5 animate-pulse-live rounded-full bg-alert-red" />
            {matches.length} match{matches.length === 1 ? '' : 'es'} live
          </span>
        ) : (
          live?.gw?.event && (
            <span className="font-semibold text-text-muted">
              GW{live.gw.event}
              {phase.live ? ' in progress' : ''}
            </span>
          )
        )}
        {countdown && !countdown.expired && (
          <span className="text-text-faint" title={live?.gw?.next_deadline_time ? new Date(live.gw.next_deadline_time).toLocaleString([], { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }) : undefined}>
            {deadlineName} in{' '}
            <span className={`tabular font-display text-lg font-semibold leading-none ${urgent ? phase.ink : 'text-text'}`}>
              {formatCountdown(countdown)}
            </span>
          </span>
        )}
      </div>

      <div className="ml-auto flex items-center gap-4">
        {matches.length > 0 && (
          <div className="hidden items-center gap-1.5 xl:flex">
            {matches.slice(0, 5).map((m) => {
              const home = crestUrl(m.home_code)
              const away = crestUrl(m.away_code)
              return (
                <span
                  key={m.match_id}
                  className={`flex items-center gap-1.5 rounded px-1.5 py-1 text-xs ${m.is_squad_match ? 'bg-broadcast-gold/15 ring-1 ring-broadcast-gold/30' : 'bg-raised'}`}
                  title={`${m.home_short} ${m.home_score ?? 0}-${m.away_score ?? 0} ${m.away_short}`}
                >
                  {home && <img src={home} alt="" className="size-3.5" />}
                  <span className="tabular font-bold text-text">
                    {m.home_score ?? 0}-{m.away_score ?? 0}
                  </span>
                  {away && <img src={away} alt="" className="size-3.5" />}
                </span>
              )
            })}
          </div>
        )}
        <span className={`flex items-center gap-1.5 text-[13px] ${isFresh ? 'text-text-muted' : live ? 'text-broadcast-gold' : 'text-text-faint'}`}>
          <span className={`size-1.5 rounded-full ${isFresh ? 'bg-pitch-green' : live ? 'bg-broadcast-gold' : 'bg-text-faint'}`} />
          <span className="hidden lg:inline">{updated ? `Updated ${updated}` : 'Connecting'}</span>
        </span>
        <SyncButton />
      </div>
    </header>
  )
}
