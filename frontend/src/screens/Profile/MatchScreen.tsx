import { Link, useParams } from 'react-router-dom'
import Chart from 'react-apexcharts'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import { crestUrl, fetchMatchReport } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { CHART_COLORS, baseChart, intAxisLabels } from '@/lib/chartTheme'
import { MomentumBand, type MomentumMarker } from '@/components/football/MomentumBand'
import type { LiveShot, MatchInsight, MatchLineupRow, MatchReview, MatchTimelineRow, MatchTeamStats } from '@/lib/types'

const EVENT_MARK: Record<string, { label: string; ink: string; fill: string }> = {
  Goal: { label: 'Goal', ink: 'text-pitch-green', fill: 'bg-pitch-green' },
  Penalty: { label: 'Penalty', ink: 'text-pitch-green', fill: 'bg-pitch-green' },
  OwnGoal: { label: 'Own goal', ink: 'text-alert-red', fill: 'bg-alert-red' },
  MissedPenalty: { label: 'Penalty missed', ink: 'text-alert-red', fill: 'bg-alert-red' },
  Card: { label: 'Card', ink: 'text-broadcast-gold', fill: 'bg-broadcast-gold' },
  Substitution: { label: 'Substitution', ink: 'text-text-faint', fill: 'bg-text-faint' },
  VAR: { label: 'VAR', ink: 'text-broadcast-blue', fill: 'bg-broadcast-blue' },
}

/** Opposed team stat, on a shared scale. Same grammar as the live match
 * card - the contest is one shape, not two numbers to compare by hand. */
function Opposed({ label, home, away, decimals = 0 }: { label: string; home: number | null; away: number | null; decimals?: number }) {
  if (home === null && away === null) return null
  const h = home ?? 0
  const a = away ?? 0
  const total = h + a
  const homePct = total > 0 ? (h / total) * 100 : 50
  return (
    <div className="grid grid-cols-[3.5rem_1fr_3.5rem] items-center gap-3 py-1.5">
      <span className="tabular text-right text-sm font-bold text-text">{home !== null ? home.toFixed(decimals) : '—'}</span>
      <div>
        <div className="text-center text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">{label}</div>
        <div className="mt-1 flex h-1.5 w-full gap-px">
          <div className="bar-draw bg-pitch-green" style={{ width: `${homePct}%` }} />
          <div className="flex-1 bg-broadcast-blue" />
        </div>
      </div>
      <span className="tabular text-sm font-bold text-text">{away !== null ? away.toFixed(decimals) : '—'}</span>
    </div>
  )
}

/** Real FotMob-authored storylines - already-written editorial one-liners
 * ("Everton have scored 11 goals in their last 5 matches"), never derived
 * or generated here. A real narrative strip, not a stat. */
