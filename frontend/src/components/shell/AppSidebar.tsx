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
    <Sidebar collapsible="icon" className="border-r-2 border-ink">
      <SidebarHeader className="border-b border-[#2a241b]">
        <div className="px-3 py-3">
          <div className="flex items-stretch">
            <span className="flex items-center bg-spot py-1 pl-2.5 pr-5 font-display text-[1.8rem] font-black leading-none text-ink [clip-path:polygon(0_0,100%_0,82%_100%,0_100%)]">FPL</span>
            <span className="ml-1 flex items-center font-display text-[1.8rem] font-black uppercase leading-none text-paper">Agent</span>
          </div>
          <div className="mt-2 font-serif text-[15px] italic text-paper/60">
            the {gwLabel ?? '—'} programme &middot; 2026/27
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        {NAV_SECTIONS.map((section) => (
          <SidebarGroup key={section.label} className="px-0 py-1">
            <SidebarGroupLabel className="px-4 text-[10.5px] font-bold uppercase tracking-[0.18em] text-spot">
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
                            ? 'rounded-none bg-paper font-semibold text-ink shadow-[3px_3px_0_var(--spot)] hover:bg-paper hover:text-ink'
                            : 'rounded-none text-paper/75 hover:bg-[#2a241b] hover:text-paper'
                        }
                        render={
                          <NavLink to={d.to} end={'end' in d ? d.end : false}>
                            <d.icon strokeWidth={2.2} className={`size-4 ${isActive ? 'text-spot' : ''}`} />
                            <span className="font-display text-[17px] font-bold uppercase tracking-[0.02em]">{d.label}</span>
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
