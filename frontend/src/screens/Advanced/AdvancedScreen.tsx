import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { DecisionAudit } from '@/components/advanced/DecisionAudit'
import { WeekPlanAudit } from '@/components/advanced/WeekPlanAudit'
import { fetchAdvancedPayload } from '@/lib/api'
import { relativeTime } from '@/lib/time'
import { useFetch } from '@/lib/useFetch'
import { ScreenError } from '@/components/shell/ScreenStates'

const STATUS_COLOR: Record<string, string> = {
  OK: 'bg-pitch-green text-pitch-green-ink', DEGRADED: 'bg-broadcast-gold text-broadcast-gold-ink', MISSING: 'bg-alert-red text-alert-red-ink',
}

/** Real, name-based presentation grouping of the flat readiness-check list
 * (full redesign pass, Part 10) - no new backend data, just sorting the
 * SAME real checks `readiness_payload.py` already returns into the logical
 * DATA/INTELLIGENCE/MODELS/INFRASTRUCTURE groups the spec asks for. Any
 * check whose name isn't in this table falls into "Other" rather than
 * being dropped. */
const READINESS_GROUPS: { label: string; names: string[] }[] = [
  { label: 'Data', names: ['Database', 'Current FPL data', 'Rules', 'Fixtures', 'Prices', 'Players', 'Transfers'] },
  { label: 'Intelligence', names: ['Injuries', 'Team news', 'Change detection', 'First-team generation'] },
  { label: 'Models', names: ['Player projections', 'Squad optimizer', 'Transfer planner', 'Captaincy', 'Chip engine'] },
  { label: 'Infrastructure', names: ['Scheduler', 'Storage governor', 'Backup', 'Tests'] },
]

/** Skeleton shaped like the workbench it precedes - verdict band, opposed
 * analysis columns, pipeline strip - not a stack of grey rectangles that
 * promises a layout this screen never renders. */
