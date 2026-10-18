import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, ScreenError } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { EdgeDensity } from '@/components/charts/EdgeDensity'
import { fetchFieldPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { EdgeStats, FieldPayload } from '@/lib/types'

/** THE FIELD - this week measured against everyone else.
 *
 * Projections say how many points a decision is worth. Rank moves on points
 * relative to the other managers, and a player the field already owns and
 * captains is worth less to you than his points suggest. This page draws four
 * thousand gameweeks from the same correlated match simulation the projections
 * use, scores you and the average manager on each, and reports the gap: its
 * mean, how often you beat the field, and how wide the spread is. It also names
 * the players the field holds that you do not, which is where a rank is lost
 * without a single bad decision.
 *
 * All figures are in the model's own points. The model runs cool: its past
 * predictions for your players have come in below what they scored (the
 * payload carries the measured shortfall). The edge is a gap between two sums of
 * the same number of slots, so a shortfall that is similar per player cancels in
 * it; the "pts" column does not, and is not a forecast of your score. */

const pct = (p: number) => `${Math.round(p * 100)}%`
const sign = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`

function Stat({ label, value, sub, tone = 'text-text' }: { label: string; value: React.ReactNode; sub?: string; tone?: string }) {
  return (
    <div>
      <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">{label}</div>
      <div className={`tabular mt-0.5 font-display text-4xl font-bold leading-none ${tone}`}>{value}</div>
      {sub && <div className="mt-1 text-[13px] text-text-faint">{sub}</div>}
    </div>
  )
}

function EdgeRow({ label, e, mean, highlight }: { label: React.ReactNode; e: EdgeStats; mean?: number; highlight?: boolean }) {
  return (
    <div className={`grid grid-cols-[minmax(0,1fr)_4rem_4.5rem_4.5rem_4.5rem_4.5rem] items-center gap-3 border-b border-divider py-2 text-sm ${highlight ? 'bg-panel' : ''}`}>
      <div className="min-w-0 truncate pl-2 font-semibold text-text">{label}</div>
      <div className="tabular text-right text-text-muted">{mean !== undefined ? mean.toFixed(1) : ''}</div>
      <div className={`tabular text-right font-bold ${e.mean >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{sign(e.mean)}</div>
      <div className="tabular text-right text-text">{pct(e.p_beat)}</div>
      <div className="tabular text-right text-text-muted">{sign(e.p90, 0)}</div>
      <div className="tabular pr-2 text-right text-text-muted">{pct(e.big_win)} / {pct(e.big_loss)}</div>
    </div>
  )
}

function Header() {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_4rem_4.5rem_4.5rem_4.5rem_4.5rem] gap-3 border-b border-divider py-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-text-faint">
      <div className="pl-2" />
      <div className="text-right">pts</div>
      <div className="text-right">edge</div>
      <div className="text-right">beat field</div>
      <div className="text-right">top 10%</div>
      <div className="pr-2 text-right">+12 / −12</div>
    </div>
  )
}

