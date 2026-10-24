import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchViewPlan } from '@/lib/api'
import { Panel, Pill } from '@/components/ui/kit'
import type { FormReading, ViewPlanPayload, WeekPlanPayload } from '@/lib/types'

/** THE EYE TEST, WITH THE EVIDENCE - and a way to act on your own.
 *
 * A manager sees a player drift. That is on this board for every player in the
 * squad and every transfer: the last three matches against the rest of his
 * season, shots, FotMob ratings, and - beside it - what players in the same
 * state went on to do in the next match across every stored season. Where the
 * history says a dip like this has carried, the line says so; where it says the
 * baseline already knew, it says that.
 *
 * Then the part a model cannot do: "My view". Set a player to what you believe
 * (25% worse, 10% better) and the planner re-solves with that belief in every
 * gameweek of the horizon. The answer is the moves your view would make and what
 * each is worth, against the stored plan. It is an opinion applied to the same
 * solver, and it is labelled as one. */

const SPELL: Record<string, string> = {
  'under a quarter': 'Under a quarter of their earlier output',
  'a quarter to a half': 'A quarter to a half of it',
  'half to three quarters': 'Half to three quarters of it',
  'three quarters to level': 'Just under it',
  above: 'Above it',
  'well above': 'More than one and a half times it',
}

const VIEWS = [
  { v: 0.5, label: '-50%' },
  { v: 0.75, label: '-25%' },
  { v: 0.9, label: '-10%' },
  { v: 1, label: 'as is' },
  { v: 1.1, label: '+10%' },
]

function Bars({ values }: { values: number[] }) {
  const max = Math.max(1, ...values)
  return (
    <span className="inline-flex h-6 items-end gap-0.5" aria-label={`xG plus xA by match: ${values.join(', ')}`}>
      {values.map((v, i) => (
        <span key={i} className={`w-2 ${i >= values.length - 3 ? 'bg-text-muted' : 'bg-divider'}`} style={{ height: `${Math.max(8, (v / max) * 100)}%` }} title={`${v.toFixed(2)}`} />
      ))}
    </span>
  )
}

function FormLine({ f }: { f: FormReading }) {
  return (
    <div className="tabular text-[13px] leading-snug text-text-muted">
      Last 3 matches <span className="font-semibold text-text">{f.recent_xgi90.toFixed(2)}</span> xG+xA per 90, against {f.before_xgi90.toFixed(2)} before. Shots {f.recent_shots90.toFixed(1)} against{' '}
      {f.before_shots90.toFixed(1)}.{f.ratings.length > 0 && <> Ratings {f.ratings.join(', ')}.</>}
    </div>
  )
}

