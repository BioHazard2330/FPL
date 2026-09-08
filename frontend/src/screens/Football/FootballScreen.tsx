import type { CSSProperties } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { Masthead } from '@/components/shell/Masthead'
import { crestUrl, fetchFootballPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { FootballSignal } from '@/lib/types'

const DIRECTION_COLOR: Record<string, string> = {
  POSITIVE: 'text-pitch-green', NEGATIVE: 'text-alert-red', WATCH: 'text-broadcast-gold', NEUTRAL: 'text-text-muted',
}

const CATEGORY_ACCENT: Record<string, string> = {
  SET_PIECE_CHANGE: 'border-broadcast-blue', SET_PIECES: 'border-broadcast-blue', TACTICAL_CHANGE: 'border-broadcast-blue',
  CREATION: 'border-broadcast-gold', GOAL_THREAT: 'border-pitch-green', ROLE_CHANGE: 'border-alert-red', MINUTES: 'border-text-faint',
}
const LEFT_BOARD_CATEGORIES = ['SET_PIECE_CHANGE', 'SET_PIECES', 'TACTICAL_CHANGE', 'CREATION']

function FeaturedSignalCard({ s }: { s: FootballSignal }) {
  const crest = crestUrl(s.team_code)
  return (
    <div className={`min-w-[300px] flex-1 border-l-4 bg-panel px-6 py-5 shadow-[0_16px_32px_-16px_rgba(0,0,0,0.8)] ${CATEGORY_ACCENT[s.category] ?? 'border-text-faint'}`}>
      <div className="flex items-center gap-2">
        {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
        <span className="text-[10px] font-bold uppercase tracking-wide text-text-faint">{s.category.replace(/_/g, ' ')}</span>
      </div>
      <div className="mt-1.5 font-display text-2xl font-bold text-text">{s.entity_name}</div>
      <p className="mt-2 text-sm leading-relaxed text-text-muted">{s.evidence}</p>
      {s.interpretation && <p className="mt-1 text-sm italic text-text-faint">{s.interpretation}</p>}
      {s.fpl_effect && <div className={`mt-3 text-sm font-bold ${DIRECTION_COLOR[s.direction] ?? 'text-text'}`}>{s.fpl_effect}</div>}
    </div>
  )
}

function SignalRow({ s }: { s: FootballSignal }) {
  const crest = crestUrl(s.team_code)
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
  const state = useFetch(fetchFootballPayload, [])

  if (state.status === 'loading') {
    return (
      <div className="space-y-3 p-10">
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

      <div className="atmosphere-gold relative overflow-hidden px-10 pb-6 pt-7">
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

      {/* FEATURED SQUAD SIGNALS - large editorial rows */}
      {p.squad_changes.length > 0 && (
        <div className="mt-6 border-y-2 border-divider px-10 py-6">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Featured squad signals</div>
          <div className="flex flex-wrap gap-4">
            {p.squad_changes.slice(0, 4).map((s, i) => <FeaturedSignalCard key={i} s={s} />)}
          </div>
          {p.squad_changes.length > 4 && (
            <div className="mt-4 divide-y divide-divider">
              {p.squad_changes.slice(4).map((s, i) => <SignalRow key={i} s={s} />)}
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
          <div className="overflow-x-auto border-2 border-divider bg-panel px-4 shadow-[0_24px_48px_-24px_rgba(0,0,0,0.9)]">
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
