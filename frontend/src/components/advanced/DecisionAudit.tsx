import type { DecisionAuditBlock } from '@/lib/types'
import { relativeTime } from '@/lib/time'

const GRADE_COLOR: Record<string, string> = {
  ROBUST: 'text-pitch-green',
  HIGH: 'text-pitch-green',
  GOOD: 'text-pitch-green',
  MEDIUM: 'text-broadcast-gold',
  MODERATE: 'text-broadcast-gold',
  FRAGILE: 'text-alert-red',
  LOW: 'text-alert-red',
  WEAK: 'text-alert-red',
  POOR: 'text-alert-red',
}

function grade(v: string | null): string {
  return v ? (GRADE_COLOR[v.toUpperCase()] ?? 'text-text') : 'text-text-faint'
}

/** The analyst's actual working question is not "what does the model say" -
 * it is "what would make this wrong." So the audit leads with the verdict
 * scorecard as an editorial band, then puts the falsifiers and the stress
 * tests that genuinely FLIP the decision above everything supporting it.
 * Nothing here is computed in the browser: it is a read of the cached
 * `fpl decision-audit` journal entry, age disclosed, because that artefact
 * is expensive and manual and can be days older than the decision. */
export function DecisionAudit({ audit }: { audit: DecisionAuditBlock }) {
  const sc = audit.scorecard
  const flipping = audit.stress_tests.filter((t) => t.decision_flips)
  const holding = audit.stress_tests.filter((t) => !t.decision_flips)
  const age = relativeTime(audit.created_at)

  return (
    <div className="relative overflow-hidden border-b-2 border-divider">
      <span className="ghost-watermark pointer-events-none absolute -top-14 right-4 select-none font-display text-[12rem] font-bold uppercase leading-none">
        AUDIT
      </span>

      {/* VERDICT BAND */}
      <div className="relative flex flex-wrap items-end gap-x-10 gap-y-4 px-10 pb-6 pt-8">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">Adversarial verdict</div>
          <div className="font-display text-6xl font-bold uppercase leading-none text-text">{sc.final_decision ?? '—'}</div>
        </div>
        <div className="flex flex-wrap gap-x-8 gap-y-3 border-l-2 border-divider pl-10">
          {([
            ['Robustness', sc.decision_robustness],
            ['Confidence', sc.confidence],
            ['Data quality', sc.data_quality],
            ['Market evidence', sc.market_evidence],
          ] as const).map(([label, value]) => (
            <div key={label}>
              <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">{label}</div>
              <div className={`font-display text-xl font-bold uppercase ${grade(value)}`}>{value ?? '—'}</div>
            </div>
          ))}
        </div>
        <div className="ml-auto max-w-xs text-right">
          <div className="font-mono text-[10px] uppercase tracking-wide text-text-faint">Audited {age ?? 'unknown'}</div>
          <div className="mt-1 text-[11px] leading-snug text-text-faint">
            Run <code className="font-mono text-text-muted">fpl decision-audit</code> to re-stress the current call.
          </div>
        </div>
      </div>

      {audit.cross_check_note && (
        <div className="relative mx-10 mb-6 border-l-4 border-broadcast-gold bg-panel px-5 py-3">
          <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-broadcast-gold">Methodology conflict</span>
          <p className="mt-1 text-sm text-text-muted">{audit.cross_check_note}</p>
          <p className="mt-1 text-[11px] italic text-text-faint">
            This cross-check is itself {age ?? 'of unknown age'} &mdash; re-run the audit before treating it as live.
          </p>
        </div>
      )}

      {/* WHAT WOULD MAKE THIS WRONG - the dominant analytical content */}
      <div className="relative grid grid-cols-1 gap-px border-t-2 border-divider bg-divider lg:grid-cols-[1fr_1fr]">
        <div className="bg-void px-10 py-7">
          <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-alert-red">What would make this wrong</div>
          {audit.falsifiers.length === 0 ? (
            <p className="mt-3 text-sm text-text-muted">The audit recorded no falsifier it could state a threshold for.</p>
          ) : (
            <ol className="mt-4 space-y-4">
              {audit.falsifiers.map((f, i) => (
                <li key={i} className="flex gap-4">
                  <span className="tabular shrink-0 font-display text-2xl font-bold leading-none text-alert-red">{String(i + 1).padStart(2, '0')}</span>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold leading-snug text-text">{f.description ?? '—'}</div>
                    {f.threshold_note && <div className="mt-0.5 text-[11px] text-text-faint">{f.threshold_note}</div>}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>

        <div className="bg-void px-10 py-7">
          <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">
            Counterfactual stress tests
            <span className="ml-2 normal-case tracking-normal text-text-faint">
              {flipping.length} of {audit.stress_tests.length} flip the decision
            </span>
          </div>
          {audit.stress_tests.length === 0 ? (
            <p className="mt-3 text-sm text-text-muted">No stress tests recorded in this audit.</p>
          ) : (
            <div className="mt-4 space-y-3">
              {flipping.map((t, i) => (
                <div key={`f${i}`} className="border-l-4 border-alert-red bg-panel px-4 py-2.5">
                  <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-alert-red">Flips the call</span>
                  <p className="mt-0.5 text-sm leading-snug text-text">{t.note ?? '—'}</p>
                </div>
              ))}
              {holding.length > 0 && (
                <ul className="space-y-1.5 pt-1">
                  {holding.map((t, i) => (
                    <li key={`h${i}`} className="flex gap-2.5 text-[13px] leading-snug text-text-muted">
                      <span className="mt-2 size-1 shrink-0 bg-pitch-green" />
                      <span>{t.note ?? '—'}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

      {/* TRUST LEDGER - two opposed columns, never a neutral bullet list */}
      {(sc.why_trust.length > 0 || sc.why_might_not_trust.length > 0) && (
        <div className="relative grid grid-cols-1 gap-px border-t-2 border-divider bg-divider lg:grid-cols-2">
          <div className="bg-void px-10 py-7">
            <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-pitch-green">Why I trust this</div>
            <ul className="mt-3 space-y-2">
              {sc.why_trust.map((w, i) => (
                <li key={i} className="flex gap-2.5 text-sm leading-snug text-text-muted">
                  <span className="mt-1.5 h-2 w-2 shrink-0 bg-pitch-green" />
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="bg-void px-10 py-7">
            <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-broadcast-gold">Why I might not</div>
            <ul className="mt-3 space-y-2">
              {sc.why_might_not_trust.map((w, i) => (
                <li key={i} className="flex gap-2.5 text-sm leading-snug text-text-muted">
                  <span className="mt-1.5 h-2 w-2 shrink-0 bg-broadcast-gold" />
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* CAUSAL CHAIN - a numbered spine, the reasoning read in order */}
      {audit.causal_chain.length > 0 && (
        <div className="relative border-t-2 border-divider px-10 py-7">
          <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Causal chain</div>
          <ol className="border-l-2 border-divider">
            {audit.causal_chain.map((c, i) => (
              <li key={i} className="relative pb-4 pl-6 last:pb-0">
                <span className="absolute -left-[5px] top-1.5 size-2 bg-broadcast-blue" />
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-broadcast-blue">{c.label ?? `Step ${i + 1}`}</div>
                <div className="mt-0.5 text-sm leading-snug text-text-muted">{c.detail ?? '—'}</div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* LEAGUE-WIDE OPPORTUNITY CHECK */}
      {audit.league_wide && (
        <div className="relative border-t-2 border-divider bg-panel px-10 py-6">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">League-wide opportunity check</div>
          <div className="flex flex-wrap items-end gap-x-10 gap-y-3">
            {([
              ['Breakouts', audit.league_wide.breakout_count],
              ['Differentials', audit.league_wide.differential_count],
              ['Traps tracked', audit.league_wide.trap_count],
            ] as const).map(([label, value]) =>
              value === undefined ? null : (
                <div key={label}>
                  <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">{label}</div>
                  <div className="tabular font-display text-2xl font-bold text-text">{value}</div>
                </div>
              ),
            )}
            {audit.league_wide.chosen_in_is_trap !== undefined && (
              <div className="border-l-2 border-divider pl-8">
                <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">Chosen candidate on trap list</div>
                <div className={`font-display text-2xl font-bold uppercase ${audit.league_wide.chosen_in_is_trap ? 'text-alert-red' : 'text-pitch-green'}`}>
                  {audit.league_wide.chosen_in_is_trap ? 'Yes' : 'No'}
                </div>
              </div>
            )}
          </div>
          {(audit.league_wide.top_differentials?.length ?? 0) > 0 && (
            <div className="mt-4 border-t border-divider pt-3">
              <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">Top differentials the audit weighed</div>
              <div className="mt-1.5 flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-text-muted">
                {audit.league_wide.top_differentials?.map((d, i) => <span key={i}>{d}</span>)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
