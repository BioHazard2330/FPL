import { NavLink, useLocation } from 'react-router-dom'
import {
  Sidebar,
  SidebarContent,
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

  return (
    <Sidebar collapsible="icon" className="border-r border-divider">
      <SidebarHeader className="border-b border-divider">
        <div className="px-3 py-3">
          <div className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-lg bg-pitch-green font-display text-base font-bold text-pitch-green-ink">F</span>
            <span className="font-display text-xl font-semibold text-text">FPL AGENT</span>
          </div>
          <div className="mt-1.5 text-[12px] text-text-faint">
            {gwLabel ?? '—'} &middot; 2026/27 season
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        {NAV_SECTIONS.map((section) => (
          <SidebarGroup key={section.label} className="px-0 py-1">
            <SidebarGroupLabel className="px-4 text-[12px] font-bold text-text-faint">
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
    </Sidebar>
  )
}
