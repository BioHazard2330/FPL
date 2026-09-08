import { useLocation } from 'react-router-dom'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { currentDestination } from '@/lib/nav'
import { useLiveMeta } from '@/lib/useLiveMeta'
import { relativeTime } from '@/lib/time'

/** Global contextual header + live intelligence strip (full redesign pass,
 * Part 4) - replaces the bare `<SidebarTrigger>`-only bar every screen sat
 * under before. Left: section identity. Centre: real GW/state, the one
 * piece of context genuinely shared by every screen. Right: live data
 * status + real signal counts pulled from the SAME live-snapshot poll the
 * nav rail already uses - never a second, independently-invented status
 * source. Counts are honestly omitted (not zeroed) when the backend hasn't
 * produced them yet. */
export function ContextHeader() {
  const { pathname } = useLocation()
  const dest = currentDestination(pathname)
  const live = useLiveMeta()

  const gwLabel = live?.gw?.event ? `GW${live.gw.event}` : null
  const gwState = live?.gw?.state
  const updated = relativeTime(live?.generated_at)
  const matches = live?.active_matches?.length ?? 0
  const changes = live?.recent_changes?.length ?? 0
  // Real freshness check, same rule as the nav rail's own status dot - a
  // successful fetch isn't the same claim as "this data is current."
  const ageMs = live?.generated_at ? Date.now() - new Date(live.generated_at).getTime() : null
  const isFresh = ageMs !== null && ageMs < 5 * 60 * 1000

  return (
    <header className="border-b-2 border-divider">
      <div className="flex items-center gap-3 px-4 py-2">
        <SidebarTrigger />
        <dest.icon strokeWidth={2.25} className="size-3.5 text-text-faint" />
        <span className="text-xs font-bold uppercase tracking-[0.12em] text-text-muted">{dest.label}</span>

        <div className="mx-auto hidden items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-text-faint md:flex">
          {gwLabel && (
            <>
              <span className="font-bold text-text">{gwLabel}</span>
              {gwState && <span>&middot; {gwState.replace(/_/g, ' ')}</span>}
            </>
          )}
        </div>

        <div className="ml-auto flex items-center gap-3 font-mono text-[11px] uppercase tracking-[0.08em]">
          {matches > 0 && (
            <span className="flex items-center gap-1.5 text-alert-red">
              <span className="size-1.5 animate-pulse-live rounded-full bg-alert-red" />
              {matches} live match{matches === 1 ? '' : 'es'}
            </span>
          )}
          {changes > 0 && <span className="text-broadcast-gold">{changes} signal{changes === 1 ? '' : 's'}</span>}
          <span className={isFresh ? 'text-pitch-green' : live ? 'text-broadcast-gold' : 'text-text-faint'}>
            {updated ? `Synced ${updated}` : 'Connecting'}
          </span>
        </div>
      </div>
    </header>
  )
}
