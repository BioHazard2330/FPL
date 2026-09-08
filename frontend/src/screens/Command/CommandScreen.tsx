import { Skeleton } from '@/components/ui/skeleton'
import { MetricNumber } from '@/components/shell/MetricNumber'
import { crestUrl, fetchCommandPayload, shirtUrl } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { ActionSquadPlayer } from '@/lib/types'

/** COMMAND — full art-direction pass (2026-09-08). Previous version was a
 * correct-but-generic stack of rows (headline, two-card comparison, KPI
 * strip, more rows) - real information, dashboard-shaped presentation.
 * Rebuilt as five structurally distinct modules, each its own composition
 * device rather than another bordered card: an asymmetric hero with a bar
 * comparison (not a card pair), a horizontal margin-evolution strip, a
 * true VS captain split, a branching strategy-dependency timeline, an
 * editorial football-evidence rail, and one confidence composition instead
 * of three KPI boxes. Every number is still the same real backend field -
 * only the composition changed. */

const DIRECTION_COLOR: Record<string, string> = {
  POSITIVE: 'text-pitch-green', NEGATIVE: 'text-alert-red', WATCH: 'text-broadcast-gold', NEUTRAL: 'text-text-muted',
}
const DIRECTION_BAR: Record<string, string> = {
  POSITIVE: 'bg-pitch-green', NEGATIVE: 'bg-alert-red', WATCH: 'bg-broadcast-gold', NEUTRAL: 'bg-text-faint',
}

/** Real size hierarchy, not a uniform row (art-direction pass, 2026-09-08 v2):
 * the captain reads as the headline player of the gallery, the rest scale
 * down by real projected median - never a decorative/random size, the same
 * number already driving the green figure under each shirt. */
function ActionSquadTile({
  p, captainId, viceId, tier = 'normal',
}: {
  p: ActionSquadPlayer
  captainId: number | null
  viceId: number | null
  tier?: 'captain' | 'featured' | 'normal' | 'bench'
}) {
  const pxSize = tier === 'captain' ? 148 : tier === 'featured' ? 116 : tier === 'bench' ? 60 : 92
  const shirt = shirtUrl(p.team_code, p.position === 'GKP', pxSize)
  const crest = crestUrl(p.team_code)
  const sizeClass =
    tier === 'captain' ? 'h-24 w-24' : tier === 'featured' ? 'h-[4.5rem] w-[4.5rem]' : tier === 'bench' ? 'h-10 w-10' : 'h-14 w-14'
  const nameClass = tier === 'captain' ? 'font-display text-lg font-bold' : tier === 'featured' ? 'text-sm font-bold' : 'text-xs font-bold'
  const medianClass = tier === 'captain' ? 'text-2xl' : tier === 'featured' ? 'text-base' : 'text-sm'
  return (
    <div className={`relative flex flex-col items-center text-center ${tier === 'captain' ? 'w-32' : tier === 'featured' ? 'w-24' : tier === 'bench' ? 'w-16' : 'w-20'}`}>
      {p.player_id === captainId && (
        <span className="absolute right-1 top-0 flex h-5 w-5 items-center justify-center bg-broadcast-gold text-xs font-bold text-broadcast-gold-ink">C</span>
      )}
      {p.player_id === viceId && (
        <span className="absolute right-1 top-0 flex h-4 w-4 items-center justify-center bg-raised text-[10px] font-bold text-text">V</span>
      )}
      <div className={`relative ${sizeClass} drop-shadow-[0_10px_16px_rgba(0,0,0,0.6)]`}>
        {shirt ? <img src={shirt} alt="" className={`${sizeClass} object-contain`} /> : <div className={`${sizeClass} bg-raised`} />}
        {crest && <img src={crest} alt="" className="absolute -bottom-0.5 -right-0.5 h-4 w-4 rounded-full bg-void shadow-[0_0_0_2px_var(--void)]" />}
      </div>
      <div className={`mt-1.5 w-full truncate text-text ${nameClass}`}>{p.name}</div>
      <div className={`tabular font-bold text-pitch-green ${medianClass}`}>{p.median.toFixed(1)}</div>
    </div>
  )
}

