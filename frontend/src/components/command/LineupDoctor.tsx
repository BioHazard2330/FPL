import { Link } from 'react-router-dom'
import { crestUrl } from '@/lib/api'
import type { LineupChanges, WeekPlanLineupPlayer } from '@/lib/types'

function Row({ p, dir }: { p: WeekPlanLineupPlayer; dir: 'in' | 'out' }) {
  const crest = crestUrl(p.team_code)
  return (
    <div className={`flex items-center gap-3 border-l-4 bg-void px-4 py-3 ${dir === 'in' ? 'border-pitch-green' : 'border-alert-red'}`}>
      <span className={`w-4 text-lg font-bold ${dir === 'in' ? 'text-pitch-green' : 'text-alert-red'}`} aria-hidden>
        {dir === 'in' ? '▲' : '▼'}
      </span>
      {crest && <img src={crest} alt="" className="h-6 w-6 rounded-full bg-void ring-2 ring-void" />}
      <div className="min-w-0 flex-1">
        <Link to={`/player/${p.player_id}`} className="block truncate font-display text-xl font-bold uppercase leading-none text-text hover:text-pitch-green">
          {p.name}
        </Link>
        <div className="mt-0.5 text-[12px] font-semibold uppercase tracking-wide text-text-faint">
          {p.team_short} &middot; {p.position}
          {p.start_percent !== null && p.start_percent < 70 && <span className="ml-2 text-broadcast-gold">{p.start_percent}% to start</span>}
        </div>
      </div>
      <div className={`tabular font-display text-2xl font-bold ${dir === 'in' ? 'text-pitch-green' : 'text-text-muted'}`}>{p.xp.toFixed(1)}</div>
    </div>
  )
}

/** THE LINEUP - what the squad you already hold is worth if the eleven and the
 * armband are set properly.
 *
 * FPL keeps last week's eleven until the manager changes it, so a bench player
 * who has overtaken a starter stays on the bench through a deadline nobody
 * remembered to revisit. This is the comparison between the lineup as it is set
 * on the FPL site now and the best one the same fifteen can field, before any
 * transfer. It costs nothing and uses no free transfer, which is why it sits
 * apart from the transfer plan. */
export function LineupDoctor({ changes, event }: { changes: LineupChanges | null | undefined; event: number | undefined }) {
  if (!changes) return null
  const armband = changes.captain_from && changes.captain_to && changes.captain_from.player_id !== changes.captain_to.player_id
  const viceChange = changes.vice_from && changes.vice_to && changes.vice_from.player_id !== changes.vice_to.player_id

  return (
    <section className="bg-void px-10 py-10">
      <div className="mb-1 flex flex-wrap items-baseline gap-x-4">
        <span className="text-[13px] font-bold uppercase tracking-[0.15em] text-text-faint">Your lineup for GW{event}</span>
        <span className="font-mono text-[12px] uppercase tracking-[0.1em] text-text-faint">before any transfer &middot; costs nothing</span>
      </div>

      {changes.worth_changing ? (
        <>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1">
            <h2 className="font-display text-4xl font-bold uppercase leading-none text-text">Set your eleven</h2>
            <span className="tabular font-display text-3xl font-bold text-pitch-green">+{changes.xp_gain.toFixed(1)} xP</span>
            <span className="text-sm text-text-muted">on the lineup as it stands on the FPL site</span>
          </div>

          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-[12px] font-bold uppercase tracking-[0.1em] text-pitch-green">Start</div>
              <div className="space-y-px">
                {changes.bring_in.map((p) => (
                  <Row key={p.player_id} p={p} dir="in" />
                ))}
                {changes.bring_in.length === 0 && <div className="bg-panel px-4 py-3 text-sm text-text-faint">No change to the eleven.</div>}
              </div>
            </div>
            <div>
              <div className="mb-2 text-[12px] font-bold uppercase tracking-[0.1em] text-alert-red">To the bench</div>
              <div className="space-y-px">
                {changes.take_out.map((p) => (
                  <Row key={p.player_id} p={p} dir="out" />
                ))}
                {changes.take_out.length === 0 && <div className="bg-panel px-4 py-3 text-sm text-text-faint">Nobody leaves the eleven.</div>}
              </div>
            </div>
          </div>

          {(armband || viceChange) && (
            <div className="mt-6 flex flex-wrap items-center gap-x-8 gap-y-2 border-t border-divider pt-4 text-sm">
              {armband && (
                <span className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center bg-broadcast-gold text-xs font-bold text-broadcast-gold-ink">C</span>
                  <span className="text-text-muted">{changes.captain_from!.name}</span>
                  <span aria-hidden className="text-text-faint">&rarr;</span>
                  <span className="font-semibold text-text">{changes.captain_to!.name}</span>
                </span>
              )}
              {viceChange && (
                <span className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center bg-raised text-[12px] font-bold text-text">V</span>
                  <span className="text-text-muted">{changes.vice_from!.name}</span>
                  <span aria-hidden className="text-text-faint">&rarr;</span>
                  <span className="font-semibold text-text">{changes.vice_to!.name}</span>
                </span>
              )}
            </div>
          )}
        </>
      ) : (
        <p className="mt-2 text-lg text-text-muted">The lineup on the FPL site is already the best eleven and armband this squad can field.</p>
      )}
    </section>
  )
}
