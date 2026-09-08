import { Activity, Crosshair, Goal, Radio, Route, Search, Users } from 'lucide-react'

export const DESTINATIONS = [
  { to: '/', label: 'Command', icon: Crosshair, end: true },
  { to: '/my-team', label: 'My Team', icon: Users },
  { to: '/plan', label: 'Plan', icon: Route },
  { to: '/football', label: 'Football', icon: Goal },
  { to: '/scout', label: 'Scout', icon: Search },
  { to: '/advanced', label: 'Advanced', icon: Activity },
  { to: '/live', label: 'Live', icon: Radio },
] as const

export function currentDestination(pathname: string) {
  return (
    DESTINATIONS.find((d) => ('end' in d && d.end ? pathname === d.to : pathname.startsWith(d.to) && d.to !== '/')) ??
    DESTINATIONS[0]
  )
}