export function EyeTest({ plan }: { plan: WeekPlanPayload }) {
  const board = plan.form_board ?? []
  const moveForms = useMemo(() => {
    const out: { player_id: number; name: string; form: FormReading; side: string }[] = []
    for (const m of plan.moves ?? []) {
      if (m.out.form) out.push({ player_id: m.out.player_id, name: m.out.name, form: m.out.form, side: 'selling' })
      if (m.into.form) out.push({ player_id: m.into.player_id, name: m.into.name, form: m.into.form, side: 'buying' })
    }
    return out
  }, [plan.moves])
  const [views, setViews] = useState<Record<number, number>>({})
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ViewPlanPayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (board.length === 0 && moveForms.length === 0) return null

  const rows = [
    ...moveForms.map((r) => ({ ...r })),
    ...board.filter((b) => !moveForms.some((m) => m.player_id === b.player_id) && (b.label !== 'STEADY' || b.position === 'FWD')).map((b) => ({ player_id: b.player_id, name: b.name, form: b as FormReading, side: '' })),
  ].slice(0, 10)

  const active = Object.entries(views).filter(([, v]) => v !== 1)
  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(await fetchViewPlan(Object.fromEntries(active.map(([k, v]) => [Number(k), v]))))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The planner could not be reached.')
    } finally {
      setBusy(false)
    }
  }

  const evidence = [...new Map(rows.filter((r) => r.form.evidence).map((r) => [r.form.evidence!.bin, r.form.evidence!])).values()].sort((x, y) => x.ratio - y.ratio)

  return (
    <Panel
      title="Does the eye test hold up?"
      sub="How the players in your moves and squad have looked over their last three matches, and what history says follows a dip like that. Set what you believe and the planner re-solves with it."
    >
      {evidence.length > 0 && (
        <div className="mb-5 rounded-lg bg-void/50 px-4 py-3">
          <div className="mb-2 text-[13px] text-text-muted">
            What followed, over every stored season: midfielders and forwards, last three matches against the rest of their season, then the next match against a baseline that already includes the dip.
          </div>
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-text-faint">
                <th className="py-1 pr-4 font-medium">Their last three matches</th>
                <th className="py-1 pr-4 font-medium">Next match, against baseline</th>
                <th className="py-1 text-right font-medium">Cases</th>
              </tr>
            </thead>
            <tbody className="tabular text-text-muted">
              {evidence.map((e) => (
                <tr key={e.bin} className="border-t border-divider/60">
                  <td className="py-1.5 pr-4">{SPELL[e.bin] ?? e.bin}</td>
                  <td className="py-1.5 pr-4">
                    <span className="font-semibold text-text">{e.ratio.toFixed(2)}x</span> <span className="text-text-faint">({e.ci[0].toFixed(2)} to {e.ci[1].toFixed(2)})</span>{' '}
                    <span className={e.ci[1] < 1 ? 'text-alert-red' : e.ci[0] > 1 ? 'text-pitch-green' : 'text-text-faint'}>{e.ci[1] < 1 ? 'carried' : e.ci[0] > 1 ? 'carried upward' : 'no difference'}</span>
                  </td>
                  <td className="py-1.5 text-right">{e.n.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 text-[12px] text-text-faint">1.00x means the player did exactly what his season already implied. A range that straddles 1.00 means the spell told us nothing.</div>
        </div>
      )}

      <div className="divide-y divide-divider border-y border-divider">
        {rows.map((r) => (
          <div key={r.player_id} className="grid grid-cols-1 gap-3 py-3 lg:grid-cols-[17rem_1fr_auto] lg:items-center">
            <div className="flex items-center gap-3">
              <Link to={`/player/${r.player_id}`} className="w-28 shrink-0 truncate text-[15px] font-semibold text-text hover:text-pitch-green">{r.name}</Link>
              <Pill tone={r.form.label === 'COLD' ? 'red' : r.form.label === 'COOLING' ? 'gold' : r.form.label === 'HOT' ? 'green' : 'neutral'}>{r.form.label.toLowerCase()}</Pill>
              {r.side && <span className="text-[12px] text-text-faint">{r.side}</span>}
              <Bars values={r.form.per_match_xgi} />
            </div>
            <FormLine f={r.form} />
            <div className="flex items-center gap-1" role="group" aria-label={`My view of ${r.name}`}>
              {VIEWS.map((o) => (
                <button
                  key={o.v}
                  type="button"
                  onClick={() => setViews((cur) => ({ ...cur, [r.player_id]: o.v }))}
                  className={`rounded px-2 py-1 text-[12px] font-semibold transition-colors ${(views[r.player_id] ?? 1) === o.v ? (o.v === 1 ? 'bg-raised text-text' : 'bg-broadcast-gold text-broadcast-gold-ink') : 'bg-raised/50 text-text-faint hover:text-text'}`}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4">
        <button
          type="button"
          disabled={busy || active.length === 0}
          onClick={run}
          className="rounded-md bg-pitch-green px-4 py-2 text-[13px] font-semibold text-pitch-green-ink disabled:opacity-40"
        >
          {busy ? 'Re-planning…' : 'Re-plan with my view'}
        </button>
        {active.length > 0 && <span className="text-[13px] text-text-muted">{active.length} player{active.length === 1 ? '' : 's'} adjusted over every gameweek of the horizon</span>}
        {active.length === 0 && <span className="text-[13px] text-text-faint">Pick a view for at least one player: how much better or worse than the model you think they are.</span>}
        {busy && <span className="text-[12px] text-text-faint">The planner takes 10 to 40 seconds.</span>}
      </div>

      {error && <p className="mt-3 border-l-4 border-alert-red bg-void/50 px-4 py-2 text-sm text-text-muted">{error}</p>}

      {result && (
        <div className="mt-5 rounded-lg border border-broadcast-gold/40 bg-void/50 px-5 py-4">
          <div className="text-[14px] font-semibold text-broadcast-gold">{result.same_as_stored ? 'Your view makes the same moves' : 'Your view changes the plan'}</div>
          <div className="mt-3 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div>
              <div className="text-[13px] text-text-faint">With your view: +{result.gain_vs_roll.toFixed(1)} over {result.horizon} GW</div>
              {result.moves.length === 0 && <p className="mt-1 text-sm text-text-muted">Roll: nothing clears the bar.</p>}
              {result.moves.map((m) => (
                <div key={m.into.player_id} className="mt-1 text-sm text-text">
                  {m.out.name} <span className="text-text-faint">&rarr;</span> <span className="font-semibold">{m.into.name}</span>{' '}
                  <span className="tabular font-semibold text-pitch-green">+{m.gain.toFixed(1)}</span>
                </div>
              ))}
              {result.declined.map((m) => (
                <div key={m.into.player_id} className="mt-1 text-[13px] text-text-faint">
                  not made: {m.out.name} &rarr; {m.into.name} adds {m.gain.toFixed(1)}
                </div>
              ))}
            </div>
            <div>
              <div className="text-[13px] text-text-faint">The stored plan</div>
              {(plan.moves ?? []).map((m) => (
                <div key={m.into.player_id} className="mt-1 text-sm text-text-muted">
                  {m.out.name} <span className="text-text-faint">&rarr;</span> {m.into.name} <span className="tabular">+{m.gain.toFixed(1)}</span>
                </div>
              ))}
              {(plan.moves ?? []).length === 0 && <p className="mt-1 text-sm text-text-muted">Roll.</p>}
            </div>
          </div>
          <p className="mt-3 text-[12px] text-text-faint">An opinion applied to the same planner. It changes nothing stored and submits nothing.</p>
        </div>
      )}
    </Panel>
  )
}
