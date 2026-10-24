import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Disclosure, Panel } from '@/components/ui/kit'
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
      <div className="border-b border-divider px-10 py-8">
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
      <div className="flex gap-2 border-t border-divider px-10 py-8">
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

  const allChecks = p.readiness
  const notOk = allChecks.filter((c) => c.status !== 'OK')
  const squadRevisions = p.points_revisions?.rows.filter((r) => r.is_mine) ?? []
  const divergences = p.benchmark?.divergences.slice(0, 6) ?? []

  const Check = ({ c }: { c: (typeof allChecks)[number] }) => (
    <div className="flex items-center justify-between gap-2 py-2">
      <div>
        <div className="text-sm font-semibold text-text">{c.name}</div>
        <div className="text-[13px] text-text-faint">{c.detail}</div>
      </div>
      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[12px] font-bold ${STATUS_COLOR[c.status] ?? 'bg-raised text-text-muted'}`}>{c.status}</span>
    </div>
  )

  return (
    <div className="data-in pb-16">
      <Masthead />

      {p.week_plan_audit ? (
        <WeekPlanAudit audit={p.week_plan_audit} />
      ) : (
        <Panel title="No week plan on file" sub={<>Run <code className="font-mono text-text">fpl week-plan</code>, or use Sync now in the header. The plan, and the stress test of each move in it, appear here once it exists.</>} />
      )}

      <Panel
        title={notOk.length === 0 ? 'Everything is running' : `${notOk.length} thing${notOk.length === 1 ? '' : 's'} to look at`}
        sub={
          notOk.length === 0
            ? `All ${allChecks.length} checks pass.`
            : notOk.map((c) => `${c.name}: ${c.detail}`).join(' ')
        }
      >
        <details>
          <summary className="cursor-pointer text-[13px] font-medium text-text-muted hover:text-text">All {allChecks.length} checks</summary>
          <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
            {grouped.map((g) => (
              <div key={g.label} className="border-t border-pitch-green/40 pt-3">
                <div className="mb-2 text-[13px] font-medium text-text-faint">{g.label}</div>
                <div className="divide-y divide-divider">
                  {g.checks.map((c) => <Check key={c.name} c={c} />)}
                </div>
              </div>
            ))}
            {other.length > 0 && (
              <div className="border-t border-text-faint/30 pt-3">
                <div className="mb-2 text-[13px] font-medium text-text-faint">Other</div>
                <div className="divide-y divide-divider">
                  {other.map((c) => <Check key={c.name} c={c} />)}
                </div>
              </div>
            )}
          </div>
        </details>
      </Panel>

      {p.decision_audit && !p.decision_audit.stale && <DecisionAudit audit={p.decision_audit} />}
      {p.decision_audit?.stale && (
        <Panel
          title="The deep audit is out of date"
          sub={<>The last one is {p.decision_audit.age_days} days old and checks an earlier squad, so it says nothing about this week. Run <code className="font-mono text-text">fpl decision-audit</code> to redo it.</>}
        />
      )}

      {p.benchmark && divergences.length > 0 && (
        <Disclosure
          title="Where we differ from Solio"
          summary={`${p.benchmark.divergences.length} players more than a point apart, GW${p.benchmark.gameweek} snapshot ${p.benchmark.age_hours.toFixed(1)}h old`}
        >
          <p className="mb-3 max-w-3xl text-[14px] leading-snug text-text-muted">
            Solio is an independent projection used only as a cross-check; it never feeds ours. A big gap is a prompt to look at the player, not a verdict. The usual reason is availability: we discount a doubtful player more heavily than Solio does.
          </p>
          <div className="divide-y divide-divider">
            {divergences.map((d) => {
              const gap = d.our_median - d.solio_pr_points
              return (
                <div key={d.player_id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2.5">
                  <Link to={`/player/${d.player_id}`} className="w-36 font-semibold text-text hover:text-pitch-green">{d.web_name}</Link>
                  <span className="tabular text-[14px] text-text-muted">ours {d.our_median.toFixed(1)}</span>
                  <span className="tabular text-[14px] text-text-muted">Solio {d.solio_pr_points.toFixed(1)}</span>
                  <span className={`tabular font-semibold ${Math.abs(gap) >= 2 ? 'text-alert-red' : 'text-broadcast-gold'}`}>{(gap >= 0 ? '+' : '') + gap.toFixed(1)}</span>
                  {d.largest_driver && <span className="text-[13px] text-text-faint">mostly {d.largest_driver}</span>}
                </div>
              )
            })}
          </div>
        </Disclosure>
      )}

      {p.points_revisions && p.points_revisions.total_revisions > 0 && (
        <Disclosure
          title={`GW${p.points_revisions.event} points revised after the matches`}
          summary={`${p.points_revisions.squad_revisions} of your players, ${p.points_revisions.total_revisions} league-wide; ${p.points_revisions.locked ? 'now locked' : 'still provisional'}`}
        >
          {squadRevisions.length === 0 ? (
            <p className="text-sm text-text-muted">None of your players had bonus or defensive-contribution points revised.</p>
          ) : (
            <div className="divide-y divide-divider">
              {squadRevisions.map((r, i) => {
                const delta = r.new_points - r.old_points
                return (
                  <div key={i} className="flex flex-wrap items-baseline gap-3 py-2.5">
                    <Link to={`/player/${r.player_id}`} className="w-32 text-sm font-semibold text-text hover:text-pitch-green">{r.web_name}</Link>
                    <span className="text-[13px] text-text-faint">{r.category === 'bonus' ? 'bonus' : 'defensive contribution'}</span>
                    <span className="tabular text-sm text-text-muted">{r.old_value} &rarr; {r.new_value}</span>
                    <span className={`tabular ml-auto font-display text-lg font-semibold ${delta >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{delta >= 0 ? '+' : ''}{delta} points</span>
                  </div>
                )
              })}
            </div>
          )}
        </Disclosure>
      )}

      <Disclosure
        title="Data sources"
        summary={`${p.sources.filter((s) => s.active !== false).length} in use${p.sources.some((s) => s.failure_count > 0 && s.active !== false) ? ', some failing' : ', none failing'}`}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Per-source ingestion health</caption>
            <thead>
              <tr className="border-b border-divider text-[13px] text-text-faint">
                <th scope="col" className="py-2 pr-4 font-medium">Source</th>
                <th scope="col" className="py-2 pr-4 font-medium">Last success</th>
                <th scope="col" className="py-2 pr-4 font-medium">Failures</th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">Latency</th>
              </tr>
            </thead>
            <tbody>
              {p.sources.filter((s) => s.active !== false).map((s) => {
                const failing = s.failure_count > 0
                return (
                  <tr key={s.source_name} className="border-b border-divider">
                    <th scope="row" className="py-2 pr-4 text-left font-medium text-text">
                      <span className="flex items-center gap-2">
                        <span className={`size-1.5 shrink-0 rounded-full ${failing ? 'bg-alert-red' : 'bg-pitch-green'}`} />
                        {s.source_name.replace(/_/g, ' ')}
                      </span>
                    </th>
                    <td className="py-2 pr-4 text-text-muted">{s.last_success ? relativeTime(s.last_success) : '—'}</td>
                    <td className={`tabular py-2 pr-4 font-semibold ${failing ? 'text-alert-red' : 'text-text-faint'}`}>{s.failure_count}</td>
                    <td className="tabular py-2 pr-4 text-right text-text-muted">{s.latency_ms !== null ? `${s.latency_ms}ms` : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Disclosure>
    </div>
  )
}
