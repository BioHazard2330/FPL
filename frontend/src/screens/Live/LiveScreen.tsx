import Chart from 'react-apexcharts'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { MatchCard } from '@/components/live/MatchCentre'
import { BonusDefconRail } from '@/components/live/BonusDefconRail'
import { fetchLiveSnapshot } from '@/lib/api'
import { relativeTime } from '@/lib/time'
import { useFetch } from '@/lib/useFetch'
import { CHART_COLORS, baseChart, flatAreaFill, intAxisLabels, rankAxisLabels } from '@/lib/chartTheme'
import { ScreenError } from '@/components/shell/ScreenStates'
import type { LiveMatchEvent } from '@/lib/types'

const CLASS_COLOR: Record<string, string> = {
  FIT: 'text-pitch-green',
  'FIT BUT MONITORED': 'text-broadcast-gold',
  DOUBTFUL: 'text-broadcast-gold',
  'LIKELY UNAVAILABLE': 'text-alert-red',
  'CONFIRMED UNAVAILABLE': 'text-alert-red',
}

const DECISION_STATUS_COLOR: Record<string, string> = {
  CURRENT: 'text-pitch-green',
  STALE: 'text-alert-red',
  RECOMPUTING: 'text-broadcast-gold',
}

const RETURN_KIND: Record<LiveMatchEvent['kind'], { label: string; color: string }> = {
  goal: { label: 'Goal', color: 'text-pitch-green' },
  assist: { label: 'Assist', color: 'text-broadcast-gold' },
  red_card: { label: 'Red card', color: 'text-alert-red' },
}

/** One cell of the control-room console strip. Deliberately not a card:
 * the cells share one band and are separated by rules, the way a real
 * broadcast control desk reads a row of monitors. */
