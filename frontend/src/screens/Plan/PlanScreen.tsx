import { useState } from 'react'
import { Masthead } from '@/components/shell/Masthead'
import { fetchPlanPayload, shirtUrl } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { Skel, SkelMasthead, SkelTable, ScreenError } from '@/components/shell/ScreenStates'
import { TransferWormhole } from '@/components/three/TransferWormhole'
import type { PlanPath } from '@/lib/types'

const TIE_COLOR: Record<string, string> = {
  CLEAR_LEAD: 'text-pitch-green',
  LIKELY_BEST: 'text-broadcast-gold',
  NEAR_TIE: 'text-alert-red',
}

/** Real strategy-rail connector: a filled arrowhead, not a bare rule line -
 * spec's "transfer arrows should actually behave like transfer arrows." */
function RailArrow() {
  return (
    <div className="my-auto flex w-8 shrink-0 items-center">
      <div className="h-[2px] flex-1 bg-divider" />
      <svg width="9" height="10" viewBox="0 0 9 10" className="shrink-0 fill-divider">
        <path d="M0 0 L9 5 L0 10 Z" />
      </svg>
    </div>
  )
}

/** THE STRATEGY GRID - real spatial path comparison, rows = ranked paths,
 * columns = the real union of gameweeks any shown path actually has a leg
 * for. Replaces a plain ranked list: comparing paths by which GW does what
 * is the actual planning question, not just "which number is bigger."
 * A cell with no step for that path/GW renders as an honest empty dash -
 * never a fabricated placeholder action. */
