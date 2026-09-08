import type { CSSProperties } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { Masthead } from '@/components/shell/Masthead'
import { crestUrl, fetchFootballPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { relativeTime } from '@/lib/time'
import type { ChangeFeedRow, FixtureTickerRow, FootballSignal } from '@/lib/types'

// Real FPL 1-5 FDR scale (fixture_ticker's own `difficulty` field) - the
// same broadcast-ticker color convention every FPL tool uses: 1-2 easy
// (green), 3 neutral (muted), 4-5 hard (red/gold).
const FDR_COLOR: Record<number, string> = {
  1: 'bg-pitch-green text-pitch-green-ink', 2: 'bg-pitch-green/70 text-pitch-green-ink',
  3: 'bg-raised text-text-muted', 4: 'bg-alert-red/70 text-alert-red-ink', 5: 'bg-alert-red text-alert-red-ink',
}

/** Real, squad-scoped FDR ticker (art-direction pass v3, direct user
 * follow-up: "more football" - the payload previously had no real fixture
 * data at all beyond next-GW Team Odds). One row per squad team, one flat
 * color cell per upcoming real fixture - broadcast fixture-ticker
 * convention, not a table. */
function FixtureTicker({ rows }: { rows: FixtureTickerRow[] }) {
  if (rows.length === 0) return null
  return (
    <div className="border-b-2 border-divider px-10 py-6">
      <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Fixture ticker</div>
      <div className="space-y-2">
        {rows.map((r) => {
          const crest = crestUrl(r.team_code)
          return (
            <div key={r.team_id} className="flex items-center gap-4">
              <div className="flex w-24 shrink-0 items-center gap-2">
                {crest && <img src={crest} alt="" className="h-5 w-5 rounded-full" />}
                <span className="text-sm font-bold text-text">{r.team_short}</span>
              </div>
              <div className="flex gap-1.5">
                {r.fixtures.map((f) => (
                  <div
                    key={f.event}
                    className={`flex w-16 flex-col items-center justify-center gap-0.5 px-1 py-1.5 ${FDR_COLOR[f.difficulty] ?? 'bg-raised text-text-muted'}`}
                  >
                    <span className="text-[9px] font-bold uppercase opacity-80">GW{f.event}</span>
                    <span className="text-xs font-bold">
                      {f.opponent_short} {f.is_home ? '(H)' : '(A)'}
                    </span>
                  </div>
                ))}
              </div>
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
                <span className={`font-bold uppercase tracking-wide ${FEED_CATEGORY_COLOR[r.category] ?? 'text-text-faint'}`}>{r.category}</span>
                {r.is_mine && <span className="bg-broadcast-gold px-1 py-0.5 text-[8px] font-bold text-broadcast-gold-ink">MY SQUAD</span>}
              </div>
              <div className="mt-0.5 text-text">
                <span className="font-semibold">{r.entity_name}</span>
                {r.old_label !== null && r.new_label !== null && (
                  <span className="text-text-muted"> {r.old_label} &rarr; {r.new_label}</span>
                )}
              </div>
            </div>
            <span className="shrink-0 text-[10px] text-text-faint">{relativeTime(r.detected_at)}</span>
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
const LEFT_BOARD_CATEGORIES = ['SET_PIECE_CHANGE', 'SET_PIECES', 'TACTICAL_CHANGE', 'CREATION']

const TIMELINE_CATEGORIES = ['SET_PIECE_CHANGE', 'SET_PIECES', 'TACTICAL_CHANGE']

/** Real per-category presentation, not one template stamped four times
 * (art-direction pass, 2026-09-08 v2, spec's own worked example: goal-threat
 * vs set-piece vs role-change should not look alike). GOAL_THREAT/CREATION
 * run large and editorial; a change-of-state signal (set-piece/tactical)
 * reads as a compact timeline entry instead; everything else takes the
 * standard featured size. Same real fields throughout, only the frame differs. */
function FeaturedSignalCard({ s, large = false }: { s: FootballSignal; large?: boolean }) {
  const crest = crestUrl(s.team_code)
  const isTimeline = TIMELINE_CATEGORIES.includes(s.category)

  if (isTimeline) {
    return (
      <div className="flex min-w-[260px] max-w-[300px] items-start gap-3 border-l-2 border-broadcast-blue bg-void px-5 py-4">
        <span className="mt-1 size-2 shrink-0 rounded-full bg-broadcast-blue" />
        <div>
          <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wide text-broadcast-blue">
            {crest && <img src={crest} alt="" className="h-3.5 w-3.5 rounded-full" />}
            {s.category.replace(/_/g, ' ')}
          </div>
          <div className="mt-1 font-display text-lg font-bold text-text">{s.entity_name}</div>
          <p className="mt-1 text-xs leading-relaxed text-text-muted">{s.evidence}</p>
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
        <span className="text-[10px] font-bold uppercase tracking-wide text-text-faint">{s.category.replace(/_/g, ' ')}</span>
      </div>
      <div className={`mt-1.5 font-display font-bold text-text ${large ? 'text-4xl' : 'text-2xl'}`}>{s.entity_name}</div>
      <p className={`mt-2 leading-relaxed text-text-muted ${large ? 'max-w-2xl text-base' : 'text-sm'}`}>{s.evidence}</p>
      {s.interpretation && <p className="mt-1 text-sm italic text-text-faint">{s.interpretation}</p>}
      {s.fpl_effect && <div className={`mt-3 font-bold ${DIRECTION_COLOR[s.direction] ?? 'text-text'} ${large ? 'text-lg' : 'text-sm'}`}>{s.fpl_effect}</div>}
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
      <div className="flex items-baseline gap-2.5 border-b-2 border-divider py-2.5 text-sm last:border-b-0">
        <span className="size-1.5 shrink-0 rounded-full bg-broadcast-blue" />
        {crest && <img src={crest} alt="" className="h-4 w-4 shrink-0 rounded-full" />}
        <span className="font-bold text-text">{s.entity_name}</span>
        {s.is_mine && <span className="bg-broadcast-gold px-1.5 py-0.5 text-[9px] font-bold text-broadcast-gold-ink">MY SQUAD</span>}
        <span className="text-broadcast-blue">{s.evidence}</span>
        <span className="ml-auto shrink-0 text-[10px] font-bold uppercase tracking-wide text-text-faint">{s.confidence}</span>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-baseline gap-2 border-b-2 border-divider py-2.5 text-sm last:border-b-0">
      {crest && <img src={crest} alt="" className="h-4 w-4 shrink-0 rounded-full" />}
      <span className="font-bold text-text">{s.entity_name}</span>
      {s.is_mine && <span className="bg-broadcast-gold px-1.5 py-0.5 text-[9px] font-bold text-broadcast-gold-ink">MY SQUAD</span>}
      <span className="text-text-muted">{s.evidence}</span>
      {s.interpretation && <span className="italic text-text-faint">{s.interpretation}</span>}
      {s.fpl_effect && <span className={`font-semibold ${DIRECTION_COLOR[s.direction] ?? 'text-text'}`}>{s.fpl_effect}</span>}
      <span className="ml-auto shrink-0 text-[10px] font-bold uppercase tracking-wide text-text-faint">{s.confidence}</span>
    </div>
  )
}

/** Real heat-map cell background - color intensity scaled to the real xG/
 * xGA value already in the payload, never a new computation (Phase 9 v2
 * follow-up, `FPL_TEMPLATE_LINEAGE.md`'s own disclosed FOOTBALL item).
 * `good` means a higher raw value is the GOOD direction (attack xG); false
 * means higher is BAD (defence xGA) - the color hue flips accordingly. */
function heatStyle(value: number | null, min: number, max: number, good: boolean): CSSProperties {
  if (value === null || max === min) return {}
  const t = Math.max(0, Math.min(1, (value - min) / (max - min)))
  const color = good ? 'var(--pitch-green)' : 'var(--alert-red)'
  return { backgroundColor: `color-mix(in srgb, ${color} ${Math.round(t * 35)}%, transparent)` }
}

export function FootballScreen() {
  const state = useFetch(fetchFootballPayload, [], 60000)

  if (state.status === 'loading') {
    return (
      <div className="space-y-3 p-10">
        <div className="font-mono text-[11px] uppercase tracking-[0.15em] text-text-faint">
          Loading football intelligence &mdash; a league-wide scan, can take up to 30s on a cold cache
        </div>
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (state.status === 'error') {
    return <div className="bg-alert-red p-6 font-semibold text-alert-red-ink">Can't reach the backend ({state.error.message}).</div>
  }

  const p = state.data
  const xgValues = p.team_state.map((t) => t.attack?.xg).filter((v): v is number => v !== null && v !== undefined)
  const xgaValues = p.team_state.map((t) => t.defence?.xga).filter((v): v is number => v !== null && v !== undefined)
  const xgMin = xgValues.length ? Math.min(...xgValues) : 0
  const xgMax = xgValues.length ? Math.max(...xgValues) : 1
  const xgaMin = xgaValues.length ? Math.min(...xgaValues) : 0
  const xgaMax = xgaValues.length ? Math.max(...xgaValues) : 1

  const leftBoard = p.categories.filter((c) => LEFT_BOARD_CATEGORIES.includes(c.category))
  const rightBoard = p.categories.filter((c) => !LEFT_BOARD_CATEGORIES.includes(c.category))

  return (
    <div className="pb-16">
      <Masthead edition="Match Intelligence Wire" title="Football" />

      <div className="relative overflow-hidden px-10 pb-6 pt-7">
        <span className="ghost-watermark pointer-events-none absolute -top-10 right-2 select-none font-display text-[11rem] font-bold uppercase leading-none">
          MATCH
        </span>
        <div className="relative font-mono text-[11px] uppercase tracking-[0.15em] text-text-faint">Football intelligence</div>
        <div className="relative mt-1 flex flex-wrap items-baseline gap-x-3">
          <span className="tabular font-display text-4xl font-bold text-text">{p.signal_count}</span>
          <span className="text-sm text-text-faint">signals tracked</span>
          {p.squad_signal_count > 0 && (
            <span className="tabular ml-4 font-display text-2xl font-bold text-broadcast-gold">{p.squad_signal_count}</span>
          )}
          {p.squad_signal_count > 0 && <span className="text-sm text-text-faint">affect your squad</span>}
        </div>
      </div>

      <FixtureTicker rows={p.fixture_ticker} />

      {/* FEATURED SQUAD SIGNALS + CHANGE WIRE - a real 70/30 asymmetric split
          (art-direction pass v3): the editorial cards carry the page, a
          narrow MANAGER/XI/AVAILABILITY newsroom ticker runs alongside,
          never a fourth equal-width card. */}
      {(p.squad_changes.length > 0 || p.change_feed.length > 0) && (
        <div className="mt-6 grid grid-cols-1 gap-8 border-y-2 border-divider px-10 py-6 lg:grid-cols-[7fr_3fr]">
          <div>
            {p.squad_changes.length > 0 && (
              <>
                <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Featured squad signals</div>
                <div className="flex flex-wrap gap-4">
                  {p.squad_changes.slice(0, 4).map((s, i) => <FeaturedSignalCard key={i} s={s} large={i === 0} />)}
                </div>
                {p.squad_changes.length > 4 && (
                  <div className="mt-4 divide-y divide-divider">
                    {p.squad_changes.slice(4).map((s, i) => <SignalRow key={i} s={s} />)}
                  </div>
                )}
              </>
            )}
          </div>
          {p.change_feed.length > 0 && (
            <div className="border-t-2 border-divider pt-4 lg:border-l-2 lg:border-t-0 lg:pl-6 lg:pt-0">
              <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Change wire</div>
              <ChangeFeedRail rows={p.change_feed} />
            </div>
          )}
        </div>
      )}

      {/* TWO-COLUMN INTELLIGENCE BOARD - categories grouped, each visually distinct */}
      <div className="mt-8 grid grid-cols-1 gap-px bg-divider lg:grid-cols-2">
        <div className="bg-void px-10 py-6">
          {leftBoard.map((c) => (
            <div key={c.category} className="mb-8 last:mb-0">
              <div className={`mb-2 flex items-center gap-2 border-l-4 pl-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint ${CATEGORY_ACCENT[c.category] ?? 'border-text-faint'}`}>
                {c.label}
                <span className="tabular text-text-faint">{c.count}</span>
              </div>
              {c.signals.slice(0, 6).map((s, i) => <SignalRow key={i} s={s} />)}
            </div>
          ))}
        </div>
        <div className="bg-void px-10 py-6">
          {rightBoard.map((c) => (
            <div key={c.category} className="mb-8 last:mb-0">
              <div className={`mb-2 flex items-center gap-2 border-l-4 pl-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint ${CATEGORY_ACCENT[c.category] ?? 'border-text-faint'}`}>
                {c.label}
                <span className="tabular text-text-faint">{c.count}</span>
              </div>
              {c.signals.slice(0, 6).map((s, i) => <SignalRow key={i} s={s} />)}
            </div>
          ))}
        </div>
      </div>

      {p.team_state.length > 0 && (
        <div className="mt-10 px-10">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Team state</div>
          <div className="overflow-x-auto border-2 border-divider bg-panel px-4">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b-2 border-divider text-[11px] uppercase tracking-wide text-text-faint">
                  <th className="py-2 pr-4">Team</th>
                  <th className="py-2 pr-4">Attack</th>
                  <th className="py-2 pr-4">Defence</th>
                  <th className="py-2 pr-4">Tactical</th>
                  <th className="py-2 pr-4">FPL implication</th>
                </tr>
              </thead>
              <tbody>
                {p.team_state.map((t) => {
                  const crest = crestUrl(t.team_code)
                  return (
                    <tr key={t.team_id} className={`border-b-2 border-divider ${t.in_squad ? 'bg-raised' : ''}`}>
                      <td className="py-2 pr-4 font-bold text-text">
                        <span className="flex items-center gap-2">
                          {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
                          {t.team_name.toUpperCase()}
                          {t.in_squad && <span className="bg-broadcast-gold px-1 py-0.5 text-[9px] font-bold text-broadcast-gold-ink">MINE</span>}
                        </span>
                      </td>
                      <td className="tabular py-2 pr-4 text-text" style={heatStyle(t.attack?.xg ?? null, xgMin, xgMax, true)}>
                        {t.attack ? `${t.attack.xg?.toFixed(2)} xG${t.attack.shots !== null ? ` · ${t.attack.shots.toFixed(1)} shots` : ''}` : '—'}
                      </td>
                      <td className="tabular py-2 pr-4 text-text" style={heatStyle(t.defence?.xga ?? null, xgaMin, xgaMax, false)}>
                        {t.defence ? `${t.defence.xga?.toFixed(2)} xGA${t.defence.conceded !== null ? ` · ${t.defence.conceded.toFixed(1)} conceded` : ''}` : '—'}
                      </td>
                      <td className="py-2 pr-4 text-text-muted">{[t.formation, t.tactical].filter(Boolean).join(' - ') || '—'}</td>
                      <td className="py-2 pr-4 text-text-muted">{t.fpl_implication ?? '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TEAM ODDS - real next-fixture clean-sheet ranking, bar composition not a table */}
      {p.team_odds.length > 0 && (
        <div className="mt-10 border-t-2 border-divider px-10 pt-8">
          <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Team odds — next fixture</div>
          <div className="grid grid-cols-1 gap-x-10 gap-y-1 md:grid-cols-2">
            {p.team_odds.map((t) => {
              const crest = crestUrl(t.team_code)
              return (
                <div key={t.team_id} className="flex items-center gap-3 py-2">
                  {crest && <img src={crest} alt="" className="h-5 w-5 shrink-0 rounded-full" />}
                  <span className="w-12 shrink-0 font-bold text-text">{t.team_short}</span>
                  <span className="w-24 shrink-0 text-[11px] text-text-faint">vs {t.opponent_short} {t.is_home ? '(H)' : '(A)'}</span>
                  <span className="relative h-4 flex-1 border border-divider bg-void">
                    <span className="absolute inset-y-0 left-0 bg-pitch-green" style={{ width: `${t.clean_sheet_pct}%` }} />
                  </span>
                  <span className="tabular w-12 shrink-0 text-right text-sm font-bold text-pitch-green">{t.clean_sheet_pct.toFixed(0)}%</span>
                  <span className="tabular w-14 shrink-0 text-right text-xs text-text-faint">{t.projected_goals.toFixed(1)} gf</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
