import { Skeleton } from '@/components/ui/skeleton'
import { Masthead } from '@/components/shell/Masthead'
import { fetchAdvancedPayload } from '@/lib/api'
import { relativeTime } from '@/lib/time'
import { useFetch } from '@/lib/useFetch'

const STATUS_COLOR: Record<string, string> = {
  OK: 'bg-pitch-green text-pitch-green-ink', DEGRADED: 'bg-broadcast-gold text-broadcast-gold-ink', MISSING: 'bg-alert-red text-alert-red-ink',
}

const CHIP_DISPLAY_NAME: Record<string, string> = {
  wildcard: 'Wildcard', freehit: 'Free Hit', bboost: 'Bench Boost', '3xc': 'Triple Captain',
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
  { label: 'Models', names: ['Player projections', 'Squad optimizer', 'Transfer optimizer', 'Captaincy', 'Chip engine'] },
  { label: 'Infrastructure', names: ['Scheduler', 'Storage governor', 'Backup', 'Tests'] },
]

export function AdvancedScreen() {
  const state = useFetch(fetchAdvancedPayload, [])

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
  const grouped = READINESS_GROUPS.map((g) => ({ ...g, checks: p.readiness.filter((c) => g.names.includes(c.name)) })).filter(
    (g) => g.checks.length > 0,
  )
  const groupedNames = new Set(READINESS_GROUPS.flatMap((g) => g.names))
  const other = p.readiness.filter((c) => !groupedNames.has(c.name))

  return (
    <div className="pb-16">
      <Masthead
        edition="Systems Desk"
        title="The Engine Room"
        right={p.freshness?.is_stale ? <span className="text-broadcast-gold">Decision may be stale: {p.freshness.stale_reason}</span> : undefined}
      />

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
                <div className="flex min-w-[170px] flex-col gap-2 bg-panel px-5 py-4 shadow-[0_12px_24px_-14px_rgba(0,0,0,0.8)]">
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

      {/* CHIP STRATEGY - real eligible-chip value + why-now explanation */}
      {p.chips.length > 0 && (
        <div className="border-b-2 border-divider px-10 py-8">
          <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Chip strategy</div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {p.chips.map((c) => {
              const positive = c.value !== null && c.value >= 2.0
              const negative = c.value !== null && c.value < 0
              return (
                <div
                  key={c.name}
                  className={`border-l-4 bg-panel px-5 py-4 shadow-[0_16px_32px_-16px_rgba(0,0,0,0.8)] ${
                    positive ? 'border-pitch-green' : negative ? 'border-alert-red' : 'border-broadcast-gold'
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="font-display text-lg font-bold text-text">{CHIP_DISPLAY_NAME[c.name] ?? c.name}</span>
                    <span className="text-[10px] uppercase tracking-wide text-text-faint">GW{c.start_event}-{c.stop_event}</span>
                  </div>
                  <div className="mt-1">
                    {c.value !== null ? (
                      <span className={`tabular text-2xl font-bold ${positive ? 'text-pitch-green' : negative ? 'text-alert-red' : 'text-broadcast-gold'}`}>
                        {c.value.toFixed(1)} xP
                      </span>
                    ) : (
                      <span className="text-sm text-text-faint">run `fpl chips` for a value</span>
                    )}
                    {c.value_as_of && <span className="ml-2 text-xs text-text-faint">as of {relativeTime(c.value_as_of)}</span>}
                  </div>
                  {c.best_alternative_event !== null && c.opportunity_cost !== null && (
                    <div className="mt-2 text-xs text-text-muted">
                      Best alternative GW{c.best_alternative_event} (+{c.best_alternative_value?.toFixed(1)}pts) &middot; timing edge{' '}
                      <span className="font-semibold text-pitch-green">{c.opportunity_cost >= 0 ? '+' : ''}{c.opportunity_cost.toFixed(1)}pts</span>
                    </div>
                  )}
                  {c.confidence && (
                    <div className="mt-1 text-[10px] uppercase tracking-wide text-text-faint">
                      {c.confidence}-confidence season-sim{c.season_sim_as_of ? ` · ${relativeTime(c.season_sim_as_of)}` : ''}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* MODEL VS MARKET - real independent-model divergence list */}
      {p.benchmark && (
        <div className="border-b-2 border-divider px-10 py-8">
          <div className="mb-1 flex items-baseline gap-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Model vs market</span>
            <span className="text-[11px] text-text-faint">Solio GW{p.benchmark.gameweek} · {p.benchmark.age_hours.toFixed(1)}h old</span>
          </div>
          {p.benchmark.divergences.length === 0 ? (
            <div className="mt-3 text-sm text-text-muted">No material divergences from the independent model this snapshot.</div>
          ) : (
            <div className="mt-4 divide-y divide-divider border-2 border-divider bg-panel px-4 shadow-[0_24px_48px_-24px_rgba(0,0,0,0.9)]">
              {p.benchmark.divergences.map((d) => (
                <div key={d.player_id} className="flex flex-wrap items-center gap-3 py-3 text-sm">
                  <span className="font-bold text-text">{d.web_name}</span>
                  <span className="tabular text-text-muted">Our {d.our_median.toFixed(1)}</span>
                  <span className="tabular text-text-muted">Solio {d.solio_pr_points.toFixed(1)}</span>
                  {d.largest_driver && <span className="text-xs italic text-text-faint">driver: {d.largest_driver}</span>}
                  <span
                    className={`ml-auto shrink-0 px-1.5 py-0.5 text-[9px] font-bold uppercase ${
                      d.classification === 'MAJOR_OUTLIER' ? 'bg-alert-red text-alert-red-ink' : 'bg-broadcast-gold text-broadcast-gold-ink'
                    }`}
                  >
                    {d.classification.replace(/_/g, ' ')}
                  </span>
                </div>
              ))}
            </div>
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
        <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Source health</div>
        <div className="overflow-x-auto border-2 border-divider bg-panel px-4 shadow-[0_24px_48px_-24px_rgba(0,0,0,0.9)]">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b-2 border-divider text-[11px] uppercase tracking-wide text-text-faint">
              <th className="py-2 pr-4">Source</th>
              <th className="py-2 pr-4">Last success</th>
              <th className="py-2 pr-4">Failures</th>
              <th className="tabular py-2 pr-4">Latency</th>
            </tr>
          </thead>
          <tbody>
            {p.sources.map((s) => (
              <tr key={s.source_name} className="border-b-2 border-divider">
                <td className="py-2 pr-4 font-bold text-text">{s.source_name}</td>
                <td className="py-2 pr-4 text-text-muted">{s.last_success ?? '—'}</td>
                <td className={`py-2 pr-4 ${s.failure_count > 0 ? 'text-alert-red' : 'text-text-muted'}`}>{s.failure_count}</td>
                <td className="tabular py-2 pr-4 text-text-muted">{s.latency_ms !== null ? `${s.latency_ms}ms` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      <div className="border-t-2 border-divider px-10 py-6 text-sm text-text-faint">
        Decision Detail, Player Odds, Optimizer Delta, and Regret Analysis are real and already computed - not
        yet ported to this screen. Open the{' '}
        <a href="/dashboard.html#advanced" className="text-broadcast-blue underline">
          old dashboard's Advanced screen
        </a>{' '}
        for the complete diagnostic set.
      </div>
    </div>
  )
}
