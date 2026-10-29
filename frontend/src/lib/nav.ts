import { Activity, BookImage, Eye, Shuffle, FileText, Medal, Crosshair, Goal, ListOrdered, Newspaper, Scale, ScanSearch, Swords, Telescope, LocateFixed, Radio, Receipt, SlidersHorizontal, Route, Search, Shield, Trophy, User, Users } from 'lucide-react'

export const DESTINATIONS = [
  { to: '/', label: 'Command', icon: Crosshair, end: true },
  { to: '/my-team', label: 'My team', icon: Users },
  { to: '/plan', label: 'Plan', icon: Route },
  { to: '/war-room', label: 'War room', icon: Shuffle },
  { to: '/album', label: 'Squad album', icon: BookImage },
  { to: '/eye', label: 'Eye journal', icon: Eye },
  { to: '/live', label: 'Live', icon: Radio },
  { to: '/matchweek', label: 'League', icon: Trophy },
  { to: '/table', label: 'Team styles', icon: ListOrdered },
  { to: '/previews', label: 'Previews', icon: Swords },
  { to: '/football', label: 'My clubs', icon: Goal },
  { to: '/atlas', label: 'Shot map', icon: LocateFixed },
  { to: '/scout', label: 'Market', icon: Search },
  { to: '/compare', label: 'Compare', icon: Scale },
  { to: '/explorer', label: 'Explorer', icon: SlidersHorizontal },
  { to: '/desk', label: 'News', icon: Newspaper },
  { to: '/review', label: 'GW report', icon: FileText },
  { to: '/leagues', label: 'Mini-leagues', icon: Medal },
  { to: '/field', label: 'Versus the field', icon: Telescope },
  { to: '/audit', label: 'Luck check', icon: ScanSearch },
  { to: '/receipts', label: 'Track record', icon: Receipt },
  { to: '/advanced', label: 'System', icon: Activity },
] as const

/** Five groups, by the question each answers: what do I do this week, what is happening in the league, who should I buy,
 * how am I doing against everyone else, and is the machine healthy. Ordering inside a group runs from most to least used. */
export const NAV_SECTIONS: { label: string; routes: string[] }[] = [
  { label: 'This week', routes: ['/', '/my-team', '/album', '/eye', '/plan', '/war-room', '/live'] },
  { label: 'The league', routes: ['/matchweek', '/table', '/previews', '/football', '/atlas'] },
  { label: 'Players', routes: ['/scout', '/compare', '/explorer', '/desk'] },
  { label: 'How I am doing', routes: ['/review', '/leagues', '/field', '/audit', '/receipts'] },
  { label: 'System', routes: ['/advanced'] },
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
