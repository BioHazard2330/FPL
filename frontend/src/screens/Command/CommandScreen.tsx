import { CaptainFaceOff } from '@/components/command/CaptainFaceOff'
import { ConfidenceGraphic } from '@/components/command/ConfidenceGraphic'
import { DecisionHero } from '@/components/command/DecisionHero'
import { DecisionHorizon } from '@/components/command/DecisionHorizon'
import { EvidenceRail } from '@/components/command/EvidenceRail'
import { PlayerGallery } from '@/components/command/PlayerGallery'
import { StrategyRail } from '@/components/command/StrategyRail'
import { fetchCommandPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { useLiveMeta } from '@/lib/useLiveMeta'
import { derivePhase, useCountdown } from '@/lib/clock'
import { Skel, SkelMasthead, SkelRail, ScreenError } from '@/components/shell/ScreenStates'

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

type SectionKey = 'decision' | 'squad' | 'horizon' | 'captain' | 'strategy' | 'evidence' | 'confidence'

/** Two real orders, one per answerable question.
 *
 * ACTIONABLE - "what should I do?" The argument runs decision -> the XI it
 * produces -> how the edge holds over the horizon -> the captaincy call ->
 * the path after it -> the football behind it -> how much to trust it.
 *
 * LOCKED / LIVE - "what have I got?" Nothing can be changed, so the squad
 * leads, the captain (who is on the pitch right now) comes straight after,
 * and the decision drops to where it belongs: a record, read last. */
const ACTIONABLE_ORDER: SectionKey[] = ['decision', 'squad', 'horizon', 'captain', 'strategy', 'evidence', 'confidence']
const LOCKED_ORDER: SectionKey[] = ['squad', 'captain', 'evidence', 'decision', 'horizon', 'strategy', 'confidence']

function orderSections(nodes: Record<SectionKey, React.ReactNode>, actionable: boolean) {
  const order = actionable ? ACTIONABLE_ORDER : LOCKED_ORDER
  return order.filter((k) => nodes[k] !== null && nodes[k] !== undefined).map((k) => ({ key: k, node: nodes[k] }))
}

export function CommandScreen() {
  const state = useFetch(fetchCommandPayload, [], 60000)
  const live = useLiveMeta()
  const countdown = useCountdown(live?.gw?.next_deadline_time)

  if (state.status === 'loading') {
    // Shaped like the decision field it precedes: masthead, giant action
    // headline, the comparison axis, then the XI gallery.
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="border-b-2 border-divider px-10 py-8">
          <Skel className="h-2 w-32" />
          <Skel className="mt-3 h-20 w-[26rem]" />
          <Skel className="mt-4 h-4 w-[34rem]" />
          <div className="mt-8 space-y-3">
            <Skel className="h-6 w-full" />
            <Skel className="h-6 w-4/5" />
          </div>
        </div>
        <div className="flex gap-4 border-b-2 border-divider px-10 py-8">
          {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => (
            <Skel key={i} className="h-24 flex-1" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-px bg-divider lg:grid-cols-2">
          {[0, 1].map((i) => (
            <div key={i} className="bg-void px-10 py-8">
              <Skel className="h-2 w-28" />
              <SkelRail rows={5} className="mt-4" />
            </div>
          ))}
        </div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="No decision to show"
        description={
          <>
            The command payload could not be fetched, so there is no recommendation on this screen &mdash; not a cached one,
            not a default one. If the backend is down, check that <code className="font-mono text-text">fpl live-server</code>{' '}
            is running.
          </>
        }
        message={state.error.message}
      />
    )
  }

  const p = state.data
  const phase = derivePhase(live?.gw?.state, countdown?.totalMs ?? null, live?.active_matches?.length ?? 0)
  const fragileCount =
    p.why.filter((w) => w.tag === 'FRAGILE').length + (p.trajectory?.future_legs.filter((l) => l.fragile_dependency).length ?? 0)

  // THE SECTION ORDER IS THE PRODUCT.
  //
  // Command used to render one fixed sequence regardless of what time it was
  // in the football week - the same "PLAY FREE HIT" hero at the top whether
  // the deadline was three days away or the matches had already kicked off
  // and the squad could not be changed at all. That is not a layout problem,
  // it is the screen telling the user to do something impossible.
  //
  // The real `models/gw_lifecycle.py` state (plus the real deadline) decides
  // which question leads. When the squad can still change, the decision
  // leads. Once it is locked or live, the XI you are actually fielding leads
  // and the decision recedes to a record of what was chosen. Same sections,
  // same data, re-ranked by what the user can actually do about it.
  const sections = orderSections(
    {
      decision: (
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
      ),
      squad: p.action_squad ? <PlayerGallery block={p.action_squad} fixtures={p.fixtures} /> : null,
      horizon:
        p.checkpoint_table && p.checkpoint_table.horizons.length > 0 ? (
          <DecisionHorizon checkpoint={p.checkpoint_table} />
        ) : null,
      captain: p.captain ? <CaptainFaceOff block={p.captain} fixtures={p.fixtures} /> : null,
      strategy:
        p.trajectory && p.trajectory.future_legs.length > 0 ? (
          <StrategyRail trajectory={p.trajectory} monitor={p.monitor} />
        ) : null,
      evidence: <EvidenceRail rows={p.football_context} />,
      confidence: (
        <ConfidenceGraphic
          why={p.why}
          fragileCount={fragileCount}
          edge={p.edge}
          robustness={p.captain?.robustness ?? null}
          isStale={p.freshness?.is_stale ?? false}
          staleReason={p.freshness?.stale_reason ?? null}
          degradedSources={p.status.degraded_sources.length}
        />
      ),
    },
    phase.actionable,
  )

  return (
    <div className="data-in pb-16">
      {/* PHASE BANNER - the one thing Command has to say before anything
          else once the squad is locked: the decision below is history, not
          an instruction. Rendering the same "do this" hero during a live
          match was the app's single most misleading moment. */}
      {!phase.actionable && (
        <div className={`flex flex-wrap items-baseline gap-x-4 gap-y-1 px-10 py-3 ${phase.fill}`}>
          <span className="font-display text-sm font-bold uppercase tracking-[0.16em]">
            {phase.live ? 'Matches are live' : 'Squad locked'}
          </span>
          <span className="text-[11px] opacity-80">
            {phase.live
              ? 'Nothing below can be acted on until the gameweek settles. This is what you are fielding.'
              : 'Transfers and the armband are closed for this gameweek. The decision below is the record of what was chosen.'}
          </span>
        </div>
      )}

      {sections.map((s) => (
        <div key={s.key}>{s.node}</div>
      ))}
    </div>
  )
}