function Body({ d }: { d: FieldPayload }) {
  const options = d.options ?? []
  const captains = d.captains ?? []
  const plan = d.plan_option!
  const axis = d.axis!
  const colors: Record<string, string> = { as_set: 'var(--text-faint)', roll: 'var(--broadcast-blue)', plan: 'var(--pitch-green)' }
  const dens = options.filter((o) => ['as_set', 'roll', 'plan'].includes(o.key)).map((o) => ({ key: o.key, label: o.label, hist: o.edge.hist, color: colors[o.key] }))
  const chosen = captains.find((c) => c.chosen)
  const best = captains.find((c) => c.player_id === d.best_captain_id)
  const upside = captains.find((c) => c.player_id === d.upside_captain_id)
  const roll = options.find((o) => o.key === 'roll')
  const asSet = options.find((o) => o.key === 'as_set')
  const posture = d.posture
  const rest = captains.slice().sort((a, b) => b.edge.mean - a.edge.mean).slice(0, 7)

  return (
    <>
      <section className="border-b border-divider px-10 py-8">
        <div className="grid grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] gap-12">
          <div>
            <div className="mb-3 font-mono text-[12px] uppercase tracking-[0.1em] text-text-faint">GW{d.event} · the plan against the average manager</div>
            <div className="flex flex-wrap gap-x-10 gap-y-4">
              <Stat label="Edge" value={sign(plan.edge.mean)} sub="points over the field, on average" tone="text-pitch-green" />
              <Stat label="Beat the field" value={pct(plan.edge.p_beat)} sub="of simulated gameweeks" />
              <Stat label="Percentile" value={pct(plan.edge.percentile)} sub="of managers, on a typical week" />
            </div>
            <p className="mt-5 max-w-xl text-sm leading-relaxed text-text-muted">
              {asSet && roll && (
                <>
                  Setting your best eleven is worth {sign(roll.edge.mean - asSet.edge.mean)} on its own; the transfers add a further {sign(plan.edge.mean - roll.edge.mean)}.{' '}
                </>
              )}
              There is a {pct(plan.edge.big_win)} chance of finishing 12 or more points clear of the field and a {pct(plan.edge.big_loss)} chance of falling 12 or more behind.
              {posture && (
                <>
                  {' '}You are {posture.overall_rank.toLocaleString()} of {posture.total_players.toLocaleString()} (top {(posture.percentile * 100).toFixed(1)}%), so you are chasing:
                  a steady edge compounds over the 31 gameweeks left, and variance only helps if it comes free.
                </>
              )}
            </p>
          </div>
          <div>
            <EdgeDensity series={dens} min={axis.min} max={axis.max} />
            <div className="mt-2 flex flex-wrap gap-4 text-[13px] text-text-muted">
              {dens.map((s) => (
                <span key={s.key} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5" style={{ background: s.color }} />{s.label}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="border-b border-divider px-10 py-7">
        <h2 className="mb-3 font-display text-2xl font-bold uppercase tracking-wide text-text">Versions of your week</h2>
        <Header />
        {options.map((o) => <EdgeRow key={o.key} label={o.label} e={o.edge} mean={o.mean_points} highlight={o.key === 'plan'} />)}
        {d.model_bias && (
          <p className="mt-3 max-w-3xl border-l-4 border-broadcast-gold bg-panel px-4 py-2 text-xs leading-relaxed text-text-muted">
            The model runs cool: across {d.model_bias.n} of its past predictions for your players they scored {d.model_bias.bias_per_player.toFixed(1)} points
            (plus or minus {d.model_bias.standard_error.toFixed(1)}) more than predicted. That applies to the field's players too, so the edge, a gap
            between equal numbers of slots, is mostly unaffected. The pts column is not: add roughly {(d.model_bias.bias_per_player * 12).toFixed(0)} for what a team like this tends to score.
          </p>
        )}
        <p className="mt-2 text-[13px] text-text-faint">
          pts: your simulated score. edge: your score minus the field's average, same trial. top 10%: the edge you clear in your best tenth of weeks. +12 / −12: chance of ending at least that far clear of, or behind, the field.
        </p>
      </section>

      <section className="border-b border-divider px-10 py-7">
        <div className="mb-1 flex flex-wrap items-baseline justify-between gap-4">
          <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-text">Who wears the armband</h2>
          {best && upside && (
            <span className="text-xs text-text-muted">
              Best edge: <span className="font-bold text-text">{best.name}</span>
              {upside.player_id !== best.player_id && <> · best upside within half a point: <span className="font-bold text-text">{upside.name}</span></>}
            </span>
          )}
        </div>
        <p className="mb-3 max-w-3xl text-xs text-text-muted">
          Captain share is how often the sampled top managers captain him; field EO is the average multiplier the field gives him. A captain the field also captains costs you rank when he scores and you did not back him, and gains you almost none when he does.
        </p>
        <div className="grid grid-cols-[2.2rem_minmax(0,1fr)_4.5rem_4.5rem_4rem_4.5rem_4.5rem_4.5rem] items-center gap-3 border-b border-divider py-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-text-faint">
          <div /><div />
          <div className="text-right">field cap</div><div className="text-right">field EO</div><div className="text-right">pts</div><div className="text-right">edge</div><div className="text-right">beat field</div><div className="text-right">top 10%</div>
        </div>
        {rest.map((c) => (
          <div key={c.player_id} className={`grid grid-cols-[2.2rem_minmax(0,1fr)_4.5rem_4.5rem_4rem_4.5rem_4.5rem_4.5rem] items-center gap-3 border-b border-divider py-2 text-sm ${c.chosen ? 'bg-panel' : ''}`}>
            <PlayerPhoto code={c.photo_code} teamCode={c.team_code} isGkp={c.position === 'GKP'} className="h-9 w-7" />
            <div className="min-w-0">
              <Link to={`/player/${c.player_id}`} className="font-bold text-text hover:text-pitch-green">{c.name}</Link>
              <span className="ml-2 font-mono text-[12px] uppercase text-text-faint">{c.team_short}</span>
              {c.chosen && <span className="ml-2 bg-broadcast-gold px-1 text-[11px] font-bold uppercase leading-4 text-broadcast-gold-ink">plan's pick</span>}
            </div>
            <div className="tabular text-right text-text-muted">{pct(c.captain_share)}</div>
            <div className="tabular text-right text-text-muted">{c.field_eo.toFixed(2)}</div>
            <div className="tabular text-right text-text-muted">{c.mean_points?.toFixed(1) ?? '—'}</div>
            <div className={`tabular text-right font-bold ${c.edge.mean >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{sign(c.edge.mean)}</div>
            <div className="tabular text-right text-text">{pct(c.edge.p_beat)}</div>
            <div className="tabular text-right text-text-muted">{sign(c.edge.p90, 0)}</div>
          </div>
        ))}
        {chosen && best && chosen.player_id !== best.player_id && (
          <p className="mt-2 text-xs text-alert-red">The plan's captain is not the best edge on this field.</p>
        )}
      </section>

      <section className="grid grid-cols-2 gap-12 px-10 py-7">
        <div>
          <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-text">What the field has that you do not</h2>
          <p className="mb-3 mt-1 text-xs text-text-muted">Players with the most field ownership times expected points that are not in your squad. Each is a way to lose rank to a week you played correctly.</p>
          {(d.threats ?? []).map((t) => (
            <div key={t.player_id} className="grid grid-cols-[2.2rem_minmax(0,1fr)_4rem_4rem_4rem] items-center gap-3 border-b border-divider py-2 text-sm">
              <PlayerPhoto code={t.photo_code} teamCode={t.team_code} isGkp={t.position === 'GKP'} className="h-9 w-7" />
              <div className="min-w-0"><Link to={`/player/${t.player_id}`} className="font-bold text-text hover:text-pitch-green">{t.name}</Link><span className="ml-2 font-mono text-[12px] uppercase text-text-faint">{t.team_short} · {t.position}</span></div>
              <div className="tabular text-right text-text-muted" title="average multiplier across the field">{t.field_eo.toFixed(2)}</div>
              <div className="tabular text-right text-text-muted" title="chance of 8+ points">{pct(t.p_haul)} haul</div>
              <div className="tabular text-right font-bold text-alert-red" title="field ownership times expected points">−{t.cost.toFixed(1)}</div>
            </div>
          ))}
        </div>
        <div>
          <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-text">Where your edge comes from</h2>
          <p className="mb-3 mt-1 text-xs text-text-muted">For each starter: his expected points times (your multiplier minus the field's). Low or negative means you are only matching the field there.</p>
          {(d.contributions ?? []).map((c) => (
            <div key={c.player_id} className="grid grid-cols-[minmax(0,1fr)_4rem_9rem_3.5rem] items-center gap-3 border-b border-divider py-2 text-sm">
              <div className="min-w-0"><Link to={`/player/${c.player_id}`} className="font-bold text-text hover:text-pitch-green">{c.name}</Link>{c.you === 2 && <span className="ml-2 bg-broadcast-gold px-1 text-[11px] font-bold uppercase leading-4 text-broadcast-gold-ink">C</span>}</div>
              <div className="tabular text-right text-text-faint">EO {c.field_eo.toFixed(2)}</div>
              <div className="relative h-2.5 bg-raised"><div className={`h-full ${c.edge >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`} style={{ width: `${Math.min(100, (Math.abs(c.edge) / 7) * 100)}%` }} /></div>
              <div className={`tabular text-right font-bold ${c.edge >= 0 ? 'text-text' : 'text-alert-red'}`}>{sign(c.edge)}</div>
            </div>
          ))}
        </div>
      </section>
    </>
  )
}

export function FieldScreen() {
  const [kind, setKind] = useState<'population' | 'top10k'>('population')
  const state = useFetch(() => fetchFieldPayload(kind), [kind])

  return (
    <div className="data-in pb-16">
      <Masthead
        edition="The Field"
        title="This week against everyone else"
        right={state.status === 'ready' && state.data.field ? <span className="text-text-muted">{state.data.n_trials?.toLocaleString()} simulated gameweeks · {pct(state.data.field.coverage)} of ownership covered</span> : undefined}
      />
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-divider px-10 py-3">
        <span className="font-mono text-[12px] uppercase tracking-[0.1em] text-text-faint">The field is</span>
        {(['population', 'top10k'] as const).map((k) => (
          <button key={k} type="button" onClick={() => setKind(k)} className={`px-2.5 py-1 text-[13px] font-semibold uppercase tracking-[0.05em] ${kind === k ? 'bg-text text-void' : 'bg-raised text-text-muted hover:text-text'}`}>
            {k === 'population' ? 'Everyone' : 'Top 10,000'}
          </button>
        ))}
        {state.status === 'ready' && state.data.field && <span className="text-[13px] text-text-faint">{state.data.field.label}</span>}
      </div>

      {state.status === 'loading' && (
        <div className="animate-pulse px-10 py-8">
          <Skel className="h-48 w-full" />
          <Skel className="mt-6 h-64 w-full" />
        </div>
      )}
      {state.status === 'error' && <ScreenError title="The field is unavailable" description="The simulation could not be built, so no edge is shown." message={state.error.message} />}
      {state.status === 'ready' && state.data.status === 'no_plan' && <p className="px-10 py-8 text-sm text-text-muted">There is no week plan yet to measure.</p>}
      {state.status === 'ready' && state.data.status === 'no_sample' && <p className="px-10 py-8 text-sm text-text-muted">{state.data.detail}. Run <span className="font-mono">fpl sync-eo --event N</span> after a gameweek locks.</p>}
      {state.status === 'ready' && state.data.status === 'ok' && <Body d={state.data} />}
    </div>
  )
}
