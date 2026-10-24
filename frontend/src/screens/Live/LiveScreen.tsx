import Chart from 'react-apexcharts'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { LiveCone } from '@/components/live/LiveCone'
import { MatchCard } from '@/components/live/MatchCentre'
import { BonusDefconRail } from '@/components/live/BonusDefconRail'
import { fetchLiveSnapshot } from '@/lib/api'
import { describeChange, eventLabel } from '@/lib/text'
import { relativeTime } from '@/lib/time'
import { useFetch } from '@/lib/useFetch'
import { CHART_COLORS, areaFade, barFill, baseChart, formatRank, intAxisLabels, lastPoint, rankAxisLabels } from '@/lib/chartTheme'
import { ScreenError } from '@/components/shell/ScreenStates'
import type { LiveMatchEvent } from '@/lib/types'

const CLASS_COLOR: Record<string, string> = {
  FIT: 'text-pitch-green',
  'FIT BUT MONITORED': 'text-broadcast-gold',
  DOUBTFUL: 'text-broadcast-gold',
  'LIKELY UNAVAILABLE': 'text-alert-red',
  'CONFIRMED UNAVAILABLE': 'text-alert-red',
}

const RETURN_KIND: Record<LiveMatchEvent['kind'], { label: string; color: string }> = {
  goal: { label: 'Goal', color: 'text-pitch-green' },
  assist: { label: 'Assist', color: 'text-broadcast-gold' },
  red_card: { label: 'Red card', color: 'text-alert-red' },
}

/** Skeleton shaped like the control room it precedes (console strip, then
 * a match-centre-height block, then two wire columns) rather than a stack
 * of grey rectangles that promises a layout the screen never renders. */
function LiveSkeleton() {
  return (
    <div className="animate-pulse pb-16">
      <div className="border-b border-divider px-10 py-3">
        <div className="h-3 w-56 bg-raised" />
      </div>
      <div className="flex border-b border-divider">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="border-l border-divider px-6 py-4 first:border-l-0 first:pl-10">
            <div className="h-2 w-20 bg-raised" />
            <div className="mt-2 h-5 w-16 bg-raised" />
          </div>
        ))}
      </div>
      <div className="border-b border-divider px-10 py-8">
        <div className="mx-auto h-12 w-40 bg-raised" />
        <div className="mt-6 space-y-2">
          {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-3 w-full bg-raised" />)}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-px bg-divider lg:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="space-y-2 bg-void px-10 py-8">
            <div className="h-2 w-24 bg-raised" />
            {[0, 1, 2, 3, 4, 5].map((j) => <div key={j} className="h-4 w-full bg-raised" />)}
          </div>
        ))}
      </div>
    </div>
  )
}

