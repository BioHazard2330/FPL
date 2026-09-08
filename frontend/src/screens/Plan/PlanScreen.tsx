import { useState } from 'react'
import Chart from 'react-apexcharts'
import { Skeleton } from '@/components/ui/skeleton'
import { Masthead } from '@/components/shell/Masthead'
import { fetchPlanPayload, shirtUrl } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
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

function StepRail({ path }: { path: PlanPath }) {
  return (
    <div className="flex items-stretch gap-0 overflow-x-auto pb-2">
      {path.steps.map((s, i) => {
        // Real visual weight split: a chip leg is a strategic event (gold),
        // a plain transfer/roll leg is routine (blue accent) - spec's
        // "important points should have different visual weight."
        const isChip = s.chip_played !== null
        return (
          <div key={i} className="flex items-stretch">
            <div
              className={`flex min-w-[150px] flex-col gap-1 px-5 py-4 ${
                s.is_locked
                  ? 'border-t-2 border-white/40 bg-pitch-green text-pitch-green-ink shadow-[0_16px_28px_-12px_rgba(31,206,107,0.55)]'
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
                  identity for both sides, never a placeholder shirt */}
              {s.player_out && s.player_in && (
                <div className="mt-1 flex items-center gap-1.5">
                  {s.player_out.team_code !== null && (
                    <img
                      src={shirtUrl(s.player_out.team_code, s.player_out.position === 'GKP', 66) ?? undefined}
                      alt=""
                      className="h-6 w-6 object-contain opacity-50 grayscale"
                    />
                  )}
                  <span className="text-xs opacity-70">&rarr;</span>
                  {s.player_in.team_code !== null && (
                    <img
                      src={shirtUrl(s.player_in.team_code, s.player_in.position === 'GKP', 66) ?? undefined}
                      alt=""
                      className="h-6 w-6 object-contain"
                    />
                  )}
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
  const state = useFetch(fetchPlanPayload, [])
  const [activePath, setActivePath] = useState(1)

  if (state.status === 'loading') {
    return (
      <div className="space-y-3 p-10">
        <div className="font-mono text-[11px] uppercase tracking-[0.15em] text-text-faint">Loading strategy</div>
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (state.status === 'error') {
    return <div className="bg-alert-red p-6 font-semibold text-alert-red-ink">Can't reach the backend ({state.error.message}).</div>
  }

  const p = state.data
  if (!p.has_plan) {
    return <div className="p-10 text-text-muted">{p.reason}</div>
  }

  const leader = p.leader!
  const current = p.paths?.find((pp) => pp.idx === activePath) ?? p.paths?.[0]

  const series = (p.trajectory_series ?? []).map((s) => ({ name: s.name, data: s.points.map((pt) => [pt.x, pt.y]) }))
  const chartOptions = {
    chart: { type: 'line' as const, toolbar: { show: false }, background: 'transparent', foreColor: 'var(--text-muted)' },
    stroke: { width: (p.trajectory_series ?? []).map((s) => (s.role === 'leading' ? 4 : 2)), curve: 'straight' as const },
    colors: (p.trajectory_series ?? []).map((s) => (s.role === 'leading' ? 'var(--pitch-green)' : 'var(--divider)')),
    grid: { borderColor: 'var(--divider)' },
    xaxis: { type: 'numeric' as const, title: { text: 'Gameweek' }, tickAmount: (p.horizon_gw ?? 8) - 3 },
    yaxis: { title: { text: 'Cumulative pts' } },
    legend: { show: false },
    dataLabels: { enabled: false },
  }

  return (
    <div className="pb-16">
      <Masthead edition="Strategy Desk" title={`${p.horizon_gw}-gameweek plan`} />
      <div className="relative overflow-hidden px-10 pb-8 pt-7">
        <span className="ghost-watermark pointer-events-none absolute -top-8 right-2 select-none font-display text-[11rem] font-bold uppercase leading-none">
          PLAN
        </span>
        <div className="relative text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">
          Leading strategy over {p.horizon_gw} gameweeks
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

      {/* DOMINANT MODULE: the strategy timeline for the selected path */}
      {current && (
        <div className="mt-8 px-10">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Strategy path</div>
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

      {/* PATH COMPARISON: real ranking, not a bar chart - the leader dominates typographically */}
      {p.paths && p.paths.length > 0 && (
        <div className="mt-10 border-t-2 border-divider px-10 pt-6">
          <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Path comparison</div>
          <div className="divide-y divide-divider">
            {p.paths
              .slice()
              .sort((a, b) => (b.score ?? -Infinity) - (a.score ?? -Infinity))
              .map((pp, rank) => {
                const active = pp.idx === activePath
                const leading = rank === 0
                return (
                  <button
                    key={pp.idx}
                    onClick={() => setActivePath(pp.idx)}
                    className={`flex w-full items-baseline gap-5 py-4 text-left transition-colors ${leading ? 'bg-panel px-4' : 'px-4 hover:bg-panel/40'}`}
                  >
                    <span
                      className={`font-display shrink-0 font-bold tabular ${leading ? 'text-5xl text-pitch-green' : 'text-2xl text-text-faint'}`}
                    >
                      {String(rank + 1).padStart(2, '0')}
                    </span>
                    <span className={`flex-1 truncate ${leading ? 'font-display text-2xl font-bold text-text' : 'text-sm font-semibold text-text-muted'} ${active && !leading ? 'text-text' : ''}`}>
                      {pp.descriptor}
                    </span>
                    <span className={`tabular shrink-0 font-bold ${leading ? 'text-3xl text-pitch-green' : 'text-base text-text-muted'}`}>
                      {pp.score?.toFixed(1) ?? '—'}
                    </span>
                    <span className="w-24 shrink-0 text-right text-[10px] uppercase tracking-wide text-text-faint">{pp.confidence}</span>
                  </button>
                )
              })}
          </div>
        </div>
      )}

      {/* CUMULATIVE EDGE */}
      {series.length > 0 && (
        <div className="mt-10 border-t-2 border-divider px-10 pt-6">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Cumulative edge</div>
          <Chart options={chartOptions} series={series} type="line" height={300} />
        </div>
      )}

      {current?.horizon_breakdown && (
        <div className="flex gap-8 border-t-2 border-divider px-10 pt-6">
          {Object.entries(current.horizon_breakdown).map(([h, entry]) => (
            <div key={h}>
              <div className="tabular text-lg font-bold text-text">{entry.path_total.toFixed(1)}</div>
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
      )}

      {/* STRATEGY RISKS */}
      {p.sensitivity && p.sensitivity.length > 0 && (
        <div className="mt-10 border-t-2 border-divider px-10 pt-6">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Strategy risks</div>
          <div className="space-y-2">
            {p.sensitivity.map((s) => (
              <div key={s.label} className="flex items-center gap-4">
                <div className="w-64 shrink-0 truncate text-sm text-text-muted">{s.label}</div>
                <div className="h-2 flex-1 bg-raised">
                  <div className="h-full bg-broadcast-gold" style={{ width: `${Math.min(s.pct, 100)}%` }} />
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
