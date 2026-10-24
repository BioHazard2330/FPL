import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { SignalLedger } from '@/components/football/SignalLedger'
import { Masthead } from '@/components/shell/Masthead'
import { Disclosure, Panel } from '@/components/ui/kit'
import { crestUrl, fetchFootballPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { ScreenError } from '@/components/shell/ScreenStates'
import { relativeTime } from '@/lib/time'
import { NextFixture } from '@/components/football/FixtureRun'
import { AwayDaysMap, type TravelLeg } from '@/components/football/AwayDaysMap'
import type { ChangeFeedRow, FixtureContext, FixtureTickerRow, FootballSignal, TeamStateRow } from '@/lib/types'
import { plain } from '@/lib/text'

// Real FPL 1-5 FDR scale (fixture_ticker's own `difficulty` field) - the
// same broadcast-ticker color convention every FPL tool uses: 1-2 easy
// (green), 3 neutral (muted), 4-5 hard (red/gold).
const FDR_COLOR: Record<number, string> = {
  1: 'bg-pitch-green text-pitch-green-ink', 2: 'bg-pitch-green/70 text-pitch-green-ink',
  3: 'bg-raised text-text-muted', 4: 'bg-alert-red/70 text-alert-red-ink', 5: 'bg-alert-red text-alert-red-ink',
}

/** Real, squad-scoped FDR ticker, promoted to the broadcast strip that
 * opens the desk. One row per squad team, one flat colour cell per real
 * upcoming fixture - fixture-ticker convention, never a table.
 *
 * Rows are ordered by schedule pressure: the mean of the REAL `difficulty`
 * values already drawn in that row's own cells, nothing else. That is
 * arithmetic over what the reader can see, not a new model output - the
 * easiest run sits at the top because "who has the kind run" is the actual
 * question a fixture ticker exists to answer, and an alphabetical/ID order
 * buries it. Teams whose fixture list is empty keep their place rather than
 * being scored against a fabricated average. */
function FixtureTicker({ rows }: { rows: FixtureTickerRow[] }) {
  if (rows.length === 0) return null
  const pressure = (r: FixtureTickerRow): number | null =>
    r.fixtures.length === 0 ? null : r.fixtures.reduce((a, f) => a + f.difficulty, 0) / r.fixtures.length
  const ordered = rows
    .slice()
    .sort((a, b) => (pressure(a) ?? 99) - (pressure(b) ?? 99))
  const width = Math.max(...rows.map((r) => r.fixtures.length), 1)

  return (
    <div className="border-b border-divider py-6">
      <div className="mb-4 flex flex-wrap items-baseline gap-3 px-10">
        <span className="text-[13px] font-bold text-text-faint">Fixture ticker</span>
        <span className="text-[13px] text-text-faint">my clubs &middot; easiest run first &middot; next {width} gameweeks</span>
      </div>
      <div>
        {ordered.map((r) => {
          const crest = crestUrl(r.team_code)
          const p = pressure(r)
          return (
            <div key={r.team_id} className="flex items-stretch gap-4 border-t border-divider px-10 py-1.5 first:border-t-0">
              <div className="flex w-28 shrink-0 items-center gap-2">
                {crest && <img src={crest} alt="" className="h-6 w-6" />}
                <span className="font-display text-base font-bold text-text">{r.team_short}</span>
              </div>
              <div className="flex gap-1.5">
                {r.fixtures.map((f) => (
                  <div
                    key={f.event}
                    className={`flex w-[4.5rem] flex-col items-center justify-center gap-0.5 px-1 py-1.5 ${FDR_COLOR[f.difficulty] ?? 'bg-raised text-text-muted'}`}
                  >
                    <span className="text-[12px] font-bold opacity-80">GW{f.event}</span>
                    <span className="text-xs font-bold">
                      {f.opponent_short} {f.is_home ? '(H)' : '(A)'}
                    </span>
                  </div>
                ))}
              </div>
              {p !== null && (
                <div className="ml-auto flex shrink-0 items-baseline gap-2 self-center">
                  <span className="text-[12px] font-bold text-text-faint">Avg FDR</span>
                  <span
                    className={`tabular font-display text-xl font-bold ${
 p <= 2.4 ? 'text-pitch-green' : p >= 3.6 ? 'text-alert-red' : 'text-text-muted'
 }`}
                  >
                    {p.toFixed(1)}
                  </span>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const FEED_CATEGORY_COLOR: Record<string, string> = {
  MANAGER: 'text-broadcast-blue', XI: 'text-broadcast-gold', AVAILABILITY: 'text-alert-red',
}
const FEED_DOT_COLOR: Record<string, string> = {
  good: 'bg-pitch-green', bad: 'bg-alert-red', neutral: 'bg-text-faint',
}

/** Real MANAGER/XI/AVAILABILITY wire (art-direction pass v3) - the same real
 * `change_events` table already driving squad-churn detection league-wide,
 * now a real newsroom ticker instead of an unexposed HTML-only panel. */
function ChangeFeedRail({ rows }: { rows: ChangeFeedRow[] }) {
  if (rows.length === 0) return null
  return (
    <div className="flex flex-col divide-y divide-divider">
      {rows.map((r, i) => {
        const crest = crestUrl(r.team_code)
        return (
          <div key={i} className="flex items-start gap-2 py-2.5 text-xs">
            <span className={`mt-1 size-1.5 shrink-0 rounded-full ${FEED_DOT_COLOR[r.dot]}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                {crest && <img src={crest} alt="" className="h-3.5 w-3.5 shrink-0 rounded-full" />}
                <span className={`font-bold ${FEED_CATEGORY_COLOR[r.category] ?? 'text-text-faint'}`}>{r.category}</span>
                {r.is_mine && <span className="shrink-0 rounded bg-broadcast-gold/20 px-1.5 text-[12px] font-semibold leading-5 text-broadcast-gold">yours</span>}
              </div>
              <div className="mt-0.5 text-text">
                <span className="font-semibold">{r.entity_name}</span>
                {r.old_label !== null && r.new_label !== null && (
                  <span className="text-text-muted"> {r.old_label} &rarr; {r.new_label}</span>
                )}
              </div>
            </div>
            <span className="shrink-0 text-[12px] text-text-faint">{relativeTime(r.detected_at)}</span>
          </div>
        )
      })}
    </div>
  )
}

const DIRECTION_COLOR: Record<string, string> = {
  POSITIVE: 'text-pitch-green', NEGATIVE: 'text-alert-red', WATCH: 'text-broadcast-gold', NEUTRAL: 'text-text-muted',
}

const CATEGORY_ACCENT: Record<string, string> = {
  SET_PIECE_CHANGE: 'border-broadcast-blue', SET_PIECES: 'border-broadcast-blue', TACTICAL_CHANGE: 'border-broadcast-blue',
  CREATION: 'border-broadcast-gold', GOAL_THREAT: 'border-pitch-green', ROLE_CHANGE: 'border-alert-red', MINUTES: 'border-text-faint',
}

const TIMELINE_CATEGORIES = ['SET_PIECE_CHANGE', 'SET_PIECES', 'TACTICAL_CHANGE']

/** Real per-category presentation, not one template stamped four times
 * (art-direction pass, 2026-09-08 v2, spec's own worked example: goal-threat
 * vs set-piece vs role-change should not look alike). GOAL_THREAT/CREATION
 * run large and editorial; a change-of-state signal (set-piece/tactical)
 * reads as a compact timeline entry instead; everything else takes the
 * standard featured size. Same real fields throughout, only the frame differs. */
/** One player, one card. The same match produced three or four signals for the
 * same footballer (goal threat, creation, role change, minutes) and each used
 * to take a card of its own, so a screen of eight signals was really three
 * players said eight ways. The strongest signal leads; the rest sit under it
 * as single lines. */
function groupByPlayer(signals: FootballSignal[]): FootballSignal[][] {
  const groups = new Map<number, FootballSignal[]>()
  for (const sig of signals) {
    const g = groups.get(sig.entity_id)
    if (g) g.push(sig)
    else groups.set(sig.entity_id, [sig])
  }
  return [...groups.values()]
}

const signalKey = (sig: FootballSignal) => `${sig.entity_id}|${sig.evidence}`

function FeaturedSignalCard({ s, large = false, extra = [] }: { s: FootballSignal; large?: boolean; extra?: FootballSignal[] }) {
  const crest = crestUrl(s.team_code)
  const isTimeline = TIMELINE_CATEGORIES.includes(s.category)

  if (isTimeline) {
    return (
      <div className="flex min-w-[260px] max-w-[300px] items-start gap-3 border-l border-broadcast-blue bg-void px-5 py-4">
        <span className="mt-1 size-2 shrink-0 rounded-full bg-broadcast-blue" />
        <div>
          <div className="flex items-center gap-2 text-[12px] font-bold text-broadcast-blue">
            {crest && <img src={crest} alt="" className="h-3.5 w-3.5 rounded-full" />}
            {s.category.replace(/_/g, ' ')}
          </div>
          <div className="mt-1 font-display text-lg font-bold text-text">{s.entity_name}</div>
          <p className="mt-1 text-xs leading-relaxed text-text-muted">{plain(s.evidence)}</p>
          {s.fpl_effect && <div className={`mt-2 text-xs font-bold ${DIRECTION_COLOR[s.direction] ?? 'text-text'}`}>{s.fpl_effect}</div>}
        </div>
      </div>
    )
  }

  return (
    <div
      className={`min-w-[300px] flex-1 border-l-4 bg-panel px-6 py-5 ${CATEGORY_ACCENT[s.category] ?? 'border-text-faint'} ${large ? 'basis-full py-7' : ''}`}
    >
      <div className="flex items-center gap-2">
        {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
        <span className="text-[12px] font-bold text-text-faint">{s.category.replace(/_/g, ' ')}</span>
      </div>
      <div className={`mt-1.5 font-display font-bold text-text ${large ? 'text-4xl' : 'text-2xl'}`}>{s.entity_name}</div>
      <p className={`mt-2 leading-relaxed text-text-muted ${large ? 'max-w-2xl text-base' : 'text-sm'}`}>{plain(s.evidence)}</p>
      {s.interpretation && <p className="mt-1 text-sm italic text-text-faint">{s.interpretation}</p>}
      {s.fpl_effect && <div className={`mt-3 font-bold ${DIRECTION_COLOR[s.direction] ?? 'text-text'} ${large ? 'text-lg' : 'text-sm'}`}>{s.fpl_effect}</div>}
      {extra.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-divider pt-2 text-xs text-text-faint">
          {extra.map((e) => (
            <li key={signalKey(e)}>
              <span className="mr-2 font-bold">{e.category.replace(/_/g, ' ')}</span>
              {plain(e.evidence)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Real signal-type variety inside the board itself, not just the top-4
 * featured cards (art-direction pass v3, direct user follow-up: "more
 * football, less AI slop"). A set-piece/tactical change is a discrete,
 * dated event - reads as a timeline tick (dot + rule), never the same
 * baseline-vs-now prose row a persistent goal-threat/creation trend gets. */
function SignalRow({ s }: { s: FootballSignal }) {
  const crest = crestUrl(s.team_code)
  const isTimeline = TIMELINE_CATEGORIES.includes(s.category)
  if (isTimeline) {
    return (
      <div className="flex items-baseline gap-2.5 border-b border-divider py-2.5 text-sm last:border-b-0">
        <span className="size-1.5 shrink-0 rounded-full bg-broadcast-blue" />
        {crest && <img src={crest} alt="" className="h-4 w-4 shrink-0 rounded-full" />}
        <span className="font-bold text-text">{s.entity_name}</span>
        {s.is_mine && <span className="shrink-0 rounded bg-broadcast-gold/20 px-1.5 text-[12px] font-semibold leading-5 text-broadcast-gold">yours</span>}
        <span className="text-broadcast-blue">{plain(s.evidence)}</span>
        <span className="ml-auto shrink-0 text-[12px] font-bold text-text-faint">{s.confidence}</span>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-baseline gap-2 border-b border-divider py-2.5 text-sm last:border-b-0">
      {crest && <img src={crest} alt="" className="h-4 w-4 shrink-0 rounded-full" />}
      <span className="font-bold text-text">{s.entity_name}</span>
      {s.is_mine && <span className="shrink-0 rounded bg-broadcast-gold/20 px-1.5 text-[12px] font-semibold leading-5 text-broadcast-gold">yours</span>}
      <span className="text-text-muted">{plain(s.evidence)}</span>
      {s.interpretation && <span className="italic text-text-faint">{s.interpretation}</span>}
      {s.fpl_effect && <span className={`font-semibold ${DIRECTION_COLOR[s.direction] ?? 'text-text'}`}>{s.fpl_effect}</span>}
      <span className="ml-auto shrink-0 text-[12px] font-bold text-text-faint">{s.confidence}</span>
    </div>
  )
}

/** Real attack-vs-defence team grid, replacing a table sat inside a
 * bordered card. Each club gets one row where xG and xGA are drawn as
 * OPPOSED bars off a shared centre line, both scaled to the same real
 * league-wide max - so "creates a lot but leaks a lot" is a shape you read
 * at a glance rather than two numbers you have to compare by hand. A club
 * with no real attack or defence row renders that side empty; nothing is
 * substituted. Squad clubs are marked, never re-ordered away from the real
 * ranking (which is by attack, the direction FPL points come from). */
function TeamStateGrid({ rows, fixtures }: { rows: TeamStateRow[]; fixtures?: FixtureContext }) {
  const xgMax = Math.max(...rows.map((t) => t.attack?.xg ?? 0), 0.01)
  const xgaMax = Math.max(...rows.map((t) => t.defence?.xga ?? 0), 0.01)
  const ordered = rows.slice().sort((a, b) => (b.attack?.xg ?? -1) - (a.attack?.xg ?? -1))

  return (
    <div>
      <div className="flex items-center gap-4 border-b border-divider px-10 pb-2">
        <span className="w-40 shrink-0" />
        <span className="w-20 shrink-0 text-[12px] font-bold text-text-faint">Next</span>
        <span className="flex-1 text-right text-[12px] font-bold text-alert-red">xGA conceded</span>
        <span className="w-px" />
        <span className="flex-1 text-[12px] font-bold text-pitch-green">xG created</span>
        <span className="hidden w-[26rem] shrink-0 text-[12px] font-bold text-text-faint xl:block">
          Shape &amp; FPL implication
        </span>
      </div>
      {ordered.map((t) => {
        const crest = crestUrl(t.team_code)
        const xg = t.attack?.xg ?? null
        const xga = t.defence?.xga ?? null
        return (
          <div
            key={t.team_id}
            className={`flex items-center gap-4 border-b border-divider px-10 py-2 ${t.in_squad ? 'bg-panel' : ''}`}
          >
            <div className="flex w-40 shrink-0 items-center gap-2">
              {crest && <img src={crest} alt="" className="h-5 w-5" />}
              <Link
                to={`/club/${t.team_id}`}
                className="truncate font-display text-sm font-bold text-text hover:text-pitch-green"
              >
                {t.team_name}
              </Link>
              {t.in_squad && <span className="shrink-0 rounded bg-broadcast-gold/20 px-1.5 text-[12px] font-semibold leading-5 text-broadcast-gold">yours</span>}
            </div>
            {/* Who they actually play next, beside how good they are - the
                two halves of the same football question. */}
            <div className="w-20 shrink-0">
              <NextFixture fixtures={fixtures?.[String(t.team_code)]} />
            </div>

            <div className="flex flex-1 items-center justify-end gap-2">
              <span className="tabular text-xs text-text-muted">{xga !== null ? xga.toFixed(2) : '—'}</span>
              <span className="h-3 flex-1 bg-void">
                <span className="bar-draw-right ml-auto block h-full bg-alert-red" style={{ width: `${xga !== null ? (xga / xgaMax) * 100 : 0}%`, marginLeft: 'auto' }} />
              </span>
            </div>
            <span className="w-px self-stretch bg-divider" />
            <div className="flex flex-1 items-center gap-2">
              <span className="h-3 flex-1 bg-void">
                <span className="bar-draw block h-full bg-pitch-green" style={{ width: `${xg !== null ? (xg / xgMax) * 100 : 0}%` }} />
              </span>
              <span className="tabular text-xs text-text-muted">{xg !== null ? xg.toFixed(2) : '—'}</span>
            </div>

            <div className="hidden w-[26rem] shrink-0 text-[13px] leading-snug xl:block">
              {(t.formation || t.tactical) && (
                <span className="text-text-faint">{[t.formation, t.tactical].filter(Boolean).join(' · ')} </span>
              )}
              {t.fpl_implication && <span className="text-text-muted">{t.fpl_implication}</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Skeleton shaped like the broadcast desk it precedes - headline count,
 * fixture-ticker rows, then the featured/wire split - so the page does not
 * visibly re-flow into a different layout once the real scan lands. The
 * cold-cache warning stays: this payload is a genuine league-wide scan. */
function FootballSkeleton() {
  return (
    <div className="animate-pulse pb-16">
      <div className="border-b border-divider px-10 py-3"><div className="h-3 w-64 bg-raised" /></div>
      <div className="px-10 pb-6 pt-7">
        <div className="h-2 w-40 bg-raised" />
        <div className="mt-2 h-9 w-56 bg-raised" />
        <div className="mt-3 text-[13px] text-text-faint">
          Loading football intelligence &mdash; a league-wide scan, can take up to 30s on a cold cache
        </div>
      </div>
      <div className="border-y border-divider py-6">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex items-center gap-4 border-t border-divider px-10 py-2 first:border-t-0">
            <div className="h-6 w-28 shrink-0 bg-raised" />
            <div className="flex gap-1.5">
              {[0, 1, 2, 3, 4].map((j) => <div key={j} className="h-9 w-[4.5rem] bg-raised" />)}
            </div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-8 px-10 py-6 lg:grid-cols-[7fr_3fr]">
        <div className="space-y-3">
          <div className="h-24 w-full bg-raised" />
          <div className="flex gap-4">
            {[0, 1, 2].map((i) => <div key={i} className="h-24 flex-1 bg-raised" />)}
          </div>
        </div>
        <div className="space-y-2">
          {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-8 w-full bg-raised" />)}
        </div>
      </div>
    </div>
  )
}

export function FootballScreen() {
  const state = useFetch(fetchFootballPayload, [], 60000)
  // Real fix for a real bug found live: this array used to be rebuilt
  // inline on every render (a fresh identity every 60s poll tick even when
  // the underlying fixtures hadn't changed), which made AwayDaysMap's own
  // `useEffect([legs])` tear down and rebuild the whole Leaflet map on
  // every poll - confirmed live to leave a stale, un-cleaned-up tint div
  // behind, doubling the real darkening opacity. Memoized on the real
  // fixture ticker data itself, not on `state` (a new object every poll
  // regardless).
  const ticker = state.status === 'ready' ? state.data.fixture_ticker : null
  const travelLegs = useMemo<TravelLeg[]>(() => {
    if (!ticker) return []
    return ticker.flatMap((r: FixtureTickerRow) =>
      r.fixtures
        .filter((f) => !f.is_home && r.team_code !== null && f.opponent_code !== null)
        .map((f) => ({
          fromTeamCode: r.team_code as number, toTeamCode: f.opponent_code as number,
          fromShort: r.team_short, toShort: f.opponent_short, event: f.event,
        })),
    )
  }, [ticker])

  if (state.status === 'loading') return <FootballSkeleton />
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Football wire unavailable"
        description="The league-wide intelligence scan could not be fetched. No fixture ticker, change wire or team state is being shown from cache — an empty desk here means unknown, not quiet."
        message={state.error.message}
      />
    )
  }

  const p = state.data
  const featuredGroups = groupByPlayer(p.squad_changes)
  const myWire = p.change_feed.filter((r) => r.is_mine)

  return (
    <div className="data-in pb-16">
      <Masthead right={p.squad_signal_count > 0 ? `${p.squad_signal_count} signals touch your squad` : undefined} />

      <FixtureTicker rows={p.fixture_ticker} />

      {/* AWAY DAYS - every real upcoming away fixture for the squad's
          clubs, on an actual map of England. Real stadium coordinates,
          real fixtures - never a simulated route. `travelLegs` is
          memoized above (see its own comment) so the map doesn't tear
          down and rebuild on every 60s poll tick. */}
      {travelLegs.length > 0 && (
        <Disclosure title="Away days" summary={`${travelLegs.length} away trips coming up for your clubs`}>
          <div className="mx-auto h-[30rem] w-full max-w-md overflow-hidden rounded-lg border border-divider">
            <AwayDaysMap legs={travelLegs} />
          </div>
        </Disclosure>
      )}

      {/* FEATURED SQUAD SIGNALS + CHANGE WIRE - a real 70/30 asymmetric split
          (art-direction pass v3): the editorial cards carry the page, a
          narrow MANAGER/XI/AVAILABILITY newsroom ticker runs alongside,
          never a fourth equal-width card. */}
      {(p.squad_changes.length > 0 || myWire.length > 0) && (
        <Panel title="What changed for your players" sub="This gameweek's matches and status changes, for players you own.">
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-[7fr_3fr]">
            <div>
              {p.squad_changes.length > 0 && (
                <>
                  <div className="flex flex-wrap gap-4">
                    {featuredGroups.slice(0, 3).map((g, i) => (
                      <FeaturedSignalCard key={g[0].entity_id} s={g[0]} large={i === 0} extra={g.slice(1, 3)} />
                    ))}
                  </div>
                  {featuredGroups.length > 3 && (
                    <div className="mt-4 divide-y divide-divider">
                      {featuredGroups.slice(3, 8).map((g) => <SignalRow key={g[0].entity_id} s={g[0]} />)}
                    </div>
                  )}
                </>
              )}
            </div>
            {myWire.length > 0 && (
              <div className="border-t border-divider pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
                <div className="mb-1 text-[13px] font-medium text-text-faint">Status changes</div>
                <ChangeFeedRail rows={myWire} />
              </div>
            )}
          </div>
        </Panel>
      )}

      {p.team_state.length > 0 && (
        <Panel title="How your clubs are playing" sub="Chances created and conceded over their recent matches, on one shared scale.">
          <TeamStateGrid rows={p.team_state} fixtures={p.fixtures} />
        </Panel>
      )}

      <Disclosure title="Do these signals carry?" summary="How well last match's numbers predict the next one, measured on every stored season">
        <SignalLedger />
      </Disclosure>

      {/* TEAM ODDS - real next-fixture clean-sheet ranking, bar composition not a table */}
      {p.team_odds.length > 0 && (
        <Panel title="Clean sheets, next fixture" sub="The model's chance each club keeps one, and the goals it expects them to score.">
          <div className="grid grid-cols-1 gap-x-10 gap-y-1 md:grid-cols-2">
            {p.team_odds.map((t) => {
              const crest = crestUrl(t.team_code)
              return (
                <div key={t.team_id} className="flex items-center gap-3 py-2">
                  {crest && <img src={crest} alt="" className="h-5 w-5 shrink-0 rounded-full" />}
                  <Link to={`/club/${t.team_id}`} className="w-12 shrink-0 font-bold text-text hover:text-pitch-green">
                    {t.team_short}
                  </Link>
                  <span className="w-24 shrink-0 text-[13px] text-text-faint">vs {t.opponent_short} {t.is_home ? '(H)' : '(A)'}</span>
                  <span className="relative h-4 flex-1 border border-divider bg-void">
                    <span className="bar-draw absolute inset-y-0 left-0 bg-pitch-green" style={{ width: `${t.clean_sheet_pct}%` }} />
                  </span>
                  <span className="tabular w-12 shrink-0 text-right text-sm font-bold text-pitch-green">{t.clean_sheet_pct.toFixed(0)}%</span>
                  <span className="tabular w-14 shrink-0 text-right text-xs text-text-faint">{t.projected_goals.toFixed(1)} gf</span>
                </div>
              )
            })}
          </div>
        </Panel>
      )}
    </div>
  )
}
