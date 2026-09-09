// Real fetch wrapper for the `/api/<screen>` routes `live/sse_server.py`
// serves (2026-09-08, Phase 8.2 Stage 2). Every payload is produced by a
// `monitoring/api/*.py` builder reading the SAME real `DashboardContext`
// the old HTML dashboard already computes - this is a data-fetching layer,
// never a second computation. In dev, Vite's own proxy (`vite.config.ts`)
// forwards `/api/*` to the real `fpl live-server` process; in prod the
// built app is served from the same origin as that server.
import type {
  AdvancedPayload, ClubProfilePayload, CommandPayload, FootballPayload, LiveSnapshot, MatchweekPayload,
  MatchReportPayload, MyTeamPayload, PlanPayload, PlayerProfilePayload, ScoutPayload,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    throw new ApiError(res.status, `${path} -> ${res.status}`)
  }
  return (await res.json()) as T
}

export function fetchCommandPayload(): Promise<CommandPayload> {
  return getJson<CommandPayload>('/api/command')
}

export function fetchMyTeamPayload(): Promise<MyTeamPayload> {
  return getJson<MyTeamPayload>('/api/myteam')
}

export function fetchPlanPayload(): Promise<PlanPayload> {
  return getJson<PlanPayload>('/api/plan')
}

export function fetchFootballPayload(): Promise<FootballPayload> {
  return getJson<FootballPayload>('/api/football')
}

export function fetchMatchweekPayload(): Promise<MatchweekPayload> {
  return getJson<MatchweekPayload>('/api/matchweek')
}

export function fetchClubProfile(teamId: number): Promise<ClubProfilePayload> {
  return getJson<ClubProfilePayload>(`/api/club?id=${teamId}`)
}

export function fetchPlayerProfile(playerId: number): Promise<PlayerProfilePayload> {
  return getJson<PlayerProfilePayload>(`/api/player?id=${playerId}`)
}

export function fetchMatchReport(matchId: number): Promise<MatchReportPayload> {
  return getJson<MatchReportPayload>(`/api/match?id=${matchId}`)
}

export function fetchScoutPayload(): Promise<ScoutPayload> {
  return getJson<ScoutPayload>('/api/scout')
}

export function fetchAdvancedPayload(): Promise<AdvancedPayload> {
  return getJson<AdvancedPayload>('/api/advanced')
}

/** The real, already-continuously-regenerated live-state file
 * (`monitoring/live_snapshot.py::build_live_snapshot`, written by the
 * live-match-poll process independent of this API layer) - served directly
 * as a static file, not a `/api/` route, since it's already real-time and
 * needs no `DashboardContext`/decision-cache involvement at all. */
export function fetchLiveSnapshot(): Promise<LiveSnapshot> {
  return getJson<LiveSnapshot>('/live_snapshot.json')
}

// Real, confirmed via direct fetch (2026-09-08, art-direction pass v3): this
// CDN only serves three discrete shirt sizes - every other pixel value 404s
// silently (img.complete=true, naturalWidth=0, no console error, no visible
// broken-image icon since it's a transparent webp response). A real bug this
// pass found live: the tier-size gallery work introduced arbitrary sizes
// (92/116/148/etc) that all 404'd. Every caller now requests a real size and
// this snaps it to the nearest one actually served.
const SHIRT_SIZES = [66, 110, 220] as const

/** Official FPL shirt CDN, keyed by team (never a per-player photo, so it can
 * never go stale after a transfer) - the exact same real asset
 * `legacy.py::_official_shirt_url` serves to the old dashboard. */
export function shirtUrl(teamCode: number | null, isGkp: boolean, size = 110): string | null {
  if (teamCode === null) return null
  const suffix = isGkp ? '_1' : ''
  const real = SHIRT_SIZES.reduce((best, s) => (Math.abs(s - size) < Math.abs(best - size) ? s : best))
  return `https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_${teamCode}${suffix}-${real}.webp`
}

/** Same-origin cached crest, served directly from `data/crests/` by
 * `live/sse_server.py`'s static handler - real, no CORS/referer issues. */
export function crestUrl(teamCode: number | null): string | null {
  return teamCode === null ? null : `/crests/t${teamCode}.png`
}
