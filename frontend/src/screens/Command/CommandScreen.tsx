import { Skeleton } from '@/components/ui/skeleton'
import { CaptainFaceOff } from '@/components/command/CaptainFaceOff'
import { ConfidenceGraphic } from '@/components/command/ConfidenceGraphic'
import { DecisionHero } from '@/components/command/DecisionHero'
import { DecisionHorizon } from '@/components/command/DecisionHorizon'
import { EvidenceRail } from '@/components/command/EvidenceRail'
import { PlayerGallery } from '@/components/command/PlayerGallery'
import { StrategyRail } from '@/components/command/StrategyRail'
import { fetchCommandPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** COMMAND — visual composition rebuild (2026-09-08, v4). Previous passes
 * fixed the information architecture and added real football texture, but
 * the page still read as a stack of equal-weight sections (eyebrow +
 * content + border-bottom, repeated eight times). This pass rebuilds the
 * SAME real payload into eight purpose-built compositions
 * (`components/command/*`), each using a genuinely different separation
 * technique (flat colour field, thick rule, or whitespace alone - see each
 * component's own docstring) so the page reads as one designed graphic
 * package rather than a scrolling list of cards. Zero new backend data;
 * every number here traces to the same `CommandPayload` fields the
 * previous version already rendered. */
export function CommandScreen() {
  const state = useFetch(fetchCommandPayload, [])

  if (state.status === 'loading') {
    return (
      <div className="space-y-4 p-10">
        <div className="font-mono text-[11px] uppercase tracking-[0.15em] text-text-faint">Loading the decision</div>
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
  const fragileCount =
    p.why.filter((w) => w.tag === 'FRAGILE').length + (p.trajectory?.future_legs.filter((l) => l.fragile_dependency).length ?? 0)

  return (
    <div className="pb-16">
      <DecisionHero
        gwLabel={p.gw.label}
        actionWord={p.action.word}
        alternative={p.alternative}
        why={p.why}
        freeTransfersValue={p.bar.free_transfers.value}
        bankM={p.bar.bank_m}
        chipsAvailable={p.bar.chips_available}
        checkpoint={p.checkpoint_table}
      />

      {p.action_squad && <PlayerGallery block={p.action_squad} />}

      {p.checkpoint_table && p.checkpoint_table.horizons.length > 0 && <DecisionHorizon checkpoint={p.checkpoint_table} />}

      {p.captain && <CaptainFaceOff block={p.captain} />}

      {p.trajectory && p.trajectory.future_legs.length > 0 && <StrategyRail trajectory={p.trajectory} monitor={p.monitor} />}

      <EvidenceRail rows={p.football_context} />

      <ConfidenceGraphic
        why={p.why}
        fragileCount={fragileCount}
        edge={p.edge}
        robustness={p.captain?.robustness ?? null}
        isStale={p.freshness?.is_stale ?? false}
        staleReason={p.freshness?.stale_reason ?? null}
        degradedSources={p.status.degraded_sources.length}
      />
    </div>
  )
}
