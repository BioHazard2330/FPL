import Chart from 'react-apexcharts'
import { LivePlayByPlay, anyInPlay, useLiveMatches } from '@/components/match/PlayByPlay'
import { Note } from '@/components/ui/Info'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { LiveCone } from '@/components/live/LiveCone'
import { MatchCard } from '@/components/live/MatchCentre'
import { LivePitch } from '@/components/live/LivePitch'
import { DepartureBoard } from '@/components/live/DepartureBoard'
import { SwingBoard } from '@/components/live/SwingBoard'
import { crestUrl, fetchLiveSnapshot } from '@/lib/api'
import { describeChange, eventLabel } from '@/lib/text'
import { relativeTime } from '@/lib/time'
import { useFetch } from '@/lib/useFetch'
import { useCrowd } from '@/lib/crowd'
import { CHART_COLORS, areaFade, barFill, baseChart, formatRank, intAxisLabels, lastPoint, rankAxisLabels } from '@/lib/chartTheme'
import { ScreenError } from '@/components/shell/ScreenStates'
import type { LiveMatchEvent, LiveSnapshot, LiveSquadPlayer, UpcomingMatch } from '@/lib/types'

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
  const pbpMatches = useLiveMatches()
  const state = useFetch(fetchLiveSnapshot, [], 10000)
  const ready = state.status === 'ready' ? state.data : null
  const crowd = useCrowd(ready?.match_events ?? [], ready?.squad?.find((s) => s.is_captain)?.player_id ?? null)

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
  const points = p.points
  const livePointsById = new Map((points?.by_player ?? []).map((x) => [x.player_id, x]))
  const squad = p.squad ?? []
  const starting = squad.filter((s) => s.slot === 'starting')
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
      <Masthead right={
        <span className="flex items-center gap-4">
          <Link to="/tv" className="border-2 border-ink bg-ink px-2.5 py-0.5 font-display text-[13px] font-black uppercase tracking-[0.06em] text-paper hover:bg-spot hover:text-ink">TV mode</Link>
          <button type="button" onClick={crowd.toggle} title="A synthesised crowd: a murmur, and a roar when one of your players scores or assists"
            className={`border-2 border-ink px-2.5 py-0.5 font-display text-[13px] font-black uppercase tracking-[0.06em] ${crowd.on ? 'bg-spot text-ink' : 'bg-paper text-ink'}`}>
            {crowd.on ? 'Crowd on' : 'Crowd off'}
          </button>
          <span className="text-text-faint">Snapshot {relativeTime(p.generated_at) ?? '—'}</span>
        </span>
      } />

      {snapshotOld && !anyInPlay(pbpMatches) && (
        <div className="border-b border-divider bg-panel px-10 py-3">
          <span className="text-[12px] font-bold text-broadcast-gold">This is an old snapshot</span>
          <span className="ml-3 text-sm text-text-muted">
            Written {relativeTime(p.generated_at)}. Nothing polls outside the active window (a deadline's run-up and a gameweek's matches), so everything below is how things stood
            then. &ldquo;Sync now&rdquo; in the header brings it up to date.
          </span>
        </div>
      )}

      <Scoreboard p={p} starting={starting} />

      {squad.length > 0 && (
        <section className="px-10 py-6">
          <div className="mb-3 flex flex-wrap items-baseline gap-3">
            <h2 className="font-display text-text">Your eleven, live</h2>
            <span className="text-[13px] text-text-faint">points with the armband once he has minutes, xP before · red box: playing now · bonus is provisional until the match settles</span>
          </div>
          <LivePitch squad={squad} byPlayer={livePointsById} bonus={bonusDefcon} events={events} upcoming={p.upcoming ?? []} />
        </section>
      )}

      {anyInPlay(pbpMatches) && <LivePlayByPlay matches={pbpMatches} />}

      <SwingBoard />

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
      ) : (p.upcoming ?? []).length > 0 ? (
        <Upcoming matches={p.upcoming ?? []} />
      ) : (
        <div className="border-b border-divider px-10 py-8">
          <div className="font-display text-2xl font-bold text-text-faint">No match is live right now</div>
          <Note>
            The match centre &mdash; scoreline, possession and xG contest, momentum band, shot map, and your own players'
            in-match returns &mdash; fills in here from the fast poll channel the moment a fixture kicks off. Nothing is
            simulated in between.
          </Note>
        </div>
      )}

      {!anyInPlay(pbpMatches) && <LivePlayByPlay matches={pbpMatches} />}

      {(p.autosubs ?? []).length > 0 && (
        <section className="px-10 py-6">
          <h2 className="font-display text-text">Auto-sub watch</h2>
          <Note>Starters on 0 minutes and the bench player FPL brings on, in your bench order with a legal formation. Standby: his match is still to finish.</Note>
          <div className="mt-4 flex flex-wrap gap-4">
            {(p.autosubs ?? []).map((a) => (
              <div key={a.out} className={`flex items-center gap-3 border-2 border-ink px-4 py-2.5 shadow-[4px_4px_0_var(--ink)] ${a.status === 'made' ? 'bg-paper' : 'bg-raised'}`}>
                <span className={`px-1.5 font-display text-[12px] font-black uppercase ${a.status === 'made' ? 'bg-ink text-paper' : 'border-2 border-dashed border-ink text-text'}`}>{a.status === 'made' ? 'made' : 'standby'}</span>
                <span className="font-display text-lg font-black uppercase text-alert-red">{a.out_name} ▼</span>
                <span className="text-text-faint">→</span>
                <span className="font-display text-lg font-black uppercase text-pitch-green">{a.into_name ? `${a.into_name} ▲` : 'nobody eligible'}</span>
              </div>
            ))}
          </div>
        </section>
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
          <Note>Template picks you don't own, hauling right now.</Note>
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
              <Note>Running totals this gameweek, not a timed feed.</Note>
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
                          <div className="text-xs text-text-muted">{describeChange(c.event_type, c.old_value, c.new_value, c.impact)}</div>
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

/** THE COMING GAMEWEEK, between matches: every kickoff still to come, by day, with the squad players in each. The match
 * centre takes this place the moment a fixture kicks off. */
function Upcoming({ matches }: { matches: UpcomingMatch[] }) {
  const days = new Map<string, UpcomingMatch[]>()
  for (const m of matches) {
    const day = new Date(m.kickoff_time).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })
    days.set(day, [...(days.get(day) ?? []), m])
  }
  const yours = matches.reduce((n, m) => n + m.players.filter((x) => x.slot === 'starting').length, 0)
  return (
    <section className="px-10 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="voice text-lg text-text-muted">no league match in play · the match centre opens at kickoff</div>
          <h2 className="font-display text-text">GW{matches[0].event}: when your eleven play</h2>
        </div>
      </div>
      <div className="mt-5"><DepartureBoard matches={matches} /></div>
      <div className="mt-2 text-[13px] text-text-faint">{yours} of your starters across {matches.length} matches</div>
      <div className="mt-5 grid gap-6 xl:grid-cols-2">
        {[...days.entries()].map(([day, list]) => (
          <div key={day}>
            <div className="mb-2 border-b-2 border-ink pb-1 font-display text-lg font-black uppercase text-text">{day}</div>
            {list.map((m) => {
              const home = crestUrl(m.home_code), away = crestUrl(m.away_code)
              return (
                <div key={m.fixture_id} className={`grid grid-cols-[3.5rem_9.5rem_1fr] items-center gap-3 border-b border-divider py-2 ${m.players.length ? '' : 'opacity-55'}`}>
                  <span className="tabular font-display text-lg font-black text-text">
                    {new Date(m.kickoff_time).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })}
                  </span>
                  <span className="flex items-center gap-1.5 font-display text-[17px] font-black uppercase text-text">
                    {home && <img src={home} alt="" className="size-5" onError={(e) => { e.currentTarget.style.display = 'none' }} />}{m.home}
                    <span className="text-text-faint">v</span>
                    {m.away}{away && <img src={away} alt="" className="size-5" onError={(e) => { e.currentTarget.style.display = 'none' }} />}
                  </span>
                  <span className="flex flex-wrap gap-1.5">
                    {m.players.map((x) => (
                      <Link key={x.player_id} to={`/player/${x.player_id}`}
                        className={`border-2 px-1.5 py-0.5 text-[12px] font-bold ${x.slot === 'starting' ? 'border-ink bg-paper text-text' : 'border-divider text-text-faint'}`}>
                        {x.is_captain && <span className="mr-1 bg-broadcast-gold px-1 text-broadcast-gold-ink">C</span>}
                        {x.web_name}{x.xp !== null && <span className="ml-1 tabular text-pitch-green">{x.xp.toFixed(1)}</span>}
                      </Link>
                    ))}
                  </span>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </section>
  )
}

/** The scoreboard: the gameweek's points (or the eleven's projection before a ball is kicked), rank and its move, the
 * armband's haul and how many of the eleven have played, are playing and are still to play. */
function Scoreboard({ p, starting }: { p: LiveSnapshot; starting: LiveSquadPlayer[] }) {
  const points = p.points
  const rank = p.rank
  const projected = starting.reduce((t, s) => t + (s.xp ?? 0) * (s.is_captain ? 2 : 1), 0)
  const up = rank?.rank_gain != null ? rank.rank_gain > 0 : null
  const kicked = points && (points.played > 0 || points.live > 0)
  const next = (p.upcoming ?? [])[0]
  return (
    <section className="px-10 pt-6">
      <div className="grid border-2 border-ink bg-ink text-paper shadow-[6px_6px_0_var(--spot)] md:grid-cols-[minmax(0,1.3fr)_repeat(3,minmax(0,1fr))]">
        <div className="border-b-2 border-paper/15 p-5 md:border-b-0 md:border-r-2">
          <div className="text-[12px] font-bold uppercase tracking-[0.16em] text-paper/60">GW{p.event ?? ''} · {kicked ? 'points' : 'projected'}</div>
          <div className="tabular font-display text-[5.5rem] font-black leading-none">{kicked ? points!.points.toFixed(0) : projected.toFixed(0)}</div>
          {p.gw?.state && <div className="mt-1 inline-block bg-alert-red px-2 font-display text-[12px] font-black uppercase">{p.gw.state === 'LIVE' ? 'Live' : p.gw.state.replace(/_/g, ' ').toLowerCase()}</div>}
        </div>
        <div className="border-b-2 border-paper/15 p-5 md:border-b-0 md:border-r-2">
          <div className="text-[12px] font-bold uppercase tracking-[0.16em] text-paper/60">Live rank{rank?.precision ? ` · ${rank.precision}` : ''}</div>
          <div className="tabular font-display text-4xl font-black">{rank?.estimated_rank != null ? `~${rank.estimated_rank.toLocaleString()}` : '-'}</div>
          {up !== null && rank?.rank_gain != null && (
            <div className={`mt-1 font-display text-lg font-black ${up ? 'text-pitch-green' : 'text-alert-red'}`}>{up ? '▲' : '▼'} {Math.abs(rank.rank_gain).toLocaleString()}</div>
          )}
        </div>
        <div className="border-b-2 border-paper/15 p-5 md:border-b-0 md:border-r-2">
          <div className="text-[12px] font-bold uppercase tracking-[0.16em] text-paper/60">Armband</div>
          <div className="tabular font-display text-4xl font-black text-broadcast-gold">{kicked && points?.captain_points != null ? points.captain_points : '-'}</div>
          <div className="font-display text-lg font-black uppercase">{points?.captain_name ?? starting.find((s) => s.is_captain)?.web_name ?? ''}</div>
        </div>
        <div className="p-5">
          <div className="text-[12px] font-bold uppercase tracking-[0.16em] text-paper/60">Your eleven</div>
          {points ? (
            <div className="mt-1 grid grid-cols-3 gap-1 text-center">
              {([['Done', points.played, 'bg-paper text-ink'], ['Playing', points.live, 'bg-alert-red text-paper'], ['To play', points.yet_to_play, 'border-2 border-paper/50']] as const).map(([l, n, c]) => (
                <div key={l} className={`py-1 ${c}`}><div className="tabular font-display text-3xl font-black leading-none">{n}</div><div className="text-[10.5px] font-black uppercase">{l}</div></div>
              ))}
            </div>
          ) : next ? (
            <div className="mt-1 text-[14px]">First up: <b>{next.home}-{next.away}</b>, {new Date(next.kickoff_time).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })}</div>
          ) : null}
          {rank?.template_pct != null && <div className="mt-2 text-[12px] text-paper/70">{rank.template_pct.toFixed(0)}% of your team matches the top 10k</div>}
        </div>
      </div>
    </section>
  )
}