export function LiveScreen() {
  const state = useFetch(fetchLiveSnapshot, [], 10000)

  if (state.status === 'loading') return <LiveSkeleton />
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Live channel unreachable"
        description={
          <>
            The browser could not read <code className="font-mono text-text">/live_snapshot.json</code>, the fast poll file
            the live-match poller writes. Nothing here is being shown from cache &mdash; there is simply no current state to
            show. The rest of the app reads a different channel and may still be fine.
          </>
        }
        message={state.error.message}
      />
    )
  }

  const p = state.data
  const isLive = p.gw?.state === 'LIVE'
  const matches = p.active_matches ?? []
  const events = p.match_events ?? []
  const changes = p.recent_changes ?? []
  const rank = p.rank
  const points = p.points
  const livePointsById = new Map((points?.by_player ?? []).map((x) => [x.player_id, x]))
  const squad = p.squad ?? []
  const starting = squad.filter((s) => s.slot === 'starting')
  const bench = squad.filter((s) => s.slot === 'bench')
  const rankArrowUp = rank?.rank_gain !== null && rank?.rank_gain !== undefined ? rank.rank_gain > 0 : null
  const charts = p.charts
  const snapshotAgeMs = p.generated_at ? Date.now() - new Date(p.generated_at).getTime() : null
  const snapshotOld = !isLive && snapshotAgeMs !== null && snapshotAgeMs > 30 * 60 * 1000
  const pointsChanges = p.points_changes
  const bonusDefcon = p.bonus_defcon ?? []
  const squadMatches = matches.filter((m) => m.is_squad_match).length
  // Column counts follow the number of panels that genuinely have data. A
  // `gap-px bg-divider` grid renders its empty track as a solid block, so a
  // hardcoded 2-column class leaves a bare grey half whenever one side is
  // legitimately absent (confirmed live: squad returns with no change log).
  const wireCols = [events.length > 0, changes.length > 0].filter(Boolean).length
  const chartCols = charts
    ? [charts.rank.events.length > 1, charts.cumulative_points.events.length > 1].filter(Boolean).length
    : 0

  return (
    <div className="data-in pb-16">
      <Masthead right={<span className="text-text-faint">Snapshot {relativeTime(p.generated_at) ?? '—'}</span>} />

      {snapshotOld && (
        <div className="border-b border-divider bg-panel px-10 py-3">
          <span className="text-[12px] font-bold text-broadcast-gold">This is an old snapshot</span>
          <span className="ml-3 text-sm text-text-muted">
            Written {relativeTime(p.generated_at)}. Nothing polls outside the active window (a deadline's run-up and a gameweek's matches), so everything below is how things stood
            then. &ldquo;Sync now&rdquo; in the header brings it up to date.
          </span>
        </div>
      )}

      {/* THE BOTTOM LINE - real gap found 2026-09-12 (direct user report:
          "cant even see where my live points is", plus a direct comparison
          against livefpl.net's own live-rank page). The actual live
          gameweek points total and the LiveFPL rank-change fields
          (old_rank/rank_gain/change_pct/safety_score/template_pct) were
          already computed server-side every real refresh - this project's
          own connector fetches them - but nothing on this screen ever
          rendered them. This is the one number the whole screen exists
          for; it now leads, at hero scale, before any operational status. */}
      {points && (
        <div className="border-b border-divider bg-panel px-10 py-8">
          <div className="flex flex-wrap items-end gap-10">
            <div>
              <div className="text-[13px] font-bold text-text-faint">Points this gameweek</div>
              <div className="tabular font-display text-7xl font-bold leading-none text-text">{points.points.toFixed(0)}</div>
            </div>
            {rank?.estimated_rank != null && (
              <div className="border-l border-divider pl-10">
                <div className="text-[13px] font-bold text-text-faint">
                  Live rank{rank.precision ? ` · ${rank.precision}` : ''}
                </div>
                <div className={`tabular font-display text-3xl font-bold ${rank.is_current ? 'text-text' : 'text-text-faint'}`}>
                  ~{rank.estimated_rank.toLocaleString()}
                  {!rank.is_current && <span className="ml-2 text-xs font-normal text-text-faint">not current</span>}
                </div>
                {rankArrowUp !== null && rank.rank_gain !== null && (
                  <div className={`mt-0.5 flex items-center gap-1.5 text-sm font-bold ${rankArrowUp ? 'text-pitch-green' : 'text-alert-red'}`}>
                    <span aria-hidden="true">{rankArrowUp ? '▲' : '▼'}</span>
                    {Math.abs(rank.rank_gain).toLocaleString()}
                    {rank.change_pct !== null && <span className="text-text-faint">({rank.change_pct >= 0 ? '+' : ''}{rank.change_pct.toFixed(1)}%)</span>}
                  </div>
                )}
              </div>
            )}
            {rank?.safety_score != null && (
              <div className="border-l border-divider pl-10">
                <div className="text-[13px] font-bold text-text-faint">Cushion</div>
                <div className="tabular font-display text-3xl font-bold text-text">{rank.safety_score.toFixed(0)}</div>
                <div className="mt-0.5 text-[12px] text-text-faint">points above the next rank band</div>
              </div>
            )}
            {rank?.template_pct != null && (
              <div className="border-l border-divider pl-10">
                <div className="text-[13px] font-bold text-text-faint">Overlap with the top 10k</div>
                <div className="tabular font-display text-3xl font-bold text-text">{rank.template_pct.toFixed(0)}%</div>
                <div className="mt-0.5 text-[12px] text-text-faint">of your team matches the template</div>
              </div>
            )}
            {points.captain_name && (
              <div className="border-l border-divider pl-10">
                <div className="text-[13px] font-bold text-text-faint">Captain</div>
                <div className="tabular font-display text-3xl font-bold text-broadcast-gold">
                  {points.captain_points ?? 0}
                  <span className="ml-2 font-sans text-base font-semibold text-text">{points.captain_name}</span>
                </div>
              </div>
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-text-faint">
            <span>{points.played} played</span>
            <span>{points.live} live</span>
            <span>{points.yet_to_play} yet to play</span>
            <span>{points.bench} on the bench</span>
          </div>
        </div>
      )}

      <LiveCone />

      {/* LIVE PROGRESSION - real gap found 2026-09-12 (direct user report:
          "amazing graphs... barely there" - a real sub-gameweek points/rank
          sample has been logged roughly every real minute of live play
          since 2026-08-28, but nothing ever plotted it in this app; the old
          dashboard.html only ever charted rank, never points, and never in
          the React app at all). Redraws with every 10s poll as new real
          samples land - genuinely live, not a static snapshot. */}
      {charts?.intragame && charts.intragame.timestamps.length > 1 && (
        <div className="grid grid-cols-1 gap-px border-b border-divider bg-divider lg:grid-cols-2">
          <div className="bg-void px-10 py-8">
            <div className="mb-3 text-[13px] font-bold text-text-faint">
              Your points through the gameweek
            </div>
            <Chart
              type="area"
              height={220}
              options={baseChart({
                chart: { type: 'area' },
                fill: areaFade(),
                stroke: { curve: 'stepline' },
                colors: [CHART_COLORS.primary],
                xaxis: { type: 'datetime', labels: { datetimeUTC: false } },
                yaxis: { labels: intAxisLabels },
                tooltip: { x: { format: 'HH:mm' } },
                annotations: lastPoint(
                  new Date(charts.intragame.timestamps[charts.intragame.timestamps.length - 1]).getTime(),
                  charts.intragame.points[charts.intragame.points.length - 1],
                  CHART_COLORS.primary,
                  `${charts.intragame.points[charts.intragame.points.length - 1]}`,
                ),
              })}
              series={[{
                name: 'Points',
                data: charts.intragame.timestamps.map((t, i) => [new Date(t).getTime(), charts!.intragame!.points[i]]),
              }]}
            />
          </div>
          <div className="bg-void px-10 py-8">
            <div className="mb-3 text-[13px] font-bold text-text-faint">
              Your rank through the gameweek
            </div>
            <Chart
              type="area"
              height={220}
              options={baseChart({
                chart: { type: 'area' },
                fill: areaFade(0.5, true),
                colors: [CHART_COLORS.secondary],
                // Reversed: a lower overall rank is better, so an unreversed
                // axis would draw a real climb up the leaderboard as a fall.
                stroke: { curve: 'stepline' },
                xaxis: { type: 'datetime', labels: { datetimeUTC: false } },
                yaxis: { reversed: true, labels: rankAxisLabels },
                tooltip: { x: { format: 'HH:mm' } },
                annotations: (() => {
                  const ranked = charts.intragame.timestamps
                    .map((t, i) => ({ t: new Date(t).getTime(), r: charts.intragame!.rank[i] }))
                    .filter((pt): pt is { t: number; r: number } => pt.r !== null)
                  const end = ranked[ranked.length - 1]
                  return end ? lastPoint(end.t, end.r, CHART_COLORS.secondary, formatRank(end.r)) : undefined
                })(),
              })}
              series={[{
                name: 'Rank',
                data: charts.intragame.timestamps
                  .map((t, i) => [new Date(t).getTime(), charts!.intragame!.rank[i]] as [number, number | null])
                  .filter((pt): pt is [number, number] => pt[1] !== null),
              }]}
            />
          </div>
        </div>
      )}

      {(matches.length > 0 || pointsChanges) && (
        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-1 px-8 py-4 text-[14px] text-text-muted">
          {matches.length > 0 && (
            <span>
              <span className="tabular font-semibold text-alert-red">{matches.length}</span> match{matches.length === 1 ? '' : 'es'} on now
              {squadMatches > 0 && <span className="text-broadcast-gold"> &middot; {squadMatches} with your players</span>}
            </span>
          )}
          {pointsChanges && (
            <span>
              GW{pointsChanges.event} points revised for <span className="tabular font-semibold text-text">{pointsChanges.squad_revisions}</span> of your players
              <span className="text-text-faint"> ({pointsChanges.total_revisions} league-wide, {pointsChanges.locked ? 'now locked' : 'still provisional'})</span>
            </span>
          )}
        </div>
      )}

      {/* MATCH CENTRE - the dominant object whenever football is actually
          happening. Real score, real per-team state, real momentum and shot
          geometry straight off the fast poll channel. */}
      {matches.length > 0 ? (
        <div className="border-b border-divider">
          <div className="px-10 pb-2 pt-6 text-[13px] font-bold text-text-faint">
            Matches, yours first
          </div>
          <div className="grid grid-cols-1 gap-px bg-divider 2xl:grid-cols-2">
            {matches.map((m) => <MatchCard key={m.match_id} m={m} />)}
          </div>
        </div>
      ) : (
        <div className="border-b border-divider px-10 py-8">
          <div className="font-display text-2xl font-bold text-text-faint">No match is live right now</div>
          <p className="mt-1.5 max-w-2xl text-sm text-text-muted">
            The match centre &mdash; scoreline, possession and xG contest, momentum band, shot map, and your own players'
            in-match returns &mdash; fills in here from the fast poll channel the moment a fixture kicks off. Nothing is
            simulated in between.
          </p>
        </div>
      )}

      {/* SQUAD IMPACT + LIVE BONUS/DEFCON - the two questions that only
          matter about MY squad during a live window, side by side. */}
      {squad.length > 0 && (
        <div className="grid grid-cols-1 gap-px bg-divider lg:grid-cols-[3fr_2fr]">
          <div className="bg-void px-10 py-8">
            <div className="mb-4 flex flex-wrap items-baseline gap-3">
              <span className="text-[13px] font-bold text-text-faint">Live squad impact</span>
              <span className="text-[13px] text-text-faint">actual points once a player has minutes, xP before kickoff</span>
            </div>
            <div className="grid grid-cols-1 gap-x-10 md:grid-cols-2">
              <div>
                <div className="pb-1 text-[12px] font-bold text-text-faint">Starting XI</div>
                <div className="divide-y divide-divider">
                  {starting.map((s) => {
                    const live = livePointsById.get(s.player_id)
                    const hasActual = live !== undefined && live.play_state !== 'yet_to_play'
                    const actual = hasActual ? live.points * live.multiplier : null
                    // Real differential tag (2026-09-12, direct user ask to
                    // match livefpl.net's own framing): low real ownership%
                    // (FPL's own official figure, not fabricated) hauling a
                    // real live score - the exact combination that moves
                    // rank the most. Thresholds are presentation-only, same
                    // convention as this file's own CLASS_COLOR/tie labels.
                    const isDiff = hasActual && (actual ?? 0) >= 5 && s.ownership_percent !== null && s.ownership_percent < 10
                    return (
                      <div key={s.player_id} className="flex items-center gap-2.5 py-2 text-sm">
                        {s.is_captain && <span className="flex size-4 shrink-0 items-center justify-center bg-broadcast-gold text-[12px] font-bold text-broadcast-gold-ink">C</span>}
                        {s.is_vice && <span className="flex size-4 shrink-0 items-center justify-center bg-raised text-[12px] font-bold text-text">V</span>}
                        <Link to={`/player/${s.player_id}`} className="truncate font-bold text-text hover:text-pitch-green">
                          {s.web_name}
                        </Link>
                        <span className="shrink-0 bg-raised px-1.5 py-0.5 text-[12px] font-bold text-text-muted">{s.position}</span>
                        {s.ownership_percent !== null && (
                          <span className="shrink-0 text-[12px] text-text-faint">{s.ownership_percent.toFixed(1)}% owned</span>
                        )}
                        {isDiff && <span className="shrink-0 text-[12px] font-bold text-broadcast-gold">Diff</span>}
                        {s.classification && s.classification !== 'FIT' && (
                          <span className={`shrink-0 text-[12px] font-bold ${CLASS_COLOR[s.classification] ?? 'text-text-faint'}`}>
                            {s.classification}
                          </span>
                        )}
                        {hasActual ? (
                          <span className="tabular ml-auto shrink-0 font-display font-bold text-text">
                            {actual}
                            {live.play_state === 'live' && <span className="ml-1 size-1.5 shrink-0 rounded-full bg-alert-red align-middle" />}
                          </span>
                        ) : (
                          <span className="tabular ml-auto shrink-0 font-semibold text-text-faint">{s.xp !== null ? `${s.xp.toFixed(1)} xP` : '—'}</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
              <div className="mt-6 md:mt-0">
                <div className="pb-1 text-[12px] font-bold text-text-faint">Bench</div>
                <div className="divide-y divide-divider opacity-70">
                  {bench.map((s) => {
                    const live = livePointsById.get(s.player_id)
                    const hasActual = live !== undefined && live.play_state !== 'yet_to_play'
                    const actual = hasActual ? live.points * live.multiplier : null
                    return (
                      <div key={s.player_id} className="flex items-center gap-2.5 py-2 text-sm">
                        <span className="truncate font-bold text-text">{s.web_name}</span>
                        <span className="shrink-0 bg-raised px-1.5 py-0.5 text-[12px] font-bold text-text-muted">{s.position}</span>
                        {hasActual ? (
                          <span className="tabular ml-auto shrink-0 font-semibold text-text">{actual}</span>
                        ) : (
                          <span className="tabular ml-auto shrink-0 font-semibold text-text-muted">{s.xp !== null ? `${s.xp.toFixed(1)} xP` : '—'}</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>

          <div className="bg-void px-10 py-8">
            <div className="mb-1 text-[13px] font-bold text-text-faint">Bonus &amp; defensive contribution</div>
            {bonusDefcon.some((r) => (r.minutes ?? 0) > 0) ? (
              <>
                <p className="mb-3 text-[13px] text-text-faint">
                  Provisional bonus is exactly that &mdash; BPS can still move until the match is settled.
                </p>
                <BonusDefconRail rows={bonusDefcon} />
              </>
            ) : (
              <p className="mt-2 max-w-sm text-sm text-text-muted">
                No squad player has minutes on the board yet. Live BPS standings and progress toward each player's real
                defensive-contribution threshold appear here once they do.
              </p>
            )}
          </div>
        </div>
      )}

      {/* THREATS - real gap found 2026-09-12 (direct user ask to match
          livefpl.net's own framing): the template's top-owned players you
          do NOT own, ranked by their real live points right now - the
          players actively working against your relative rank, straight
          off the same live payload your own squad's points already come
          from (no new source, no new network call). */}
      {p.threats.length > 0 && (
        <div className="border-t border-divider bg-void px-10 py-8">
          <div className="mb-1 text-[13px] font-bold text-text-faint">Threats</div>
          <p className="mb-3 text-[13px] text-text-faint">Template picks you don't own, hauling right now.</p>
          <div className="flex flex-wrap gap-x-10 gap-y-3">
            {p.threats.map((t) => (
              <div key={t.player_id} className="flex items-baseline gap-2">
                <span className="tabular font-display text-2xl font-bold text-alert-red">{t.points}</span>
                <Link to={`/player/${t.player_id}`} className="font-bold text-text hover:text-alert-red">
                  {t.web_name}
                </Link>
                <span className="bg-raised px-1.5 py-0.5 text-[12px] font-bold text-text-muted">{t.position}</span>
                <span className="text-[12px] text-text-faint">{t.ownership_percent.toFixed(1)}% owned</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* SQUAD RETURNS + CHANGE WIRE - cumulative real returns (not a
          minute-stamped feed: the backend sends counts, and this screen
          used to print a column of dashes by rendering fields that do not
          exist), alongside the real recent change log. */}
      {(events.length > 0 || changes.length > 0) && (
        <div className={`grid grid-cols-1 gap-px border-t border-divider bg-divider ${wireCols > 1 ? 'lg:grid-cols-2' : ''}`}>
          {events.length > 0 && (
            <div className="bg-void px-10 py-8">
              <div className="mb-1 text-[13px] font-bold text-text-faint">Squad returns</div>
              <p className="mb-3 text-[13px] text-text-faint">Running totals this gameweek, not a timed feed.</p>
              <div className="divide-y divide-divider">
                {events.map((e, i) => {
                  const kind = RETURN_KIND[e.kind]
                  return (
                    <div key={i} className="flex items-baseline gap-3 py-2.5">
                      <span className={`tabular font-display text-2xl font-bold ${kind?.color ?? 'text-text'}`}>{e.count}</span>
                      <span className={`text-[12px] font-bold ${kind?.color ?? 'text-text-faint'}`}>
                        {kind?.label ?? e.kind}
                      </span>
                      <span className="ml-auto text-sm font-bold text-text">{e.web_name ?? `#${e.player_id}`}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {changes.length > 0 && (
            <div className="bg-void px-10 py-8">
              <h2 className="mb-3 font-display text-xl font-semibold text-text">What changed</h2>
              <div className="divide-y divide-divider">
                {changes.slice(0, 15).map((c, i) => (
                  <div key={i} className="flex items-start gap-3 py-2.5 text-sm">
                    <span
                      className={`mt-1.5 size-1.5 shrink-0 rounded-full ${
 c.severity === 'high' ? 'bg-alert-red' : c.severity === 'medium' ? 'bg-broadcast-gold' : 'bg-text-faint'
 }`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-2">
                        <span className="font-bold text-text">{c.web_name ?? '—'}</span>
                        <span className="text-[12px] font-bold text-text-faint">
                          {eventLabel(c.event_type)}
                        </span>
                      </div>
                      {c.event_type === 'early_withdrawal' || c.event_type === 'lineup_confirmed' ? (
                        <div className="text-xs text-text-muted">
                          {c.event_type === 'early_withdrawal' ? 'taken off, no reason given: ' : ''}
                          <span className="text-text">{c.new_value?.replace(/_/g, ' ') ?? '—'}</span>
                        </div>
                      ) : (
                        (c.old_value !== null || c.new_value !== null) && (
                          <div className="text-xs text-text-muted">{describeChange(c.event_type, c.old_value, c.new_value)}</div>
                        )
                      )}
                    </div>
                    <span className="shrink-0 text-[12px] text-text-faint">{relativeTime(c.detected_at) ?? ''}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* SEASON TRAJECTORY - real rank/points/captain history */}
      {charts && (charts.rank.events.length > 1 || charts.cumulative_points.events.length > 1) && (
        <div className={`grid grid-cols-1 gap-px border-t border-divider bg-divider ${chartCols > 1 ? 'lg:grid-cols-2' : ''}`}>
          {charts.rank.events.length > 1 && (
            <div className="bg-void px-10 py-8">
              <div className="mb-3 text-[13px] font-bold text-text-faint">Overall rank trajectory</div>
              <Chart
                type="area"
                height={260}
                options={baseChart({
                  chart: { type: 'area' },
                  fill: areaFade(0.5, true),
                  colors: [CHART_COLORS.primary],
                  xaxis: { categories: charts.rank.events.map((e) => `GW${e}`), labels: { style: { cssClass: 'tabular' } } },
                  // Reversed: a lower overall rank is better, so an unreversed
                  // axis would draw a real climb as a fall.
                  yaxis: { reversed: true, labels: rankAxisLabels },
                  markers: { size: 4 },
                  annotations: lastPoint(
                    `GW${charts.rank.events[charts.rank.events.length - 1]}`,
                    charts.rank.values[charts.rank.values.length - 1],
                    CHART_COLORS.primary,
                    formatRank(charts.rank.values[charts.rank.values.length - 1]),
                  ),
                })}
                series={[{ name: 'Overall rank', data: charts.rank.values }]}
              />
            </div>
          )}
          {charts.cumulative_points.events.length > 1 && (
            <div className="bg-void px-10 py-8">
              <div className="mb-3 text-[13px] font-bold text-text-faint">Cumulative points</div>
              <Chart
                type="area"
                height={260}
                options={baseChart({
                  chart: { type: 'area' },
                  fill: areaFade(),
                  colors: [CHART_COLORS.secondary],
                  xaxis: { categories: charts.cumulative_points.events.map((e) => `GW${e}`), labels: { style: { cssClass: 'tabular' } } },
                  yaxis: { labels: intAxisLabels },
                  markers: { size: 4 },
                  annotations: lastPoint(
                    `GW${charts.cumulative_points.events[charts.cumulative_points.events.length - 1]}`,
                    charts.cumulative_points.values[charts.cumulative_points.values.length - 1],
                    CHART_COLORS.secondary,
                    `${charts.cumulative_points.values[charts.cumulative_points.values.length - 1]}`,
                  ),
                })}
                series={[{ name: 'Cumulative points', data: charts.cumulative_points.values }]}
              />
            </div>
          )}
          {charts.captain_contribution.events.length > 1 && (
            <div className={`bg-void px-10 py-8 ${chartCols > 1 ? 'lg:col-span-2' : ''}`}>
              <div className="mb-3 text-[13px] font-bold text-text-faint">Captain contribution per GW</div>
              <Chart
                type="bar"
                height={220}
                options={baseChart({
                  chart: { type: 'bar' },
                  fill: barFill(),
                  colors: [CHART_COLORS.accent],
                  dataLabels: { enabled: true, offsetY: -22, style: { fontSize: '12px', fontWeight: 700, colors: ['var(--text)'] }, background: { enabled: false } },
                  plotOptions: { bar: { dataLabels: { position: 'top' } } },
                  xaxis: { categories: charts.captain_contribution.events.map((e) => `GW${e}`), labels: { style: { cssClass: 'tabular' } } },
                  yaxis: { labels: intAxisLabels },
                })}
                series={[{ name: 'Captain points', data: charts.captain_contribution.values }]}
              />
            </div>
          )}
        </div>
      )}

    </div>
  )
}