function ConsoleCell({ label, children, wide = false }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`border-l-2 border-divider px-6 py-4 first:border-l-0 first:pl-10 ${wide ? 'min-w-0 flex-1' : 'shrink-0'}`}>
      <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  )
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
      <div className="flex border-b-2 border-divider">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="border-l-2 border-divider px-6 py-4 first:border-l-0 first:pl-10">
            <div className="h-2 w-20 bg-raised" />
            <div className="mt-2 h-5 w-16 bg-raised" />
          </div>
        ))}
      </div>
      <div className="border-b-2 border-divider px-10 py-8">
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
  const rec = p.recommendation
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
      <Masthead
        edition={isLive ? 'Control Room · ● LIVE' : 'Control Room'}
        title={`GW${p.event ?? '?'} · ${p.gw?.state ?? 'No live window'}`}
        right={<span className="text-text-faint">Snapshot {relativeTime(p.generated_at) ?? '—'}</span>}
      />

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
        <div className="border-b-2 border-divider bg-panel px-10 py-8">
          <div className="flex flex-wrap items-end gap-10">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Gameweek points</div>
              <div className="tabular font-display text-7xl font-bold leading-none text-text">{points.points.toFixed(0)}</div>
            </div>
            {rank?.estimated_rank != null && (
              <div className="border-l-2 border-divider pl-10">
                <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">
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
              <div className="border-l-2 border-divider pl-10">
                <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Safety score</div>
                <div className="tabular font-display text-3xl font-bold text-text">{rank.safety_score.toFixed(0)}</div>
                <div className="mt-0.5 text-[10px] text-text-faint">pts above the next rank band</div>
              </div>
            )}
            {rank?.template_pct != null && (
              <div className="border-l-2 border-divider pl-10">
                <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Template rating</div>
                <div className="tabular font-display text-3xl font-bold text-text">{rank.template_pct.toFixed(0)}%</div>
                <div className="mt-0.5 text-[10px] text-text-faint">match with the top-10k template</div>
              </div>
            )}
            {points.captain_name && (
              <div className="border-l-2 border-divider pl-10">
                <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Captain</div>
                <div className="tabular font-display text-3xl font-bold text-broadcast-gold">
                  {points.captain_points ?? 0}
                  <span className="ml-2 font-sans text-base font-semibold text-text">{points.captain_name}</span>
                </div>
              </div>
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-text-faint">
            <span>{points.played} played</span>
            <span>{points.live} live</span>
            <span>{points.yet_to_play} yet to play</span>
            <span>{points.bench} on the bench</span>
          </div>
        </div>
      )}

      {/* CONSOLE STRIP - the real control-room readout: is anything live,
          where do I stand, is the standing decision still valid, and have
          finished-GW points been revised under me. One band, rule-separated
          cells, no cards. */}
      <div className="flex flex-wrap items-stretch border-b-2 border-divider">
        <ConsoleCell label="Channel">
          <div className="flex items-center gap-2">
            <span className={`size-2.5 rounded-full ${isLive ? 'animate-pulse-live bg-alert-red' : 'bg-text-faint'}`} />
            <span className="font-display text-lg font-bold uppercase tracking-wide text-text">
              {isLive ? 'Live' : 'Standby'}
            </span>
          </div>
        </ConsoleCell>

        <ConsoleCell label="Live matches">
          <div className={`tabular font-display text-lg font-bold ${matches.length > 0 ? 'text-alert-red' : 'text-text-faint'}`}>
            {matches.length}
            {squadMatches > 0 && <span className="ml-2 text-sm font-semibold text-broadcast-gold">{squadMatches} with my players</span>}
          </div>
        </ConsoleCell>

        {rec?.status && (
          <ConsoleCell label="Standing decision">
            <div className={`font-display text-lg font-bold uppercase tracking-wide ${DECISION_STATUS_COLOR[rec.status] ?? 'text-text'}`}>
              {rec.status}
            </div>
            <div className="mt-0.5 text-[10px] text-text-faint">
              {rec.stale_reason ?? (rec.computed_at ? `computed ${relativeTime(rec.computed_at)}` : '')}
            </div>
          </ConsoleCell>
        )}

        {pointsChanges && (
          <ConsoleCell label={`GW${pointsChanges.event} revisions`} wide>
            <div className="tabular font-display text-lg font-bold text-text">
              {pointsChanges.squad_revisions}
              <span className="ml-1 text-sm font-normal text-text-faint">of {pointsChanges.total_revisions} league-wide</span>
            </div>
            <div className="mt-0.5 text-[10px] uppercase tracking-wide text-text-faint">
              {pointsChanges.locked ? 'gameweek locked' : 'still provisional'}
            </div>
          </ConsoleCell>
        )}
      </div>

      {/* MATCH CENTRE - the dominant object whenever football is actually
          happening. Real score, real per-team state, real momentum and shot
          geometry straight off the fast poll channel. */}
      {matches.length > 0 ? (
        <div className="border-b-2 border-divider">
          <div className="px-10 pb-2 pt-6 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">
            Match centre &mdash; squad matches first
          </div>
          <div className="grid grid-cols-1 gap-px bg-divider 2xl:grid-cols-2">
            {matches.map((m) => <MatchCard key={m.match_id} m={m} />)}
          </div>
        </div>
      ) : (
        <div className="border-b-2 border-divider px-10 py-8">
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
              <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Live squad impact</span>
              <span className="text-[11px] text-text-faint">actual points once a player has minutes, xP before kickoff</span>
            </div>
            <div className="grid grid-cols-1 gap-x-10 md:grid-cols-2">
              <div>
                <div className="pb-1 text-[10px] font-bold uppercase tracking-wide text-text-faint">Starting XI</div>
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
                        {s.is_captain && <span className="flex size-4 shrink-0 items-center justify-center bg-broadcast-gold text-[9px] font-bold text-broadcast-gold-ink">C</span>}
                        {s.is_vice && <span className="flex size-4 shrink-0 items-center justify-center bg-raised text-[9px] font-bold text-text">V</span>}
                        <Link to={`/player/${s.player_id}`} className="truncate font-bold text-text hover:text-pitch-green">
                          {s.web_name}
                        </Link>
                        <span className="shrink-0 bg-raised px-1.5 py-0.5 text-[9px] font-bold text-text-muted">{s.position}</span>
                        {s.ownership_percent !== null && (
                          <span className="shrink-0 text-[10px] text-text-faint">{s.ownership_percent.toFixed(1)}% owned</span>
                        )}
                        {isDiff && <span className="shrink-0 text-[9px] font-bold uppercase text-broadcast-gold">Diff</span>}
                        {s.classification && s.classification !== 'FIT' && (
                          <span className={`shrink-0 text-[9px] font-bold uppercase ${CLASS_COLOR[s.classification] ?? 'text-text-faint'}`}>
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
                <div className="pb-1 text-[10px] font-bold uppercase tracking-wide text-text-faint">Bench</div>
                <div className="divide-y divide-divider opacity-70">
                  {bench.map((s) => {
                    const live = livePointsById.get(s.player_id)
                    const hasActual = live !== undefined && live.play_state !== 'yet_to_play'
                    const actual = hasActual ? live.points * live.multiplier : null
                    return (
                      <div key={s.player_id} className="flex items-center gap-2.5 py-2 text-sm">
                        <span className="truncate font-bold text-text">{s.web_name}</span>
                        <span className="shrink-0 bg-raised px-1.5 py-0.5 text-[9px] font-bold text-text-muted">{s.position}</span>
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
            <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Bonus &amp; defensive contribution</div>
            {bonusDefcon.some((r) => (r.minutes ?? 0) > 0) ? (
              <>
                <p className="mb-3 text-[11px] text-text-faint">
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
        <div className="border-t-2 border-divider bg-void px-10 py-8">
          <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Threats</div>
          <p className="mb-3 text-[11px] text-text-faint">Template picks you don't own, hauling right now.</p>
          <div className="flex flex-wrap gap-x-10 gap-y-3">
            {p.threats.map((t) => (
              <div key={t.player_id} className="flex items-baseline gap-2">
                <span className="tabular font-display text-2xl font-bold text-alert-red">{t.points}</span>
                <Link to={`/player/${t.player_id}`} className="font-bold text-text hover:text-alert-red">
                  {t.web_name}
                </Link>
                <span className="bg-raised px-1.5 py-0.5 text-[9px] font-bold text-text-muted">{t.position}</span>
                <span className="text-[10px] text-text-faint">{t.ownership_percent.toFixed(1)}% owned</span>
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
        <div className={`grid grid-cols-1 gap-px border-t-2 border-divider bg-divider ${wireCols > 1 ? 'lg:grid-cols-2' : ''}`}>
          {events.length > 0 && (
            <div className="bg-void px-10 py-8">
              <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Squad returns</div>
              <p className="mb-3 text-[11px] text-text-faint">Running totals this gameweek, not a timed feed.</p>
              <div className="divide-y divide-divider">
                {events.map((e, i) => {
                  const kind = RETURN_KIND[e.kind]
                  return (
                    <div key={i} className="flex items-baseline gap-3 py-2.5">
                      <span className={`tabular font-display text-2xl font-bold ${kind?.color ?? 'text-text'}`}>{e.count}</span>
                      <span className={`text-[10px] font-bold uppercase tracking-[0.12em] ${kind?.color ?? 'text-text-faint'}`}>
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
              <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Change wire</div>
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
                        <span className="text-[10px] font-bold uppercase tracking-wide text-text-faint">
                          {c.event_type?.replace(/_/g, ' ') ?? ''}
                        </span>
                      </div>
                      {(c.old_value !== null || c.new_value !== null) && (
                        <div className="text-xs text-text-muted">
                          {c.old_value ?? '—'} &rarr; <span className="text-text">{c.new_value ?? '—'}</span>
                        </div>
                      )}
                    </div>
                    <span className="shrink-0 text-[10px] text-text-faint">{relativeTime(c.detected_at) ?? ''}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* SEASON TRAJECTORY - real rank/points/captain history */}
      {charts && (charts.rank.events.length > 1 || charts.cumulative_points.events.length > 1) && (
        <div className={`grid grid-cols-1 gap-px border-t-2 border-divider bg-divider ${chartCols > 1 ? 'lg:grid-cols-2' : ''}`}>
          {charts.rank.events.length > 1 && (
            <div className="bg-void px-10 py-8">
              <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Overall rank trajectory</div>
              <Chart
                type="area"
                height={260}
                options={baseChart({
                  chart: { type: 'area' },
                  fill: flatAreaFill(),
                  colors: [CHART_COLORS.primary],
                  xaxis: { categories: charts.rank.events.map((e) => `GW${e}`), labels: { style: { cssClass: 'tabular' } } },
                  // Reversed: a lower overall rank is better, so an unreversed
                  // axis would draw a real climb as a fall.
                  yaxis: { reversed: true, labels: rankAxisLabels },
                })}
                series={[{ name: 'Overall rank', data: charts.rank.values }]}
              />
            </div>
          )}
          {charts.cumulative_points.events.length > 1 && (
            <div className="bg-void px-10 py-8">
              <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Cumulative points</div>
              <Chart
                type="area"
                height={260}
                options={baseChart({
                  chart: { type: 'area' },
                  fill: flatAreaFill(),
                  colors: [CHART_COLORS.secondary],
                  xaxis: { categories: charts.cumulative_points.events.map((e) => `GW${e}`), labels: { style: { cssClass: 'tabular' } } },
                  yaxis: { labels: intAxisLabels },
                })}
                series={[{ name: 'Cumulative points', data: charts.cumulative_points.values }]}
              />
            </div>
          )}
          {charts.captain_contribution.events.length > 1 && (
            <div className={`bg-void px-10 py-8 ${chartCols > 1 ? 'lg:col-span-2' : ''}`}>
              <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Captain contribution per GW</div>
              <Chart
                type="bar"
                height={220}
                options={baseChart({
                  chart: { type: 'bar' },
                  colors: [CHART_COLORS.accent],
                  xaxis: { categories: charts.captain_contribution.events.map((e) => `GW${e}`), labels: { style: { cssClass: 'tabular' } } },
                  yaxis: { labels: intAxisLabels },
                })}
                series={[{ name: 'Captain points', data: charts.captain_contribution.values }]}
              />
            </div>
          )}
        </div>
      )}

      {/* SYSTEM HEALTH - real per-source freshness + the real adaptive sync
          cadence this project's own scheduler uses to decide its next tick.
          Never a decorative "system monitor": every value here already
          drives a real backend decision. */}
      {(p.source_freshness.length > 0 || p.cadence) && (
        <div className="border-t-2 border-divider bg-panel px-10 py-8">
          <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">System health</div>
          <div className="grid grid-cols-1 gap-8 md:grid-cols-[1fr_auto]">
            {p.source_freshness.length > 0 && (
              <div className="grid grid-cols-2 gap-x-8 gap-y-2 sm:grid-cols-3">
                {p.source_freshness.map((s) => (
                  <div key={s.source} className="flex items-center gap-2">
                    <span className={`size-1.5 shrink-0 rounded-full ${s.degraded ? 'bg-alert-red' : 'bg-pitch-green'}`} />
                    <span className="truncate text-sm font-semibold text-text">{s.source}</span>
                    <span className="ml-auto shrink-0 text-[10px] text-text-faint">
                      {s.last_success ? new Date(s.last_success).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'never'}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {p.cadence && (
              <div className="border-l-2 border-divider pl-8 text-sm">
                <div className="text-text-muted">
                  Sync every <span className="font-bold text-text">{p.cadence.system.interval_minutes}m</span>
                </div>
                <div className="mt-1 text-xs text-text-faint">{p.cadence.system.reason}</div>
                <div className="mt-3 text-text-muted">
                  Rank refreshes at least every <span className="font-bold text-text">{p.cadence.rank.next_due_floor_minutes}m</span>
                </div>
                <div className="mt-3 font-mono text-[10px] uppercase tracking-wide text-text-faint">
                  Snapshot written {relativeTime(p.generated_at) ?? '—'} · this screen re-reads it every 10s
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
