import { Link } from 'react-router-dom'
import { relativeTime } from '@/lib/time'
import type { WeekPlanAuditBlock } from '@/lib/types'

/** THE WEEK PLAN, CHECKED - the workbench's centrepiece.
 *
 * What the engine room is for: not "is the plan good" but "how wrong can the
 * model be before this plan stops being worth following". Each move is priced
 * against the best plan that makes the other moves and nothing else, at the
 * projection as it stands and at half of it for the player coming in. The
 * drop that takes the move to the bar is read off the line between the two;
 * that is an interpolation and is labelled as one.
 *
 * It sits beside the one independent projection this project has (Solio) and
 * the assumptions the plan rests on, because a stress test that does not say
 * what it assumed is decoration. */
export function WeekPlanAudit({ audit }: { audit: WeekPlanAuditBlock }) {
  const maxGain = Math.max(...audit.moves.map((m) => m.stress?.gain_with_others ?? m.gain), 1)

  return (
    <section className="border-b-2 border-divider bg-void px-10 py-8">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">GW{audit.event} week plan, checked</span>
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-text-faint">
          decision #{audit.decision_id} &middot; solved {relativeTime(audit.computed_at) ?? '—'}
          {audit.solver && (
            <>
              {' '}
              &middot; {audit.solver.proven_optimal ? 'proven best plan' : 'best found, not proven'} over {audit.solver.horizon} GW &middot;{' '}
              {audit.solver.pool_size} players considered
            </>
          )}
        </span>
      </div>

      {audit.stale_reasons.length > 0 && (
        <div className="mt-3 max-w-2xl border-l-4 border-alert-red bg-panel px-4 py-2 text-sm text-text-muted">
          Out of date: {audit.stale_reasons.join('; ')}.
        </div>
      )}

      {audit.moves.length === 0 ? (
        <p className="mt-4 max-w-2xl text-sm text-text-muted">The plan is a roll, so there is no move to stress.</p>
      ) : (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[56rem] text-left text-sm">
            <caption className="sr-only">Each planned move and what it is worth if the player coming in disappoints</caption>
            <thead>
              <tr className="border-b-2 border-divider text-[10px] uppercase tracking-[0.14em] text-text-faint">
                <th scope="col" className="py-2 pr-4 font-bold">Move</th>
                <th scope="col" className="py-2 pr-4 text-right font-bold">xP next GW</th>
                <th scope="col" className="py-2 pr-4 text-right font-bold">Solio</th>
                <th scope="col" className="py-2 pr-4 font-bold">Worth, with the other moves made</th>
                <th scope="col" className="py-2 pr-4 text-right font-bold">If he returns half</th>
                <th scope="col" className="py-2 text-right font-bold">Stops clearing {audit.min_move_gain} if he returns</th>
              </tr>
            </thead>
            <tbody>
              {audit.moves.map((m) => {
                const worth = m.stress?.gain_with_others ?? m.gain
                return (
                  <tr key={m.into_id} className="border-b border-divider align-middle">
                    <th scope="row" className="py-3 pr-4 text-left">
                      <span className="text-text-muted">{m.out}</span> <span aria-hidden className="text-text-faint">&rarr;</span>{' '}
                      <Link to={`/player/${m.into_id}`} className="font-display text-lg font-bold uppercase text-text hover:text-pitch-green">
                        {m.into}
                      </Link>
                      {m.start_percent_out !== null && m.start_percent_out < 70 && (
                        <span className="ml-2 text-[10px] font-bold uppercase text-broadcast-gold">{m.out} {m.start_percent_out}% to start</span>
                      )}
                    </th>
                    <td className="tabular py-3 pr-4 text-right text-text-muted">
                      {m.xp_out.toFixed(1)} &rarr; <span className="font-bold text-text">{m.xp_in.toFixed(1)}</span>
                    </td>
                    <td className="tabular py-3 pr-4 text-right text-text-muted">{m.solio_in !== null ? m.solio_in.toFixed(1) : '—'}</td>
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-3">
                        <div className="h-2.5 w-40 bg-panel">
                          <div className="bar-draw h-full bg-pitch-green" style={{ width: `${Math.max(4, (Math.max(worth, 0) / maxGain) * 100)}%` }} />
                        </div>
                        <span className="tabular font-bold text-pitch-green">+{worth.toFixed(1)}</span>
                      </div>
                    </td>
                    <td className="tabular py-3 pr-4 text-right">
                      {m.stress ? (
                        <span className={m.stress.survives_half ? 'font-bold text-pitch-green' : 'font-bold text-alert-red'}>
                          {m.stress.gain_if_half >= 0 ? '+' : ''}
                          {m.stress.gain_if_half.toFixed(1)}
                        </span>
                      ) : (
                        <span className="text-text-faint">—</span>
                      )}
                    </td>
                    <td className="tabular py-3 text-right text-text-muted">
                      {m.stress
                        ? m.stress.breakeven_drop_pct === null
                          ? 'more than half'
                          : `${m.stress.breakeven_drop_pct.toFixed(0)}% less than projected`
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 max-w-3xl text-xs leading-relaxed text-text-faint">
        {audit.model_mae !== null
          ? `The model's own measured error is ${audit.model_mae.toFixed(1)} points per player per gameweek, so a player returning a fifth less than projected is ordinary. `
          : 'There are too few settled predictions to measure the model\'s own error yet. '}
        A move that stops clearing the bar at that point is a margin call, not a certainty. The last column is interpolated between the two
        solves, not a third one.
      </p>

      <div className="mt-6 border-t-2 border-divider pt-4">
        <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">What the plan assumes</div>
        <ul className="max-w-3xl list-disc space-y-1.5 pl-5 text-sm text-text-muted">
          {audit.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </div>
    </section>
  )
}