function StrategyGrid({ paths, activePath, onSelect }: { paths: PlanPath[]; activePath: number; onSelect: (idx: number) => void }) {
  const ranked = paths.slice().sort((a, b) => (b.score ?? -Infinity) - (a.score ?? -Infinity))
  const events = Array.from(new Set(paths.flatMap((pp) => pp.steps.map((s) => s.event)))).sort((a, b) => a - b)
  if (events.length === 0) return null

  return (
    <div className="overflow-x-auto">
      <div className="grid" style={{ gridTemplateColumns: `minmax(220px, auto) repeat(${events.length}, minmax(96px, 1fr)) auto` }}>
        {/* header row: GW axis */}
        <div />
        {events.map((e) => (
          <div key={e} className="border-b-2 border-divider px-2 pb-2 text-center text-[10px] font-bold uppercase tracking-wide text-text-faint">
            GW{e}
          </div>
        ))}
        <div className="border-b-2 border-divider" />

        {ranked.map((pp, rank) => {
          const active = pp.idx === activePath
          const leading = rank === 0
          const stepByEvent = new Map(pp.steps.map((s) => [s.event, s]))
          return (
            <div key={pp.idx} className="contents">
              <button
                onClick={() => onSelect(pp.idx)}
                className={`flex items-baseline gap-3 border-b border-divider py-3 pr-3 text-left ${active ? 'bg-panel' : 'hover:bg-panel/50'}`}
              >
                <span className={`font-display font-bold tabular ${leading ? 'text-2xl text-pitch-green' : 'text-base text-text-faint'}`}>
                  {String(rank + 1).padStart(2, '0')}
                </span>
                <span className={`truncate text-sm font-semibold ${active ? 'text-text' : 'text-text-muted'}`}>{pp.descriptor}</span>
              </button>
              {events.map((e) => {
                const s = stepByEvent.get(e)
                if (!s) return <div key={e} className={`border-b border-divider py-3 text-center text-text-faint ${active ? 'bg-panel' : ''}`}>&middot;</div>
                const isChip = s.chip_played !== null
                return (
                  <div
                    key={e}
                    className={`flex items-center justify-center border-b border-divider px-1 py-2 text-center ${active ? 'bg-panel' : ''}`}
                  >
                    <span
                      className={`w-full truncate px-1.5 py-1 text-[10px] font-bold uppercase leading-tight ${
                        s.is_locked
                          ? 'bg-pitch-green text-pitch-green-ink'
                          : isChip
                            ? 'border border-dashed border-broadcast-gold/60 text-broadcast-gold'
                            : 'text-text-muted'
                      }`}
                    >
                      {s.chip_played ?? s.action}
                    </span>
                  </div>
                )
              })}
              <button
                onClick={() => onSelect(pp.idx)}
                className={`border-b border-divider py-3 pl-3 text-right ${active ? 'bg-panel' : ''}`}
              >
                <span className={`tabular font-bold ${leading ? 'font-display text-xl text-pitch-green' : 'text-sm text-text-muted'}`}>
                  {pp.score?.toFixed(1) ?? '—'}
                </span>
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function StepRail({ path }: { path: PlanPath }) {
  return (
    <div className="flex items-stretch gap-0 overflow-x-auto pb-2">
      {path.steps.map((s, i) => {
        // Real visual weight split: a chip leg is a strategic event (gold),
        // a plain transfer/roll leg is routine (blue accent) - spec's
        // "important points should have different visual weight."
        const isChip = s.chip_played !== null
        // Real gap found 2026-09-12 (direct user report: "it says wildcard
        // but doesn't even show the fucking wildcard") - a chip step never
        // has a single player_out/player_in pair (it's not a 1-for-1 swap),
        // so with only the shirt-flip below there was nothing to show but
        // the bare chip name. `players_in`/`players_out` (a real diff of
        // this step's resulting squad against the one going into it) is
        // non-empty exactly for a genuine rebuild (wildcard) and empty for
        // a step that doesn't touch the squad (bench boost/triple captain).
        const hasSquadRebuild = !s.player_out && !s.player_in && (s.players_in.length > 0 || s.players_out.length > 0)
        return (
          <div key={i} className="flex items-stretch">
            <div
              className={`flex flex-col gap-1 px-5 py-4 ${hasSquadRebuild ? 'min-w-[260px]' : 'min-w-[150px]'} ${
                s.is_locked
                  ? 'border-t-2 border-white/40 bg-pitch-green text-pitch-green-ink'
                  : isChip
                    ? 'border-2 border-dashed border-broadcast-gold/60 bg-panel text-text'
                    : 'border-2 border-dashed border-divider bg-panel text-text-muted'
              }`}
            >
              <span className={`text-[10px] font-bold uppercase tracking-wide ${s.is_locked ? 'opacity-80' : isChip ? 'text-broadcast-gold' : 'opacity-70'}`}>
                GW{s.event}{s.is_locked ? ' · now' : ''}
              </span>
              <span className="font-display text-lg font-bold leading-tight">{s.chip_played ?? s.action}</span>
              {/* real out->in shirt swap (art-direction pass v3, direct user
                  follow-up: "more football" - a transfer leg used to be
                  pure text) - only renders when the payload resolved real
                  identity for both sides, never a placeholder shirt.
                  2026-09-10: upgraded to a real hover-driven CSS 3D flip
                  (`TransferWormhole`) instead of a static side-by-side pair -
                  the "3D" ask, scoped to real shirts on a real rotating
                  plane rather than an invented portal effect. */}
              {s.player_out && s.player_in && (
                <div className="mt-1 flex items-center gap-1.5">
                  <TransferWormhole
                    outShirt={s.player_out.team_code !== null ? shirtUrl(s.player_out.team_code, s.player_out.position === 'GKP', 66) : null}
                    inShirt={s.player_in.team_code !== null ? shirtUrl(s.player_in.team_code, s.player_in.position === 'GKP', 66) : null}
                    outName={s.player_out.name}
                    inName={s.player_in.name}
                  />
                  {/* Names stay visible without hovering - the flip is a
                      real bonus flourish, never the only way to read who's
                      actually moving. */}
                  <span className="truncate text-xs opacity-70">
                    {s.player_out.name} <span aria-hidden="true">&rarr;</span> {s.player_in.name}
                  </span>
                </div>
              )}
              {hasSquadRebuild && (
                <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                  <div className="min-w-0">
                    <div className="mb-0.5 text-[9px] font-bold uppercase tracking-wide opacity-60">
                      Out ({s.players_out.length})
                    </div>
                    <div className="space-y-0.5">
                      {s.players_out.map((p, pi) => (
                        <div key={pi} className="flex items-center gap-1 opacity-75">
                          {p.team_code !== null && (
                            <img src={shirtUrl(p.team_code, p.position === 'GKP', 44) ?? undefined} className="h-4 w-4 shrink-0 object-contain" alt="" />
                          )}
                          <span className="truncate">{p.name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="mb-0.5 text-[9px] font-bold uppercase tracking-wide opacity-60">
                      In ({s.players_in.length})
                    </div>
                    <div className="space-y-0.5">
                      {s.players_in.map((p, pi) => (
                        <div key={pi} className="flex items-center gap-1 font-semibold">
                          {p.team_code !== null && (
                            <img src={shirtUrl(p.team_code, p.position === 'GKP', 44) ?? undefined} className="h-4 w-4 shrink-0 object-contain" alt="" />
                          )}
                          <span className="truncate">{p.name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
              {s.gw_ev !== null && (
                <span className="tabular text-xs font-semibold opacity-90">
                  {s.gw_ev >= 0 ? '+' : ''}
                  {s.gw_ev.toFixed(1)} pts
                </span>
              )}
              {s.uses_hit && <span className="text-[10px] font-bold uppercase tracking-wide opacity-80">Takes a hit</span>}
            </div>
            {i < path.steps.length - 1 && <RailArrow />}
          </div>
        )
      })}
      {path.steps.length > 1 && (
        <>
          <RailArrow />
          <div className="flex min-w-[130px] flex-col justify-center px-4 py-4 text-[10px] font-bold uppercase tracking-wide text-text-faint">
            Re-evaluate — not locked in
          </div>
        </>
      )}
    </div>
  )
}

export function PlanScreen() {
  const state = useFetch(fetchPlanPayload, [], 60000)
  const [activePath, setActivePath] = useState(1)

  if (state.status === 'loading') {
    // Shaped like the strategy desk it precedes: headline path, then the
    // gameweek-by-path grid, then the selected-path step rail.
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="border-b-2 border-divider px-10 py-8">
          <Skel className="h-2 w-28" />
          <Skel className="mt-3 h-14 w-[22rem]" />
        </div>
        <div className="bg-panel px-10 py-8">
          <Skel className="h-2 w-28" />
          <div className="mt-5">
            <SkelTable rows={5} cols={7} />
          </div>
        </div>
        <div className="flex gap-3 px-10 py-8">
          {[0, 1, 2, 3, 4].map((i) => <Skel key={i} className="h-28 flex-1" />)}
        </div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="No strategy to show"
        description="The plan payload could not be fetched, so no path, sequence or chip timing is being shown. An empty desk here means the strategy is unknown right now, not that there is no move to make."
        message={state.error.message}
      />
    )
  }

  const p = state.data
  if (!p.has_plan) {
    return <div className="p-10 text-text-muted">{p.reason}</div>
  }

  const leader = p.leader!
  const current = p.paths?.find((pp) => pp.idx === activePath) ?? p.paths?.[0]

  return (
    <div className="data-in pb-16">
      <Masthead edition="Strategy Desk" title={`${p.horizon_gw}-gameweek plan`} />
      <div className="relative overflow-hidden px-10 pb-8 pt-7">
        <span className="ghost-watermark pointer-events-none absolute -top-8 right-2 select-none font-display text-[11rem] font-bold uppercase leading-none">
          PLAN
        </span>
        <div className="relative text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">
          {leader.already_played_chip ? 'Locked in this gameweek · leading follow-up plan' : `Leading strategy over ${p.horizon_gw} gameweeks`}
          {leader.tie && <span className={`ml-2 ${TIE_COLOR[leader.tie]}`}>{leader.tie.replace(/_/g, ' ')}</span>}
        </div>
        <div className="relative mt-1 font-display text-6xl font-bold uppercase text-text">{leader.descriptor}</div>
        <div className="relative mt-2 flex items-center gap-6">
          <span className="tabular text-3xl font-bold text-pitch-green">{leader.score?.toFixed(1)} pts</span>
          {leader.delta_vs_roll !== null && (
            <span className="text-sm text-text-muted">
              <strong className="tabular text-text">
                {leader.delta_vs_roll! >= 0 ? '+' : ''}
                {leader.delta_vs_roll!.toFixed(1)}
              </strong>{' '}
              vs rolling &middot; <strong className="text-text">{leader.confidence}</strong> confidence
            </span>
          )}
        </div>
      </div>

      {/* THE STRATEGY GRID - real spatial comparison across 2+ genuinely
          distinct paths. Real gap found 2026-09-12 (direct user report: the
          Plan screen "gives me a headache") - once only one path survives
          the reality-consistency filter (a chip is already played, so
          there is nothing left to compare), this grid was rendering the
          exact same 8-step sequence the hero headline and the step rail
          below it ALSO render, in a THIRD horizontally-scrolling format -
          three copies of one fact is the headache, not any one of them.
          Only worth its own real estate when there is an actual choice to
          compare. */}
      {p.paths && p.paths.length > 1 && (
        <div className="mt-8 bg-panel px-10 py-8">
          <div className="mb-5 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Strategy grid</div>
          <StrategyGrid paths={p.paths} activePath={activePath} onSelect={setActivePath} />
        </div>
      )}

      {/* DETAIL: the selected path's own real per-leg breakdown (shirts,
          hit-taken flags, per-GW EV). With only one real path this IS the
          plan, not a drill-down under a grid that no longer exists. */}
      {current && (
        <div className="mt-10 px-10">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">
            {p.paths && p.paths.length > 1 ? 'Selected path detail' : 'Path detail'}
          </div>
          <StepRail path={current} />
          <div className="mt-4 flex flex-wrap gap-x-8 gap-y-1 text-sm text-text-muted">
            <span>
              Final free transfers: <strong className="text-text">{current.final_free_transfers ?? '?'}</strong>
            </span>
            <span>
              Final bank: <strong className="text-text">£{current.final_bank_m.toFixed(1)}m</strong>
            </span>
          </div>
        </div>
      )}

      {/* HORIZON TOTALS - real per-horizon path totals for the selected path.
          Was a line chart plotting cumulative points; dropped 2026-09-12
          (direct user report: near-tied paths made it an unreadable
          overlapping mess) in favor of just the real numbers it was
          annotating anyway. */}
      {current?.horizon_breakdown && (
        <div className="mt-12 px-10">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Horizon totals</div>
          <div className="flex flex-wrap gap-10 border-t-2 border-divider pt-4">
            {Object.entries(current.horizon_breakdown).map(([h, entry]) => (
              <div key={h}>
                <div className="tabular font-display text-2xl font-bold text-text">{entry.path_total.toFixed(1)}</div>
                <div className="text-[11px] uppercase tracking-wide text-text-faint">at {h} gameweeks</div>
                {entry.delta_vs_roll !== null && (
                  <div className="tabular text-xs text-pitch-green">
                    {entry.delta_vs_roll >= 0 ? '+' : ''}
                    {entry.delta_vs_roll.toFixed(1)} vs roll
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* STRATEGY RISKS - a real gold-accented rail, matching the same
          risk-strip language My Team's own squad-risks strip already uses */}
      {p.sensitivity && p.sensitivity.length > 0 && (
        <div className="mt-12 border-t-2 border-divider bg-raised/40 px-10 py-8">
          <div className="mb-4 text-[11px] font-bold uppercase tracking-wide text-broadcast-gold">Strategy risks - what would flip this</div>
          <div className="space-y-3">
            {p.sensitivity.map((s) => (
              <div key={s.label} className="flex items-center gap-4 border-l-2 border-broadcast-gold/50 pl-3">
                <div className="w-64 shrink-0 truncate text-sm text-text-muted">{s.label}</div>
                <div className="h-2 flex-1 bg-panel">
                  <div className="bar-draw h-full bg-broadcast-gold" style={{ width: `${Math.min(s.pct, 100)}%` }} />
                </div>
                <div className="tabular w-14 text-right text-sm font-semibold text-text">~{s.pct}%</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
