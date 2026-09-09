import { Activity, Crosshair, Goal, Radio, Route, Search, Shield, Trophy, User, Users } from 'lucide-react'

export const DESTINATIONS = [
  { to: '/', label: 'Command', icon: Crosshair, end: true },
  { to: '/my-team', label: 'My Team', icon: Users },
  { to: '/plan', label: 'Plan', icon: Route },
  { to: '/matchweek', label: 'Matchweek', icon: Trophy },
  { to: '/football', label: 'Football', icon: Goal },
  { to: '/scout', label: 'Scout', icon: Search },
  { to: '/advanced', label: 'Advanced', icon: Activity },
  { to: '/live', label: 'Live', icon: Radio },
] as const

/** Real section hierarchy over the same seven destinations - not new
 * routes, and deliberately not a collapsible tree. The three groups are
 * the three genuinely different questions this product answers: what do I
 * do (decision), what is happening in football (intelligence), and is the
 * machine itself healthy right now (operations). Ordering within each
 * group is unchanged, so no existing muscle memory breaks. */
export const NAV_SECTIONS: { label: string; routes: string[] }[] = [
  { label: 'Decision', routes: ['/', '/my-team', '/plan'] },
  { label: 'The football', routes: ['/matchweek', '/football'] },
  { label: 'Intelligence', routes: ['/scout'] },
  { label: 'Operations', routes: ['/live', '/advanced'] },
]

/** Profile routes are real destinations with no nav entry of their own - a
 * club or player page is reached by clicking, not from the rail. Without
 * these the header fell through to DESTINATIONS[0] and every player file
 * announced itself as "COMMAND". */
const DETAIL_DESTINATIONS = [
  { to: '/club/', label: 'Club file', icon: Shield },
  { to: '/player/', label: 'Player file', icon: User },
  { to: '/match/', label: 'Match report', icon: Goal },
] as const

export function currentDestination(pathname: string) {
  return (
    DETAIL_DESTINATIONS.find((d) => pathname.startsWith(d.to)) ??
    DESTINATIONS.find((d) => ('end' in d && d.end ? pathname === d.to : pathname.startsWith(d.to) && d.to !== '/')) ??
    DESTINATIONS[0]
  )
}