function AdvancedSkeleton() {
  return (
    <div className="animate-pulse pb-16">
      <div className="border-b border-divider px-10 py-3"><div className="h-3 w-64 bg-raised" /></div>
      <div className="border-b-2 border-divider px-10 py-8">
        <div className="h-2 w-32 bg-raised" />
        <div className="mt-3 h-14 w-56 bg-raised" />
        <div className="mt-6 flex gap-8">
          {[0, 1, 2, 3].map((i) => (
            <div key={i}><div className="h-2 w-20 bg-raised" /><div className="mt-2 h-6 w-24 bg-raised" /></div>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-px bg-divider lg:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="space-y-3 bg-void px-10 py-7">
            <div className="h-2 w-40 bg-raised" />
            {[0, 1, 2].map((j) => <div key={j} className="h-10 w-full bg-raised" />)}
          </div>
        ))}
      </div>
      <div className="flex gap-2 border-t-2 border-divider px-10 py-8">
        {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-24 w-40 shrink-0 bg-raised" />)}
      </div>
    </div>
  )
}

export function AdvancedScreen() {
  const state = useFetch(fetchAdvancedPayload, [], 60000)

  if (state.status === 'loading') return <AdvancedSkeleton />
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Diagnostics unavailable"
        description="The engine-room payload could not be fetched, so nothing on this screen is being shown — there is no cached copy and no fallback value. Readiness, model pipeline and source health are all unknown right now, which is not the same as healthy."
        message={state.error.message}
      />
    )
  }

  const p = state.data
  const grouped = READINESS_GROUPS.map((g) => ({ ...g, checks: p.readiness.filter((c) => g.names.includes(c.name)) })).filter(
    (g) => g.checks.length > 0,
  )
  const groupedNames = new Set(READINESS_GROUPS.flatMap((g) => g.names))
  const other = p.readiness.filter((c) => !groupedNames.has(c.name))

  return (
    <div className="data-in pb-16">
      <Masthead
        edition="Systems Desk"
        title="The Engine Room"
      />

      {p.week_plan_audit ? (
        <WeekPlanAudit audit={p.week_plan_audit} />
      ) : (
        <div className="border-b-2 border-divider px-10 py-8">
          <div className="font-display text-2xl font-bold text-text-faint">No week plan on file</div>
          <p className="mt-1.5 max-w-2xl text-sm text-text-muted">
            Run <code className="font-mono text-text">fpl week-plan</code>, or use Sync now in the header. The plan, and the stress test of each
            move in it, appear here once it exists.
          </p>
        </div>
      )}

      {p.decision_audit && !p.decision_audit.stale && <DecisionAudit audit={p.decision_audit} />}
      {p.decision_audit?.stale && (
        <div className="border-b-2 border-divider bg-panel px-10 py-4 text-sm text-text-muted">
          <span className="mr-3 text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">Adversarial audit</span>
          The last one is {p.decision_audit.age_days} days old and audits an earlier squad and an earlier recommendation, so it says nothing about
          this week. Run <code className="font-mono text-text">fpl decision-audit</code> to redo it.
        </div>
      )}

      {/* MODEL PIPELINE - the dominant visual, each stage its own object */}
      {p.pipeline.length > 0 && (
        <div className="relative overflow-hidden border-b-2 border-divider px-10 py-8">
          <span className="ghost-watermark pointer-events-none absolute -top-10 right-2 select-none font-display text-[9rem] font-bold uppercase leading-none">
            ENGINE
          </span>
          <div className="relative mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Model pipeline</div>
          <div className="flex items-stretch overflow-x-auto">
            {p.pipeline.map((stage, i) => (
              <div key={stage.stage} className="flex items-stretch">
                <div className="flex min-w-[170px] flex-col gap-2 bg-panel px-5 py-4">
                  <div className={`h-1 w-full ${STATUS_COLOR[stage.status]?.split(' ')[0] ?? 'bg-text-faint'}`} />
                  <div className="text-[10px] font-bold text-text-faint">0{i + 1}</div>
                  <div className="font-display text-sm font-bold uppercase tracking-wide text-text">{stage.stage}</div>
                  <div className="text-[11px] leading-snug text-text-faint" title={stage.detail}>
                    {stage.detail.length > 70 ? stage.detail.slice(0, 67) + '…' : stage.detail}
                  </div>
                </div>
                {i < p.pipeline.length - 1 && <div className="flex items-center px-1.5 text-text-faint">&rarr;</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* MODEL VS MARKET - a real weighted rail, not a boxed list - a real
          MAJOR_OUTLIER earns visibly more weight than a routine divergence,
          the same lead/rest hierarchy Command's own EvidenceRail uses. */}
      {p.benchmark && (
        <div className="border-t-2 border-divider bg-void px-10 py-8">
          <div className="mb-1 flex items-baseline gap-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Model vs market</span>
            <span className="text-[11px] text-text-faint">Solio GW{p.benchmark.gameweek} · {p.benchmark.age_hours.toFixed(1)}h old</span>
          </div>
          {p.benchmark.divergences.length === 0 ? (
            <div className="mt-3 text-sm text-text-muted">No material divergences from the independent model this snapshot.</div>
          ) : (
            <div className="mt-4 divide-y divide-divider">
              {/* Weight by the size of the real gap, not by classification
                  alone. Against real production data every surfaced row is
                  MAJOR_OUTLIER, so keying emphasis off the label gave eight
                  identically-loud rows and no hierarchy at all - the widest
                  real divergence is the one worth investigating first. */}
              {p.benchmark.divergences.map((d, i) => {
                const gaps = p.benchmark!.divergences.map((x) => Math.abs(x.our_median - x.solio_pr_points))
                const widest = Math.max(...gaps)
                const gap = gaps[i]
                const major = d.classification === 'MAJOR_OUTLIER' && gap >= widest - 1e-9
                return (
                  <div key={d.player_id} className={`flex flex-wrap items-center gap-3 ${major ? 'border-l-4 border-alert-red bg-panel py-4 pl-4' : 'py-3'}`}>
                    <Link
                      to={`/player/${d.player_id}`}
                      className={`font-bold text-text hover:text-pitch-green ${major ? 'font-display text-2xl' : ''}`}
                    >
                      {d.web_name}
                    </Link>
                    <span className="tabular text-text-muted">Our {d.our_median.toFixed(1)}</span>
                    <span className="tabular text-text-muted">Solio {d.solio_pr_points.toFixed(1)}</span>
                    <span className={`tabular font-bold ${gap >= 2 ? 'text-alert-red' : 'text-broadcast-gold'}`}>
                      {(d.our_median - d.solio_pr_points >= 0 ? '+' : '') + (d.our_median - d.solio_pr_points).toFixed(1)}
                    </span>
                    {d.largest_driver && <span className="text-xs italic text-text-faint">driver: {d.largest_driver}</span>}
                    <span
                      className={`ml-auto shrink-0 px-1.5 py-0.5 text-[9px] font-bold uppercase ${
                        major ? 'bg-alert-red text-alert-red-ink' : 'bg-broadcast-gold text-broadcast-gold-ink'
                      }`}
                    >
                      {d.classification.replace(/_/g, ' ')}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {p.player_odds.length > 0 && (
        <div className="border-t-2 border-divider px-10 py-8">
          <div className="mb-1 flex flex-wrap items-baseline gap-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Market price on my squad</span>
            <span className="text-[11px] text-text-faint">anytime goalscorer &middot; raw implied, not devigged</span>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-x-10 md:grid-cols-2">
            {p.player_odds.map((o) => (
              <div key={o.player_id} className="flex items-center gap-3 border-b border-divider py-2.5">
                <Link to={`/player/${o.player_id}`} className="w-28 shrink-0 truncate text-sm font-bold text-text hover:text-pitch-green">
                  {o.web_name ?? `#${o.player_id}`}
                </Link>
                <span className="w-10 shrink-0 text-[10px] font-bold uppercase text-text-faint">{o.team_short ?? ''}</span>
                <span className="tabular w-12 shrink-0 text-right text-sm font-bold text-text">
                  {(o.implied_probability_raw * 100).toFixed(0)}%
                </span>
                <span className="tabular w-12 shrink-0 text-right text-xs text-text-muted">{o.anytime_scorer_price.toFixed(2)}</span>
                <span className="w-16 shrink-0 text-right text-[10px] text-text-faint">{relativeTime(o.retrieved_at) ?? ''}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* POINTS REVISIONS - real post-match Bonus/DefCon corrections on the
          latest FINISHED gameweek. A zero here is a real measured zero (the
          detector ran and found nothing), not a placeholder - so it is
          stated as such rather than hiding the section. */}
      {p.points_revisions && (
        <div className="border-t-2 border-divider bg-panel px-10 py-8">
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">
              GW{p.points_revisions.event} points revisions
            </span>
            <span className="text-[11px] uppercase tracking-wide text-text-faint">
              {p.points_revisions.locked ? 'gameweek locked' : 'still provisional'}
            </span>
          </div>
          {p.points_revisions.total_revisions === 0 ? (
            <p className="mt-2 max-w-2xl text-sm text-text-muted">
              The revision detector ran against GW{p.points_revisions.event} and found no post-settlement Bonus or DefCon
              corrections. That is a real measured zero, not missing data.
            </p>
          ) : (
            <>
              <div className="mt-1 flex items-baseline gap-3">
                <span className="tabular font-display text-3xl font-bold text-text">{p.points_revisions.squad_revisions}</span>
                <span className="text-sm text-text-faint">of {p.points_revisions.total_revisions} league-wide hit my squad</span>
              </div>
              <div className="mt-4 divide-y divide-divider">
                {p.points_revisions.rows.map((r, i) => {
                  const delta = r.new_points - r.old_points
                  return (
                    <div key={i} className={`flex flex-wrap items-baseline gap-3 py-2.5 ${r.is_mine ? 'border-l-4 border-broadcast-gold pl-4' : ''}`}>
                      <Link to={`/player/${r.player_id}`} className="text-sm font-bold text-text hover:text-pitch-green">
                        {r.web_name}
                      </Link>
                      <span className="text-[10px] font-bold uppercase text-text-faint">{r.team_short} &middot; {r.position}</span>
                      <span className="bg-raised px-1.5 py-0.5 text-[9px] font-bold uppercase text-text-muted">{r.category}</span>
                      <span className="tabular text-xs text-text-muted">{r.old_value} &rarr; {r.new_value}</span>
                      <span className={`tabular ml-auto font-display text-lg font-bold ${delta >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
                        {delta >= 0 ? '+' : ''}{delta}
                      </span>
                      <span className="tabular w-20 shrink-0 text-right text-[10px] text-text-faint">
                        {r.detected_gap_hours.toFixed(1)}h after
                      </span>
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </div>
      )}

      {/* SYSTEM READINESS - logical bento groups, each its own visual treatment */}
      <div className="px-10 py-8">
        <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">System readiness</div>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
          {grouped.map((g) => (
            <div key={g.label} className="border-t-2 border-pitch-green/40 pt-3">
              <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-text-faint">{g.label}</div>
              <div className="divide-y divide-divider">
                {g.checks.map((c) => (
                  <div key={c.name} className="flex items-center justify-between gap-2 py-2">
                    <div>
                      <div className="text-sm font-semibold text-text">{c.name}</div>
                      <div className="text-[11px] text-text-faint">{c.detail}</div>
                    </div>
                    <span className={`shrink-0 px-1.5 py-0.5 text-[9px] font-bold ${STATUS_COLOR[c.status] ?? 'bg-raised text-text-muted'}`}>{c.status}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {other.length > 0 && (
            <div className="border-t-2 border-text-faint/30 pt-3">
              <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-text-faint">Other</div>
              <div className="divide-y divide-divider">
                {other.map((c) => (
                  <div key={c.name} className="flex items-center justify-between gap-2 py-2">
                    <div>
                      <div className="text-sm font-semibold text-text">{c.name}</div>
                      <div className="text-[11px] text-text-faint">{c.detail}</div>
                    </div>
                    <span className={`shrink-0 px-1.5 py-0.5 text-[9px] font-bold ${STATUS_COLOR[c.status] ?? 'bg-raised text-text-muted'}`}>{c.status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="border-t-2 border-divider px-10 py-8">
        <div className="mb-3 flex flex-wrap items-baseline gap-3">
          <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Source health</span>
          <span className="text-[11px] text-text-faint">
            {p.sources.filter((s) => s.active !== false).length} sources in use
            {p.sources.some((s) => s.active === false) &&
              ` · ${p.sources.filter((s) => s.active === false).length} dormant (one-off backfills and per-gameweek feeds, not fetched on a cycle)`}
          </span>
        </div>
        {/* An analytical instrument, not a table inside a box: thick header
            rule, dense rows, a state marker in the gutter, no container
            border competing with the row rules. */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Per-source ingestion health</caption>
            <thead>
              <tr className="border-b-2 border-divider text-[10px] uppercase tracking-[0.14em] text-text-faint">
                <th scope="col" className="py-2 pr-4 font-bold">Source</th>
                <th scope="col" className="py-2 pr-4 font-bold">Last success</th>
                <th scope="col" className="py-2 pr-4 font-bold">Failures</th>
                <th scope="col" className="py-2 pr-4 text-right font-bold">Latency</th>
              </tr>
            </thead>
            <tbody>
              {p.sources.filter((s) => s.active !== false).map((s) => {
                const failing = s.failure_count > 0
                return (
                  <tr key={s.source_name} className={`border-b border-divider ${failing ? 'bg-panel' : ''}`}>
                    <th scope="row" className="py-2 pr-4 text-left font-bold text-text">
                      <span className="flex items-center gap-2">
                        <span className={`size-1.5 shrink-0 rounded-full ${failing ? 'bg-alert-red' : 'bg-pitch-green'}`} />
                        {s.source_name}
                      </span>
                    </th>
                    <td className="py-2 pr-4 text-text-muted">
                      {s.last_success ? <>{relativeTime(s.last_success)} <span className="text-text-faint">· {s.last_success.slice(0, 16).replace('T', ' ')}</span></> : '—'}
                    </td>
                    <td className={`tabular py-2 pr-4 font-bold ${failing ? 'text-alert-red' : 'text-text-faint'}`}>{s.failure_count}</td>
                    <td className="tabular py-2 pr-4 text-right text-text-muted">{s.latency_ms !== null ? `${s.latency_ms}ms` : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  )
}