export function CommandScreen() {
  const state = useFetch(fetchCommandPayload, [])

  if (state.status === 'loading') {
    return (
      <div className="space-y-4 p-10">
        <Skeleton className="h-6 w-40" />
        <div className="grid grid-cols-2 gap-6">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-72 w-full" />
        </div>
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <div className="bg-alert-red p-6 font-semibold text-alert-red-ink">
        Can't reach the backend ({state.error.message}). Is `fpl live-server` running?
      </div>
    )
  }

  const p = state.data
  const chosenTotal = p.checkpoint_table?.chosen.totals[p.checkpoint_table.chosen.totals.length - 1] ?? null
  const altTotal = p.checkpoint_table?.alt.totals[p.checkpoint_table.alt.totals.length - 1] ?? null
  const maxTotal = Math.max(chosenTotal ?? 0, altTotal ?? 0, 1)
  const fragileCount =
    p.why.filter((w) => w.tag === 'FRAGILE').length + (p.trajectory?.future_legs.filter((l) => l.fragile_dependency).length ?? 0)

  return (
    <div className="pb-20">
      {/* ── HERO ── three-column broadcast graphic: decision / comparison / oversized GW anchor.
          The GW numeral is a real structural column now, not a corner sticker. */}
      <section className="atmosphere-blue relative overflow-hidden border-b-2 border-divider">
        <div className="relative grid grid-cols-1 lg:grid-cols-[1.05fr_0.8fr_auto]">
          <div className="px-10 pb-12 pt-8">
            <div className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-faint">{p.gw.label} &middot; The decision</div>
            <div className="verdict-block mt-4 inline-block bg-pitch-green py-4 pl-6 pr-14 shadow-[0_20px_40px_-16px_rgba(31,206,107,0.5)]">
              <h1 className="font-display text-5xl font-bold uppercase leading-[0.9] text-pitch-green-ink md:text-6xl">{p.action.word}</h1>
            </div>
            {p.alternative && (
              <div className="mt-3 text-2xl font-semibold normal-case text-text-faint md:text-3xl">
                not {p.alternative.label.replace(/^PLAY /i, '').toLowerCase()}
              </div>
            )}
            {p.why.length > 0 && (
              <div className="mt-6 max-w-xl space-y-2 border-l-2 border-pitch-green/40 pl-4">
                {p.why.map((w, i) => (
                  <p key={i} className="text-sm leading-relaxed text-text-muted">
                    {w.tag && <span className={`mr-2 font-bold ${w.tag === 'FRAGILE' ? 'text-broadcast-gold' : 'text-pitch-green'}`}>{w.tag}</span>}
                    {w.text}
                  </p>
                ))}
              </div>
            )}
            <div className="mt-6 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px] uppercase tracking-wide text-text-faint">
              <span>{p.bar.free_transfers.value} free transfer{p.bar.free_transfers.value === '1' ? '' : 's'}</span>
              <span>£{p.bar.bank_m.toFixed(1)}m bank</span>
              {p.bar.chips_available.length > 0 && <span className="text-broadcast-gold">{p.bar.chips_available.join(' · ')}</span>}
            </div>
          </div>

          {/* dominant centre visual: a bar-height comparison, not a card */}
          {chosenTotal !== null && altTotal !== null && p.checkpoint_table && (
            <div className="flex items-end justify-center gap-8 px-6 pb-12 pt-4">
              <div className="flex flex-col items-center gap-3">
                <div className="text-2xl font-bold text-text-faint opacity-60">
                  <MetricNumber value={altTotal} />
                </div>
                <div
                  className="w-16 border-t-2 border-text-faint/50 bg-panel shadow-[0_10px_24px_-10px_rgba(0,0,0,0.7)] transition-[height] duration-500"
                  style={{ height: `${Math.max(24, (altTotal / maxTotal) * 220)}px` }}
                />
                <div className="max-w-20 text-center text-[10px] font-bold uppercase leading-tight tracking-wide text-text-faint">
                  {p.checkpoint_table.alt.name}
                </div>
              </div>
              <div className="flex flex-col items-center gap-3">
                <div className="text-4xl font-bold text-pitch-green">
                  <MetricNumber value={chosenTotal} />
                </div>
                <div
                  className="w-20 border-t-2 border-white/40 bg-pitch-green shadow-[0_16px_32px_-8px_rgba(31,206,107,0.55)] transition-[height] duration-500"
                  style={{ height: `${Math.max(24, (chosenTotal / maxTotal) * 220)}px` }}
                />
                <div className="max-w-24 text-center text-[10px] font-bold uppercase leading-tight tracking-wide text-text">
                  {p.checkpoint_table.chosen.name}
                </div>
              </div>
              <div className="pb-2 text-xs font-bold uppercase tracking-wide text-text-faint">
                {p.checkpoint_table.horizons[p.checkpoint_table.horizons.length - 1]}GW total
              </div>
            </div>
          )}

          {/* right anchor: the gameweek itself as a vertical broadcast marker, not a corner sticker */}
          <div className="relative hidden w-40 shrink-0 items-center justify-center overflow-hidden border-l-2 border-divider/60 lg:flex">
            <span
              className="ghost-watermark pointer-events-none select-none font-display text-[7.5rem] font-bold uppercase leading-none"
              style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
            >
              {p.gw.label}
            </span>
          </div>
        </div>
      </section>

      {/* ── THE SQUAD THIS ACTION PRODUCES ── real starting XI for the recommended action */}
      {p.action_squad && p.action_squad.starting.length > 0 && (
        <section className="border-b-2 border-divider px-10 py-8">
          <div className="mb-5 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">
            {p.action_squad.action ? `The ${p.action_squad.action.toLowerCase()} squad` : 'Resulting squad'}
          </div>
          <div className="flex flex-wrap items-end gap-x-7 gap-y-5">
            {p.action_squad.starting
              .slice()
              .sort((a, b) => b.median - a.median)
              .map((pl, i) => {
                const tier =
                  pl.player_id === p.action_squad!.captain_id ? 'captain' : i < 3 ? 'featured' : 'normal'
                return <ActionSquadTile key={pl.player_id} p={pl} captainId={p.action_squad!.captain_id} viceId={p.action_squad!.vice_id} tier={tier} />
              })}
          </div>
          {p.action_squad.bench.length > 0 && (
            <div className="mt-6 flex flex-wrap items-end gap-x-6 gap-y-4 border-t-2 border-divider pt-5 opacity-60">
              {p.action_squad.bench.map((pl) => (
                <ActionSquadTile key={pl.player_id} p={pl} captainId={null} viceId={null} tier="bench" />
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── MODULE 1: DECISION MARGIN ── full-bleed horizontal evolution strip */}
      {p.checkpoint_table && p.checkpoint_table.horizons.length > 0 && (
        <section className="border-b-2 border-divider px-10 py-10">
          <div className="mb-6 flex items-baseline gap-4">
            <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Decision margin</span>
            <span className="tabular font-display text-4xl font-bold text-pitch-green">
              {p.checkpoint_table.edge[p.checkpoint_table.edge.length - 1] >= 0 ? '+' : ''}
              {p.checkpoint_table.edge[p.checkpoint_table.edge.length - 1].toFixed(1)}pts
            </span>
            <span className="text-xs text-text-faint">at the {p.checkpoint_table.horizons[p.checkpoint_table.horizons.length - 1]}-GW horizon</span>
          </div>
          <div className="relative flex items-end gap-0">
            {/* real trend line tracing the same edge values the bars encode -
                a broadcast-style horizon graphic, not a bare bar row */}
            <svg
              className="pointer-events-none absolute inset-x-0 bottom-[calc(1.75rem+0.5rem)] h-24 w-full"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
            >
              <polyline
                fill="none"
                stroke="var(--pitch-green)"
                strokeWidth="1.5"
                strokeOpacity="0.55"
                vectorEffect="non-scaling-stroke"
                points={p.checkpoint_table.horizons
                  .map((_, i) => {
                    const edge = p.checkpoint_table!.edge[i]
                    const maxEdge = Math.max(...p.checkpoint_table!.edge.map((e) => Math.abs(e)), 1)
                    const barH = Math.max(6, (Math.abs(edge) / maxEdge) * 90)
                    const x = ((i + 0.5) / p.checkpoint_table!.horizons.length) * 100
                    const y = 100 - (barH / 96) * 100
                    return `${x},${y}`
                  })
                  .join(' ')}
              />
            </svg>
            {p.checkpoint_table.horizons.map((h, i) => {
              const edge = p.checkpoint_table!.edge[i]
              const maxEdge = Math.max(...p.checkpoint_table!.edge.map((e) => Math.abs(e)), 1)
              const barH = Math.max(6, (Math.abs(edge) / maxEdge) * 90)
              return (
                <div key={h} className="flex flex-1 flex-col items-center gap-2">
                  <div className="tabular text-sm font-bold text-text">{edge >= 0 ? '+' : ''}{edge.toFixed(1)}</div>
                  <div className="flex h-24 w-full items-end justify-center">
                    <div
                      className={`w-2/3 max-w-10 border-t-2 ${edge >= 0 ? 'border-white/40 bg-pitch-green shadow-[0_8px_16px_-6px_rgba(31,206,107,0.5)]' : 'border-white/20 bg-alert-red shadow-[0_8px_16px_-6px_rgba(227,69,47,0.5)]'}`}
                      style={{ height: `${barH}px` }}
                    />
                  </div>
                  <div className="w-full border-t-2 border-divider pt-2 text-center text-[10px] font-bold uppercase tracking-wide text-text-faint">
                    {h} GW
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* ── MODULE 2: CAPTAIN BATTLE ── true VS split, center divider */}
      {p.captain && (
        <section className="border-b-2 border-divider">
          <div className="px-10 pt-8 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Captain battle</div>
          <div className="grid grid-cols-1 items-stretch md:grid-cols-[1fr_auto_1fr]">
            <div className="atmosphere-green relative flex items-center justify-end gap-6 overflow-hidden px-10 py-10 text-right">
              <div>
                <div className="relative font-display text-4xl font-bold uppercase text-text md:text-5xl">{p.captain.best.name}</div>
                <div className="tabular relative mt-2 text-5xl font-bold text-pitch-green">
                  <MetricNumber value={p.captain.best.median} suffix=" xP" />
                </div>
                {(p.captain.best.floor !== null || p.captain.best.ceiling !== null) && (
                  <div className="tabular relative mt-1 text-xs text-text-faint">
                    {p.captain.best.floor?.toFixed(1) ?? '—'}&ndash;{p.captain.best.ceiling?.toFixed(1) ?? '—'} range
                  </div>
                )}
              </div>
              {(() => {
                const shirt = p.captain!.best.team_code !== null ? shirtUrl(p.captain!.best.team_code, p.captain!.best.position === 'GKP', 220) : null
                return shirt ? (
                  <img src={shirt} alt="" className="relative h-32 w-32 shrink-0 object-contain drop-shadow-[0_16px_24px_rgba(0,0,0,0.6)] md:h-40 md:w-40" />
                ) : null
              })()}
            </div>
            <div className="flex items-center justify-center px-6 py-6">
              <div className="flex size-16 items-center justify-center rounded-full border-2 border-broadcast-gold bg-void font-display text-lg font-bold text-broadcast-gold shadow-[0_8px_24px_-8px_rgba(240,169,62,0.5)]">
                VS
              </div>
            </div>
            <div className="flex items-center justify-start gap-6 px-10 py-10">
              {p.captain.second && (() => {
                const shirt = p.captain!.second!.team_code !== null ? shirtUrl(p.captain!.second!.team_code, p.captain!.second!.position === 'GKP', 180) : null
                return shirt ? (
                  <img src={shirt} alt="" className="h-24 w-24 shrink-0 object-contain opacity-80 drop-shadow-[0_12px_18px_rgba(0,0,0,0.55)] md:h-28 md:w-28" />
                ) : null
              })()}
              {p.captain.second ? (
                <div>
                  <div className="font-display text-2xl font-bold uppercase text-text-muted md:text-3xl">{p.captain.second.name}</div>
                  <div className="tabular mt-2 text-3xl font-bold text-text-muted">{p.captain.second.median.toFixed(1)} xP</div>
                  {(p.captain.second.floor !== null || p.captain.second.ceiling !== null) && (
                    <div className="tabular mt-1 text-xs text-text-faint">
                      {p.captain.second.floor?.toFixed(1) ?? '—'}&ndash;{p.captain.second.ceiling?.toFixed(1) ?? '—'} range
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-sm text-text-faint">No genuine second option this week.</div>
              )}
            </div>
          </div>
          {p.captain.edge_driver && (
            <div className="border-t border-divider px-10 py-3 text-center text-sm text-text-muted">
              Edge driven by <span className="font-semibold text-text">{p.captain.edge_driver.label}</span>{' '}
              <span className="font-bold text-pitch-green">(+{p.captain.edge_driver.value.toFixed(1)})</span>
              {p.captain.robustness && <span className="ml-4 text-xs uppercase tracking-wide text-text-faint">{p.captain.robustness}</span>}
            </div>
          )}
        </section>
      )}

      {/* ── MODULE 3: WHAT BREAKS THE DECISION ── branching strategy timeline */}
      {p.trajectory && p.trajectory.future_legs.length > 0 && (
        <section className="border-b-2 border-divider px-10 py-10">
          <div className="mb-6 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Strategy path — what breaks this</div>
          <div className="flex gap-0 overflow-x-auto pb-2">
            <div className="flex min-w-fit flex-col items-center gap-2 pr-6">
              <div className="flex size-3 items-center justify-center rounded-full bg-pitch-green" />
              <div className="w-28 text-center text-[11px] font-bold uppercase tracking-wide text-pitch-green">{p.trajectory.now.gw ? `GW${p.trajectory.now.gw}` : 'Now'}</div>
              <div className="w-28 text-center text-xs text-text-muted">{p.trajectory.now.action}</div>
            </div>
            {p.trajectory.future_legs.map((leg, i) => (
              <div key={i} className="flex min-w-fit items-center">
                <div className={`h-px w-8 ${leg.fragile_dependency ? 'border-t-2 border-dashed border-broadcast-gold' : 'bg-divider'}`} />
                <div className="flex flex-col items-center gap-2 px-4">
                  <div className={`flex size-3 items-center justify-center rounded-full ${leg.fragile_dependency ? 'bg-broadcast-gold' : 'bg-divider'}`} />
                  <div className={`w-28 text-center text-[11px] font-bold uppercase tracking-wide ${leg.fragile_dependency ? 'text-broadcast-gold' : 'text-text-faint'}`}>
                    {leg.gw ? `GW${leg.gw}` : `Step ${i + 1}`}
                  </div>
                  <div className="w-28 text-center text-xs text-text-muted">{leg.action}</div>
                </div>
              </div>
            ))}
          </div>
          {p.monitor.length > 0 && (
            <div className="mt-8 divide-y divide-divider border-t-2 border-divider">
              {p.monitor.map((r, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2 py-3 text-sm">
                  <span className="font-semibold text-text">{r.current}</span>
                  <span className="text-text-faint">&rarr;</span>
                  <span className="text-text-muted">{r.trigger}</span>
                  <span className="text-text-faint">&rarr;</span>
                  <span className="font-semibold text-pitch-green">{r.consequence}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── MODULE 4: FOOTBALL CONTEXT ── editorial horizontal rail */}
      {p.football_context.length > 0 && (
        <section className="border-b-2 border-divider py-10">
          <div className="px-10 mb-6 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Football context</div>
          <div className="flex gap-px overflow-x-auto bg-divider px-px">
            {p.football_context.map((f, i) =>
              i === 0 ? (
                <div key={i} className="atmosphere-gold relative min-w-[340px] overflow-hidden bg-void px-8 py-8">
                  <div className="relative text-[10px] font-bold uppercase tracking-wide text-broadcast-gold">{f.category.replace(/_/g, ' ')}</div>
                  <div className="relative mt-1 font-display text-4xl font-bold leading-[0.95] text-text">{f.entity_name}</div>
                  <p className="relative mt-3 max-w-sm text-sm leading-relaxed text-text-muted">{f.evidence}</p>
                  {f.fpl_effect && <div className={`relative mt-4 text-base font-bold ${DIRECTION_COLOR[f.direction] ?? 'text-text'}`}>{f.fpl_effect}</div>}
                </div>
              ) : (
                <div key={i} className="min-w-[200px] max-w-[240px] shrink-0 bg-void px-6 py-6">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">{f.category.replace(/_/g, ' ')}</div>
                  <div className="mt-1 font-display text-lg font-bold text-text">{f.entity_name}</div>
                  <p className="mt-1.5 text-xs leading-relaxed text-text-muted">{f.evidence}</p>
                  {f.fpl_effect && <div className={`mt-2 text-xs font-bold ${DIRECTION_COLOR[f.direction] ?? 'text-text'}`}>{f.fpl_effect}</div>}
                </div>
              ),
            )}
          </div>
        </section>
      )}

      {/* ── MODULE 5: DECISION CONFIDENCE ── one composition, not three KPI boxes */}
      <section className="px-10 py-10">
        <div className="mb-6 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Decision confidence</div>
        <div className="flex flex-col gap-6 md:flex-row md:items-center">
          {p.edge && (
            <div className="flex items-center gap-4">
              <div className="font-display text-5xl font-bold text-pitch-green">
                <MetricNumber value={p.edge.value} suffix="pt" />
              </div>
              <div className="text-xs text-text-faint">
                edge vs {p.edge.alt_label}
                <br />
                {p.edge.horizon}
              </div>
            </div>
          )}
          <div className="h-10 w-px bg-divider max-md:hidden" />
          <div className="flex-1">
            <div className="h-2 w-full overflow-hidden bg-panel">
              <div
                className={`h-full ${fragileCount === 0 ? 'bg-pitch-green' : fragileCount <= 1 ? 'bg-broadcast-gold' : 'bg-alert-red'}`}
                style={{ width: `${Math.max(8, 100 - fragileCount * 22)}%` }}
              />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-text-muted">
              <span>
                {fragileCount === 0 ? 'No fragile dependencies flagged' : `${fragileCount} fragile dependenc${fragileCount === 1 ? 'y' : 'ies'} flagged`}
              </span>
              {p.captain?.robustness && <span className="uppercase tracking-wide text-text-faint">Robustness: {p.captain.robustness}</span>}
              {p.freshness?.is_stale && <span className="font-semibold text-broadcast-gold">Stale — {p.freshness.stale_reason ?? 'recomputing'}</span>}
            </div>
          </div>
          {p.status.degraded_sources.length > 0 && (
            <div className="flex items-center gap-2 text-xs text-alert-red">
              <span className={`size-1.5 rounded-full ${DIRECTION_BAR.NEGATIVE}`} />
              {p.status.degraded_sources.length} source{p.status.degraded_sources.length === 1 ? '' : 's'} degraded
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
