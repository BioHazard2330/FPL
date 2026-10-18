import { NavLink, useLocation } from 'react-router-dom'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import { DESTINATIONS, NAV_SECTIONS } from '@/lib/nav'
import { useLiveMeta } from '@/lib/useLiveMeta'
import { relativeTime } from '@/lib/time'

/** Compact football command rail (full redesign pass, Part 4) - replaces
 * the earlier "Bulletin Terminal" sidebar's full-width green pill active
 * state (still visually a generic app-shell button) with a broadcast
 * lower-third marker: a 3px green edge + text-color emphasis, no filled
 * background block. Real GW/season line under the wordmark and a real
 * data-status footer (last live-snapshot update) - both fed by the same
 * shared `useLiveMeta` poll every other piece of chrome reads from, never
 * a second invented "system status." */
export function AppSidebar() {
  const { pathname } = useLocation()
  const live = useLiveMeta()
  const gwLabel = live?.gw?.event ? `GW${live.gw.event}` : null
  const updated = relativeTime(live?.generated_at)
  // Real freshness check (full redesign pass - direct user complaint: the
  // status dot claimed "live" while the timestamp next to it read "4h
  // ago", a real violation of this project's own "never label data live
  // outside its freshness window" rule). A successful fetch alone doesn't
  // mean the underlying snapshot is fresh - only `generated_at` does.
  const ageMs = live?.generated_at ? Date.now() - new Date(live.generated_at).getTime() : null
  const isFresh = ageMs !== null && ageMs < 5 * 60 * 1000

  return (
    <Sidebar collapsible="icon" className="border-r border-divider">
      <SidebarHeader className="border-b border-divider">
        <div className="px-3 py-3">
          <div className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-lg bg-pitch-green font-display text-base font-bold text-pitch-green-ink">F</span>
            <span className="font-display text-xl font-semibold tracking-wide text-text">FPL AGENT</span>
          </div>
          <div className="mt-2 font-mono text-[12px] uppercase tracking-[0.1em] text-text-faint">
            {gwLabel ?? '—'} &middot; 2026/27
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        {NAV_SECTIONS.map((section) => (
          <SidebarGroup key={section.label} className="px-0 py-1">
            <SidebarGroupLabel className="px-4 text-[11px] font-bold uppercase tracking-[0.18em] text-text-faint">
              {section.label}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5 px-2">
                {section.routes.map((route) => {
                  const d = DESTINATIONS.find((x) => x.to === route)
                  if (!d) return null
                  const isActive = 'end' in d && d.end ? pathname === d.to : pathname.startsWith(d.to)
                  return (
                    <SidebarMenuItem key={d.to}>
                      <SidebarMenuButton
                        tooltip={d.label}
                        className={
                          isActive
                            ? 'rounded-lg bg-raised font-semibold text-text hover:bg-raised hover:text-text'
                            : 'rounded-lg text-text-muted hover:bg-raised/50 hover:text-text'
                        }
                        render={
                          <NavLink to={d.to} end={'end' in d ? d.end : false}>
                            <d.icon strokeWidth={2} className={`size-4 ${isActive ? 'text-pitch-green' : ''}`} />
                            <span className="text-[14px] font-medium">{d.label}</span>
                          </NavLink>
                        }
                      />
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter className="border-t border-divider">
        <div className="space-y-1 px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-[12px] font-bold uppercase tracking-wide text-text-faint">
            <span className={`size-1.5 rounded-full ${isFresh ? 'animate-pulse-live bg-pitch-green' : live ? 'bg-broadcast-gold' : 'bg-text-faint'}`} />
            {isFresh ? 'Synced' : live ? 'Synced (idle)' : 'Connecting'}
          </div>
          {updated && <div className="text-[12px] text-text-faint">Updated {updated}</div>}
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
