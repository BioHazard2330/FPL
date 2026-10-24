import { CaptainFaceOff } from '@/components/command/CaptainFaceOff'
import { DeadlineChecklist } from '@/components/command/DeadlineChecklist'
import { DeskStrip } from '@/components/command/DeskStrip'
import { CaptainLadder } from '@/components/command/CaptainLadder'
import { ConfidenceGraphic } from '@/components/command/ConfidenceGraphic'
import { DecisionHero } from '@/components/command/DecisionHero'
import { DecisionHorizon } from '@/components/command/DecisionHorizon'
import { EvidenceRail } from '@/components/command/EvidenceRail'
import { PlayerGallery } from '@/components/command/PlayerGallery'
import { StrategyRail } from '@/components/command/StrategyRail'
import { MarginalValue } from '@/components/command/MarginalValue'
import { RoadAhead } from '@/components/command/RoadAhead'
import { EyeTest } from '@/components/command/EyeTest'
import { DecisionSheet } from '@/components/command/DecisionSheet'
import { LiveStrip } from '@/components/command/LiveStrip'
import { MoveCard } from '@/components/command/MoveCard'
import { SeasonRibbon } from '@/components/command/SeasonRibbon'
import { SquadPitch } from '@/components/command/SquadPitch'
import { Panel } from '@/components/ui/kit'
import { fetchCommandPayload, fetchDeskPayload, fetchWeekPlanPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { useLiveMeta } from '@/lib/useLiveMeta'
import { derivePhase, PHASES, useCountdown } from '@/lib/clock'
import type { Phase } from '@/lib/clock'
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

type SectionKey =
  | 'decision' | 'value' | 'lineup' | 'record' | 'squad' | 'horizon' | 'captain' | 'strategy' | 'evidence' | 'confidence' | 'later' | 'desk' | 'checklist' | 'field'

/** Two real orders, one per answerable question.
 *
 * ACTIONABLE - "what should I do?" The argument runs decision -> the XI it
 * produces -> how the edge holds over the horizon -> the captaincy call ->
 * the path after it -> the football behind it -> how much to trust it.
 *
 * LOCKED / LIVE - "what have I got?" Nothing can be changed, so the squad
 * leads, the captain (who is on the pitch right now) comes straight after,
 * and the decision drops to where it belongs: a record, read last. */
const ACTIONABLE_ORDER: SectionKey[] = [
  'decision', 'checklist', 'field', 'value', 'lineup', 'record', 'squad', 'horizon', 'captain', 'strategy', 'later', 'desk', 'evidence', 'confidence',
]
const LOCKED_ORDER: SectionKey[] = [
  'squad', 'captain', 'desk', 'evidence', 'lineup', 'decision', 'value', 'record', 'horizon', 'strategy', 'later', 'confidence',
]

function orderSections(nodes: Record<SectionKey, React.ReactNode>, actionable: boolean) {
  const order = actionable ? ACTIONABLE_ORDER : LOCKED_ORDER
  return order.filter((k) => nodes[k] !== null && nodes[k] !== undefined).map((k) => ({ key: k, node: nodes[k] }))
}

export function CommandScreen() {
  const state = useFetch(fetchCommandPayload, [], 60000)
  const planState = useFetch(fetchWeekPlanPayload, [], 60000)
  const deskState = useFetch(fetchDeskPayload, [], 300000)
  const desk = deskState.status === 'ready' ? deskState.data : null
  const live = useLiveMeta()
  const countdown = useCountdown(live?.gw?.next_deadline_time)

  const plan = planState.status === 'ready' && planState.data.status !== 'none' ? planState.data : null

  if (state.status === 'loading' && !plan) {
    // Shaped like the decision field it precedes: masthead, giant action
    // headline, the comparison axis, then the XI gallery.
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="border-b border-divider px-10 py-8">
          <Skel className="h-2 w-32" />
          <Skel className="mt-3 h-20 w-[26rem]" />
          <Skel className="mt-4 h-4 w-[34rem]" />
          <div className="mt-8 space-y-3">
            <Skel className="h-6 w-full" />
            <Skel className="h-6 w-4/5" />
          </div>
        </div>
        <div className="flex gap-4 border-b border-divider px-10 py-8">
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
  if (state.status === 'error' && !plan) {
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

  const p = state.status === 'ready' ? state.data : null
  // Development only: ?phase=IMMINENT (or BUILD_UP, FINAL_CALL, REVIEW) renders the screen as it reads before a deadline.
  const forced = import.meta.env.DEV ? new URLSearchParams(window.location.search).get('phase') : null
  const derived = derivePhase(live?.gw?.state, countdown?.totalMs ?? null, live?.active_matches?.length ?? 0)
  const phase = forced && forced in PHASES ? { phase: forced as Phase, ...PHASES[forced as Phase] } : derived
  const fragileCount = p
    ? p.why.filter((w) => w.tag === 'FRAGILE').length + (p.trajectory?.future_legs.filter((l) => l.fragile_dependency).length ?? 0)
    : 0
  const pending = <Skel className="m-10 h-40" />

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
  const planNodes: Partial<Record<SectionKey, React.ReactNode>> = {}

  const legacyNodes: Partial<Record<SectionKey, React.ReactNode>> = p && !plan
    ? {
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
          p.checkpoint_table && p.checkpoint_table.horizons.length > 0 ? <DecisionHorizon checkpoint={p.checkpoint_table} /> : null,
        captain: p.captain ? <CaptainFaceOff block={p.captain} fixtures={p.fixtures} /> : null,
        strategy:
          p.trajectory && p.trajectory.future_legs.length > 0 ? <StrategyRail trajectory={p.trajectory} monitor={p.monitor} /> : null,
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
      }
    : {}

  if (plan) {
    const moves = plan.moves ?? []
    return (
      <div className="data-in">
        {live?.gw?.state === 'LIVE' || (live?.active_matches?.length ?? 0) > 0 ? <LiveStrip /> : null}
        <DecisionSheet plan={plan} chips={p?.bar.chips_available ?? []} />
        <div className="bare grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          {plan.action_squad && <SquadPitch block={plan.action_squad} fixtures={plan.fixtures} title={`Your GW${plan.event} team`} sub={moves.length > 0 ? 'After the moves above, with the armband set.' : 'As it stands, with the armband set.'} />}
          <div className="space-y-6">
            {moves.length > 0 && (
              <Panel title={moves.length === 1 ? 'The transfer, in detail' : 'The transfers, in detail'} sub={`Why each move earns its points over ${plan.horizon ?? 5} gameweeks.`}>
                <div className="space-y-4">
                  {moves.map((m) => (
                    <MoveCard key={m.into.player_id} m={m} horizon={plan.horizon ?? 5} fixtures={plan.fixtures} startEvent={plan.event ?? 0} />
                  ))}
                  {(plan.declined ?? []).map((m) => (
                    <p key={m.into.player_id} className="text-[13px] text-text-muted">
                      <span className="font-semibold text-text">Left out:</span> {m.out.name} &rarr; {m.into.name} adds {m.gain >= 0 ? '+' : ''}
                      {m.gain.toFixed(1)} over {plan.horizon} GW, under the {plan.min_move_gain} a move has to earn.
                    </p>
                  ))}
                </div>
              </Panel>
            )}
            <MarginalValue plan={plan} />
          </div>
        </div>
        <SeasonRibbon />
        <EyeTest plan={plan} />
        <CaptainLadder plan={plan} />
        <DeadlineChecklist plan={plan} desk={desk} />
        <RoadAhead plan={plan} compact />
        <DeskStrip desk={desk} />
      </div>
    )
  }

  const sections = orderSections(
    {
      decision: null,
      value: null,
      lineup: null,
      later: null,
      record: null,
      squad: null,
      horizon: null,
      captain: null,
      strategy: null,
      evidence: p ? <EvidenceRail rows={p.football_context} /> : pending,
      confidence: null,
      ...legacyNodes,
      ...planNodes,
    } as Record<SectionKey, React.ReactNode>,
    phase.actionable,
  )

  return (
    <div className="data-in pb-16">
      {sections.map((s) => (
        <div key={s.key}>{s.node}</div>
      ))}
    </div>
  )
}
