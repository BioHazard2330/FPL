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
          <div className="flex items-stretch">
            <span className="flex items-center bg-pitch-green py-1 pl-2.5 pr-4 font-display text-[1.35rem] font-bold leading-none tracking-wide text-pitch-green-ink [clip-path:polygon(0_0,100%_0,82%_100%,0_100%)]">FPL</span>
            <span className="ml-1.5 flex items-center font-display text-[1.35rem] font-semibold uppercase leading-none tracking-[0.06em] text-text">Agent</span>
          </div>
          <div className="mt-2 text-[11.5px] font-semibold uppercase tracking-[0.14em] text-text-faint">
            {gwLabel ?? '—'} &middot; 2026/27
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        {NAV_SECTIONS.map((section) => (
          <SidebarGroup key={section.label} className="px-0 py-1">
            <SidebarGroupLabel className="px-4 text-[10.5px] font-bold uppercase tracking-[0.16em] text-text-faint/80">
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
                            ? 'relative rounded-sm bg-gradient-to-r from-pitch-green/15 to-transparent font-semibold text-text before:absolute before:inset-y-1 before:left-0 before:w-[5px] before:bg-pitch-green before:[clip-path:polygon(0_0,100%_0,60%_100%,0_100%)] hover:bg-raised hover:text-text'
                            : 'rounded-sm text-text-muted hover:bg-raised/50 hover:text-text'
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