function Storylines({ insights, home, away }: { insights: MatchInsight[]; home: number; away: number }) {
  if (insights.length === 0) return null
  return (
    <div className="border-b-2 border-divider px-10 py-6">
      <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Storylines</div>
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        {insights.slice(0, 6).map((ins, i) => (
          <div key={i} className="flex items-baseline gap-2 text-sm">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: ins.color ?? 'var(--text-faint)' }}
              aria-hidden="true"
            />
            <span className="text-text-muted">{ins.text}</span>
            {ins.team_id !== null && (
              <span className="text-[10px] font-bold uppercase text-text-faint">
                {ins.team_id === home ? '(home)' : ins.team_id === away ? '(away)' : ''}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Real FotMob editorial article - a genuine published headline/summary/
 * image, read as-is. Turns the report from a stats sheet into an actual
 * piece someone wrote. Never LLM-authored or paraphrased by this project. */
function TheStory({ review }: { review: MatchReview }) {
  return (
    <div className="border-b-2 border-divider">
      <div className="grid grid-cols-1 gap-6 px-10 py-8 md:grid-cols-[1fr_auto]">
        <div className="min-w-0">
          <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">
            {review.kind === 'post' ? 'The story' : 'Match preview'}
          </div>
          <div className="mt-2 font-display text-2xl font-bold leading-tight text-text">{review.title}</div>
          {review.description && <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">{review.description}</p>}
          {review.content_url && (
            <a
              href={review.content_url}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-block text-[11px] font-bold uppercase tracking-wide text-broadcast-blue hover:underline"
            >
              Read the full story &rarr;
            </a>
          )}
        </div>
        {review.image_url && (
          <img src={review.image_url} alt="" className="h-32 w-full shrink-0 object-cover md:h-32 md:w-52" />
        )}
      </div>
    </div>
  )
}

/** The timeline, read down the middle with the minute as the spine and each
 * event sitting on its own team's side - the way a match report is laid out
 * on every football site, and the reason it is instantly readable. */
function TimelineRow({ e }: { e: MatchTimelineRow }) {
  const mark = EVENT_MARK[e.event_type] ?? { label: e.event_type, ink: 'text-text-muted', fill: 'bg-text-faint' }
  const body = (
    <div className={`min-w-0 ${e.is_home ? 'text-right' : 'text-left'}`}>
      <div className={`text-[9px] font-bold uppercase tracking-[0.14em] ${mark.ink}`}>{mark.label}</div>
      <div className="truncate text-sm font-bold text-text">
        {e.player_id !== null ? (
          <Link to={`/player/${e.player_id}`} className="hover:text-pitch-green">{e.player_name ?? '—'}</Link>
        ) : (
          e.player_name ?? '—'
        )}
        {e.is_mine && <span className="ml-1.5 bg-broadcast-gold px-1 text-[8px] font-bold text-broadcast-gold-ink">MINE</span>}
      </div>
      {e.description && <div className="truncate text-[11px] text-text-faint">{e.description}</div>}
    </div>
  )
  return (
    <div className="grid grid-cols-[1fr_3rem_1fr] items-center gap-3 border-b border-divider py-2.5">
      {e.is_home ? body : <div />}
      <div className="flex flex-col items-center gap-1">
        <span className={`size-2 shrink-0 ${mark.fill}`} />
        <span className="tabular text-[11px] font-bold text-text-muted">{e.minute !== null ? `${e.minute}'` : '—'}</span>
      </div>
      {e.is_home ? <div /> : body}
    </div>
  )
}

function LineupTable({ rows, title }: { rows: MatchLineupRow[]; title: string }) {
  const starters = rows.filter((r) => r.started)
  const subs = rows.filter((r) => !r.started)
  const render = (list: MatchLineupRow[]) =>
    list.map((r, i) => (
      <div key={`${r.player_id ?? 'x'}-${i}`} className={`flex items-baseline gap-2 border-b border-divider py-1.5 text-sm ${r.is_mine ? 'bg-panel' : ''}`}>
        <span className="min-w-0 flex-1 truncate font-bold text-text">
          {r.player_id !== null ? (
            <Link to={`/player/${r.player_id}`} className="hover:text-pitch-green">{r.name ?? '—'}</Link>
          ) : (
            r.name ?? '—'
          )}
          {r.is_mine && <span className="ml-1.5 bg-broadcast-gold px-1 text-[8px] font-bold text-broadcast-gold-ink">MINE</span>}
        </span>
        {(r.goals ?? 0) > 0 && <span className="shrink-0 text-xs font-bold text-pitch-green">{r.goals}G</span>}
        {(r.assists ?? 0) > 0 && <span className="shrink-0 text-xs font-bold text-broadcast-gold">{r.assists}A</span>}
        <span className="tabular shrink-0 text-[11px] text-text-faint">
          {r.minutes !== null && r.minutes > 0 ? `${r.minutes}'` : '—'}
        </span>
        {r.rating !== null && (
          <span
            className={`tabular w-8 shrink-0 text-right text-xs font-bold ${
              r.rating >= 7.5 ? 'text-pitch-green' : r.rating < 6.2 ? 'text-alert-red' : 'text-text'
            }`}
          >
            {r.rating.toFixed(1)}
          </span>
        )}
      </div>
    ))
  const anyDetail = rows.some((r) => r.rating !== null || (r.minutes ?? 0) > 0)
  return (
    <div>
      <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">{title}</div>
      {!anyDetail && (
        <p className="mb-3 text-[11px] text-text-faint">
          No per-player minutes or ratings were captured for this match &mdash; the lineup below is real, the detail
          simply was not recorded.
        </p>
      )}
      {render(starters)}
      {subs.length > 0 && (
        <>
          <div className="mb-1 mt-4 text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">Substitutes</div>
          <div className="opacity-70">{render(subs)}</div>
        </>
      )}
    </div>
  )
}

/** THE SHOT QUALITY - two real reads of the same shot list, because they
 * answer different questions. The race line shows the running total, which
 * team accumulated more expected threat overall; the bubble timeline shows
 * exactly when the real chances fell and how big each one was - a 2-0 xG
 * lead built from one huge chance in the 3rd minute reads completely
 * differently from the same total built steadily. Neither invents a value:
 * every point is a real shot already in `p.shots`, just never charted. */
function ShotQuality({ shots, homeTeamId, homeShort, awayShort }: {
  shots: LiveShot[]
  homeTeamId: number
  homeShort: string
  awayShort: string
}) {
  const withMinute = shots.filter((s): s is LiveShot & { minute: number } => s.minute !== null)
  if (withMinute.length === 0) return null
  // Payload orders shots minute DESC (most recent first, for the live feed's
  // own convenience) - reversed here so a cumulative sum runs forward in
  // real time, not backward.
  const chronological = [...withMinute].sort((a, b) => a.minute - b.minute)

  let homeCum = 0
  let awayCum = 0
  const homeSeries: [number, number][] = [[0, 0]]
  const awaySeries: [number, number][] = [[0, 0]]
  for (const s of chronological) {
    if (s.xg === null) continue
    if (s.team_id === homeTeamId) {
      homeCum += s.xg
      homeSeries.push([s.minute, Number(homeCum.toFixed(2))])
    } else {
      awayCum += s.xg
      awaySeries.push([s.minute, Number(awayCum.toFixed(2))])
    }
  }
  const lastMinute = chronological[chronological.length - 1].minute
  homeSeries.push([lastMinute, homeSeries[homeSeries.length - 1][1]])
  awaySeries.push([lastMinute, awaySeries[awaySeries.length - 1][1]])

  const bubbleHome: [number, number, number][] = chronological
    .filter((s) => s.team_id === homeTeamId && s.xg !== null)
    .map((s) => [s.minute, 1, Number((s.xg as number).toFixed(2))])
  const bubbleAway: [number, number, number][] = chronological
    .filter((s) => s.team_id !== homeTeamId && s.xg !== null)
    .map((s) => [s.minute, 0, Number((s.xg as number).toFixed(2))])

  return (
    <div className="border-b-2 border-divider px-10 py-8">
      <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Shot quality</div>
      <div className="mb-4 flex flex-wrap items-center gap-4 text-[11px] text-text-muted">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-pitch-green" /> {homeShort}</span>
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-broadcast-blue" /> {awayShort}</span>
      </div>

      <div className="mb-2 text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">Cumulative xG</div>
      <Chart
        type="line"
        height={220}
        options={baseChart({
          chart: { type: 'line' },
          stroke: { width: 3, curve: 'stepline' },
          colors: [CHART_COLORS.primary, CHART_COLORS.secondary],
          xaxis: { type: 'numeric', title: { text: 'Minute' }, labels: { formatter: (v: string) => `${Math.round(Number(v))}'`, style: { cssClass: 'tabular' } } },
          yaxis: { title: { text: 'xG' }, labels: intAxisLabels, decimalsInFloat: 2 },
          tooltip: { x: { formatter: (v: number) => `${Math.round(v)}'` } },
        })}
        series={[
          { name: homeShort, data: homeSeries },
          { name: awayShort, data: awaySeries },
        ]}
      />

      <div className="mb-2 mt-8 text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">
        Every chance, by minute &middot; bubble size = xG
      </div>
      <Chart
        type="bubble"
        height={140}
        options={baseChart({
          chart: { type: 'bubble' },
          colors: [CHART_COLORS.primary, CHART_COLORS.secondary],
          xaxis: { type: 'numeric', title: { text: 'Minute' }, tickAmount: 6, labels: { formatter: (v: string) => `${Math.round(Number(v))}'`, style: { cssClass: 'tabular' } } },
          yaxis: { show: false, min: -0.5, max: 1.5 },
          tooltip: { y: { formatter: (v: number) => `${v.toFixed(2)} xG` } },
        })}
        series={[
          { name: homeShort, data: bubbleHome },
          { name: awayShort, data: bubbleAway },
        ]}
      />
    </div>
  )
}

function stat(s: MatchTeamStats | null, k: keyof MatchTeamStats): number | null {
  const v = s ? s[k] : null
  return typeof v === 'number' ? v : null
}

export function MatchScreen() {
  const { id } = useParams()
  const state = useFetch(() => fetchMatchReport(Number(id)), [id], 30000)

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="border-b-2 border-divider px-10 py-8">
          <Skel className="mx-auto h-14 w-56" />
        </div>
        <div className="space-y-2 px-10 py-8">
          {[0, 1, 2, 3, 4, 5].map((i) => <Skel key={i} className="h-8 w-full" />)}
        </div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Match report unavailable"
        description="No report could be fetched for this match. If the id does not exist the backend returns a real 404 rather than an empty report."
        message={state.error.message}
      />
    )
  }

  const p = state.data
  const m = p.match
  const homeCrest = crestUrl(m.home.code)
  const awayCrest = crestUrl(m.away.code)
  const hs = p.team_stats.home
  const as = p.team_stats.away
  const live = m.status === 'LIVE' || m.status === 'HALFTIME'

  return (
    <div className="data-in pb-16">
      <Masthead
        edition="Match Report"
        title={`${m.home.short} v ${m.away.short}`}
        right={<span className="text-text-faint">{m.status.replace(/_/g, ' ')}</span>}
      />

      {p.review && <TheStory review={p.review} />}

      {/* THE SCORELINE */}
      <div className="border-b-2 border-divider px-10 py-8">
        <div className="flex items-center justify-center gap-6">
          <Link to={`/club/${m.home.team_id}`} className="flex flex-1 items-center justify-end gap-3 hover:opacity-80">
            <span className="truncate font-display text-2xl font-bold uppercase text-text">{m.home.name}</span>
            {homeCrest && <img src={homeCrest} alt="" className="h-12 w-12 shrink-0" />}
          </Link>
          <div className="shrink-0 text-center">
            <div className="tabular font-display text-6xl font-bold leading-none text-text">
              {m.home.score ?? 0}<span className="mx-2 text-text-faint">-</span>{m.away.score ?? 0}
            </div>
            <div className="mt-2 flex items-center justify-center gap-1.5">
              {live && <span className="size-1.5 animate-pulse-live rounded-full bg-alert-red" />}
              <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">
                {live ? (m.live_minute !== null ? `${m.live_minute}'` : m.status) : 'Full time'}
              </span>
            </div>
          </div>
          <Link to={`/club/${m.away.team_id}`} className="flex flex-1 items-center gap-3 hover:opacity-80">
            {awayCrest && <img src={awayCrest} alt="" className="h-12 w-12 shrink-0" />}
            <span className="truncate font-display text-2xl font-bold uppercase text-text">{m.away.name}</span>
          </Link>
        </div>
        {(hs?.formation || as?.formation) && (
          <div className="mt-4 flex items-center justify-center gap-6 text-[11px] font-bold uppercase tracking-[0.16em] text-text-faint">
            <span>{hs?.formation ?? ''}</span>
            <span className="text-text-faint">formation</span>
            <span>{as?.formation ?? ''}</span>
          </div>
        )}
      </div>

      <Storylines insights={p.insights} home={m.home.team_id} away={m.away.team_id} />

      {/* THE CONTEST */}
      {(hs || as) && (
        <div className="border-b-2 border-divider px-10 py-6">
          <Opposed label="Possession" home={stat(hs, 'possession_pct')} away={stat(as, 'possession_pct')} />
          <Opposed label="xG" home={stat(hs, 'xg')} away={stat(as, 'xg')} decimals={2} />
          <Opposed label="Shots" home={stat(hs, 'shots')} away={stat(as, 'shots')} />
          <Opposed label="On target" home={stat(hs, 'shots_on_target')} away={stat(as, 'shots_on_target')} />
          <Opposed label="Big chances" home={stat(hs, 'big_chances')} away={stat(as, 'big_chances')} />
          <Opposed label="Corners" home={stat(hs, 'corners')} away={stat(as, 'corners')} />
        </div>
      )}

      {/* BATTLE OF THE PITCH - real fields this project fetched every sync
          and never rendered: touches in the box, real pass accuracy (not
          just a count), the physical duel (tackles/interceptions/blocks/
          clearances/duels won), discipline, and - the real sleeper - who
          actually ran further. */}
      {(hs || as) && (
        <div className="border-b-2 border-divider px-10 py-6">
          <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Battle of the pitch</div>
          <Opposed label="Touches in box" home={stat(hs, 'touches_opp_box')} away={stat(as, 'touches_opp_box')} />
          <Opposed label="Accurate passes" home={stat(hs, 'accurate_passes')} away={stat(as, 'accurate_passes')} />
          <Opposed label="Pass accuracy %" home={stat(hs, 'pass_accuracy_pct')} away={stat(as, 'pass_accuracy_pct')} />
          <Opposed label="Tackles" home={stat(hs, 'tackles')} away={stat(as, 'tackles')} />
          <Opposed label="Interceptions" home={stat(hs, 'interceptions')} away={stat(as, 'interceptions')} />
          <Opposed label="Blocks" home={stat(hs, 'blocks')} away={stat(as, 'blocks')} />
          <Opposed label="Clearances" home={stat(hs, 'clearances')} away={stat(as, 'clearances')} />
          <Opposed label="Duels won" home={stat(hs, 'duels_won')} away={stat(as, 'duels_won')} />
          <Opposed label="Yellow cards" home={stat(hs, 'yellow_cards')} away={stat(as, 'yellow_cards')} />
          <Opposed label="Red cards" home={stat(hs, 'red_cards')} away={stat(as, 'red_cards')} />
          <Opposed
            label="Distance covered (km)"
            home={hs?.distance_covered_m !== null && hs?.distance_covered_m !== undefined ? hs.distance_covered_m / 1000 : null}
            away={as?.distance_covered_m !== null && as?.distance_covered_m !== undefined ? as.distance_covered_m / 1000 : null}
            decimals={1}
          />
          <Opposed label="Sprints" home={stat(hs, 'sprints')} away={stat(as, 'sprints')} />
        </div>
      )}

      <ShotQuality shots={p.shots} homeTeamId={m.home.team_id} homeShort={m.home.short} awayShort={m.away.short} />

      {/* MOMENTUM + THE TIMELINE - one shape, not two disconnected panels.
          The band gives the real pressure swing across the whole match at a
          glance; every marker on it is a real timeline event at its real
          minute, not inferred from the pressure shape itself. The detailed
          list below stays for the real player-level detail (who, what) a
          compact band can't carry. */}
      {p.momentum.length > 1 && (
        <div className="border-b-2 border-divider px-10 py-8">
          <MomentumBand
            points={p.momentum}
            maxMinuteOverride={Math.max(...p.momentum.map((pt) => pt.minute), 90)}
            markers={p.timeline
              .filter((e): e is MatchTimelineRow & { minute: number; event_type: MomentumMarker['kind'] } =>
                e.minute !== null && (['Goal', 'Card', 'OwnGoal', 'MissedPenalty', 'Penalty', 'VAR'] as const).includes(e.event_type as never))
              .map((e): MomentumMarker => ({ minute: e.minute, isHome: e.is_home, kind: e.event_type }))}
          />
        </div>
      )}

      {/* THE TIMELINE */}
      {p.timeline.length > 0 && (
        <div className="border-b-2 border-divider px-10 py-8">
          <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Timeline</div>
          {p.timeline.map((e, i) => <TimelineRow key={i} e={e} />)}
        </div>
      )}

      {/* BOTH TEAMS - the live screen only ever showed my own players. */}
      {(p.lineups.home.length > 0 || p.lineups.away.length > 0) && (
        <div className="grid grid-cols-1 gap-px bg-divider lg:grid-cols-2">
          <div className="bg-void px-10 py-8">
            <LineupTable rows={p.lineups.home} title={`${m.home.name} · ratings`} />
          </div>
          <div className="bg-void px-10 py-8">
            <LineupTable rows={p.lineups.away} title={`${m.away.name} · ratings`} />
          </div>
        </div>
      )}
    </div>
  )
}
