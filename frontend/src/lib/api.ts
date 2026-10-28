// Real fetch wrapper for the `/api/<screen>` routes `live/sse_server.py`
// serves (2026-09-08, Phase 8.2 Stage 2). Every payload is produced by a
// `monitoring/api/*.py` builder reading the SAME real `DashboardContext`
// the old HTML dashboard already computes - this is a data-fetching layer,
// never a second computation. In dev, Vite's own proxy (`vite.config.ts`)
// forwards `/api/*` to the real `fpl live-server` process; in prod the
// built app is served from the same origin as that server.
import type {
  MatchStory,
  SquadNewsPayload,
  LeaguesPayload,
  ViewPlanPayload,
  SignalsPayload,
  ExplorerPayload,
  WhatIfPayload,
  DeskPayload,
  ComparePayload,
  AuditPayload,
  LiveConePayload,
  FieldPayload,
  ProjectionPayload,
  PlayerIndexRow,
  PreviewsPayload,
  AtlasPayload,
  ReceiptsPayload,
  AdvancedPayload, ClubProfilePayload, CommandPayload, FootballPayload, LiveSnapshot, MatchweekPayload,
  MatchReportPayload, MyTeamPayload, PlanPayload, PlayerProfilePayload, ScoutPayload, TablePayload, WeekPlanPayload,
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

export interface MadeTransferResult {
  status: 'recorded' | 'undone' | 'refused'
  reason?: string
  event?: number
  bank_tenths?: number
  plan_refresh?: string | null
}

async function postMadeTransfer(query: string): Promise<MadeTransferResult> {
  try {
    const res = await fetch(`/api/made-transfer?${query}`, { method: 'POST', headers: { 'X-FPL-Refresh': '1' } })
    if (!res.ok) return { status: 'refused', reason: `server said ${res.status}` }
    return (await res.json()) as MadeTransferResult
  } catch {
    return { status: 'refused', reason: 'the dashboard server is not reachable' }
  }
}

export function recordMadeTransfers(pairs: { outId: number; inId: number }[]): Promise<MadeTransferResult> {
  return postMadeTransfer(`moves=${pairs.map((p) => `${p.outId}:${p.inId}`).join(',')}`)
}

export function undoMadeTransfers(): Promise<MadeTransferResult> {
  return postMadeTransfer('undo=1')
}

export function fetchWeekPlanPayload(): Promise<WeekPlanPayload> {
  return getJson<WeekPlanPayload>('/api/weekplan')
}

export function fetchDeskPayload(): Promise<DeskPayload> {
  return getJson<DeskPayload>('/api/desk')
}

export function fetchPreviewsPayload(): Promise<PreviewsPayload> {
  return getJson<PreviewsPayload>('/api/previews')
}

export function fetchPlayersIndex(): Promise<{ players: PlayerIndexRow[] }> {
  return getJson<{ players: PlayerIndexRow[] }>('/api/players')
}

export function fetchExplorerPayload(): Promise<ExplorerPayload> {
  return getJson<ExplorerPayload>('/api/explorer')
}

export function fetchWhatIf(moves: [number, number][]): Promise<WhatIfPayload> {
  const q = moves.map(([o, i]) => `${o}:${i}`).join(',')
  return getJson<WhatIfPayload>(`/api/whatif${q ? `?moves=${q}` : ''}`)
}

export function fetchComparePayload(a: number, b: number): Promise<ComparePayload> {
  return getJson<ComparePayload>(`/api/compare?a=${a}&b=${b}`)
}

export function fetchProjection(playerId: number): Promise<ProjectionPayload> {
  return getJson<ProjectionPayload>(`/api/projection?id=${playerId}`)
}

export function fetchAuditPayload(event?: number): Promise<AuditPayload> {
  return getJson<AuditPayload>(event ? `/api/audit?event=${event}` : '/api/audit')
}

export function fetchLiveCone(): Promise<LiveConePayload> {
  return getJson<LiveConePayload>('/api/livecone')
}

export function fetchFieldPayload(kind: 'population' | 'top10k'): Promise<FieldPayload> {
  return getJson<FieldPayload>(`/api/field?kind=${kind}`)
}

export function fetchMyTeamPayload(): Promise<MyTeamPayload> {
  return getJson<MyTeamPayload>('/api/myteam')
}

export function fetchPlanPayload(): Promise<PlanPayload> {
  return getJson<PlanPayload>('/api/plan')
}

export function fetchReceiptsPayload(): Promise<ReceiptsPayload> {
  return getJson<ReceiptsPayload>('/api/receipts')
}

export function fetchAtlasPayload(): Promise<AtlasPayload> {
  return getJson<AtlasPayload>('/api/atlas')
}

export function fetchTablePayload(): Promise<TablePayload> {
  return getJson<TablePayload>('/api/table')
}

export function fetchLiveStory(matchId: number): Promise<{ story: MatchStory; minute: number; provisional: boolean }> {
  return getJson<{ story: MatchStory; minute: number; provisional: boolean }>(`/api/livestory?id=${matchId}`)
}

export function fetchSquadNews(): Promise<SquadNewsPayload> {
  return getJson<SquadNewsPayload>('/api/squadnews')
}

export function fetchLeagues(): Promise<LeaguesPayload> {
  return getJson<LeaguesPayload>('/api/leagues')
}

export function fetchViewPlan(scales: Record<number, number>): Promise<ViewPlanPayload> {
  const q = Object.entries(scales).map(([k, v]) => `${k}:${v}`).join(',')
  return getJson<ViewPlanPayload>(`/api/viewplan?scales=${encodeURIComponent(q)}`)
}

export function fetchSignalsPayload(): Promise<SignalsPayload> {
  return getJson<SignalsPayload>('/api/signals')
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

/** Official Premier League headshot (transparent PNG), keyed by the FPL player
 * `code`. 110x140 for anything above a small avatar, 40x40 below. */
export function playerPhotoUrl(code: number, size: 'large' | 'small' = 'large'): string {
  return `https://resources.premierleague.com/premierleague25/photos/players/${size === 'small' ? '40x40' : '110x140'}/${code}.png`
}
