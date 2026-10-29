import type { Chase } from '@/lib/types'

const pct = (p: number) => `${Math.round(p * 100)}%`
const signed = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`
const RANK_LABEL: Record<string, string> = { '1000': 'top 1k', '10000': 'top 10k', '100000': 'top 100k' }

/** The road to the target as a printed ruler: the manager's total and each rank target's total on one points scale. */
function Ruler({ c }: { c: Chase }) {
  const marks = [
    ...Object.entries(c.others).map(([rank, total]) => ({ rank, total, main: false })),
    { rank: String(c.target), total: c.target_total, main: true },
  ]
  const lo = Math.min(c.you_total, ...marks.map((m) => m.total)) - 8
  const hi = Math.max(c.you_total, ...marks.map((m) => m.total)) + 8
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`
  return (
    <div className="relative mt-8 h-24">
      <div className="absolute inset-x-0 top-10 h-[3px] bg-ink" />
      <div className="absolute top-10 h-[3px] bg-spot" style={{ left: x(c.you_total), width: `calc(${x(c.target_total)} - ${x(c.you_total)})` }} />
      {marks.map((m) => (
        <div key={m.rank} className="absolute top-0 -translate-x-1/2 text-center" style={{ left: x(m.total) }}>
          <div className={`whitespace-nowrap font-display font-black uppercase ${m.main ? 'text-[15px] text-text' : 'text-[12px] text-text-faint'}`}>{RANK_LABEL[m.rank] ?? m.rank}</div>
          <div className={`mx-auto mt-1 w-[3px] bg-ink ${m.main ? 'h-7' : 'h-5'}`} />
          <div className={`tabular mt-1 font-display font-black ${m.main ? 'text-xl text-text' : 'text-sm text-text-faint'}`}>{m.total}</div>
        </div>
      ))}
      <div className="absolute top-[1.85rem] -translate-x-1/2 text-center" style={{ left: x(c.you_total) }}>
        <div className="mx-auto size-5 rounded-full border-[3px] border-ink bg-spot" />
        <div className="tabular mt-1.5 whitespace-nowrap bg-ink px-1.5 font-display text-[15px] font-black text-paper">you {c.you_total}</div>
      </div>
    </div>
  )
}

/** THE TOP-10K CHASE: the gap to the 10,000th manager, the weekly edge on the top-10k field that closes it over the
 * gameweeks left, the measured pace so far, and what each of this week's choices does to the chance. */
export function ChaseBand({ c }: { c: Chase }) {
  const pace = c.pace_source === 'measured' && c.measured_pace ? c.measured_pace : null
  const chanceNow = pace ? c.chance_at_measured_pace ?? c.chance_at_plan_pace : c.chance_at_plan_pace
  const plan = c.options.find((o) => o.key === 'plan')
  const rows = [
    ...c.options.filter((o) => o.key !== 'plan' || !c.options.some((x) => x.key === 'roll' && x.mean === o.mean)),
    ...c.captains.slice().sort((a, b) => b.chance - a.chance).slice(0, 4).map((k) => ({
      key: `cap_${k.player_id}`, label: `Armband on ${k.name}${k.chosen ? ' (the plan)' : ''}`, mean: k.mean, sd: k.sd, chance: k.chance,
    })),
  ]
  const base = plan?.chance ?? chanceNow
  const maxEdge = Math.max(10, ...c.measured.map((m) => Math.abs(m.edge)))
  return (
    <section className="px-10 pb-8 pt-7">
      <div className="voice text-lg text-text-muted">the season's real target</div>
      <h2 className="font-display text-text">The top-10k chase</h2>
      <div className="mt-5 grid grid-cols-1 gap-8 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div>
          <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
            <div>
              <div className="tabular font-display text-[5.5rem] font-black leading-[0.8] text-text">{c.gap > 0 ? c.gap : 0}</div>
              <div className="mt-2 text-[13px] text-text-muted">points behind the 10,000th ({c.target_total}) after GW{c.target_event}</div>
            </div>
            <div>
              <div className="tabular font-display text-[3.4rem] font-black leading-[0.8] text-spot [text-shadow:2px_2px_0_var(--ink)]">{c.need_per_week !== null ? signed(c.need_per_week) : '—'}</div>
              <div className="mt-2 text-[13px] text-text-muted">a week above the top-10k average, for {c.weeks_left} gameweeks</div>
            </div>
          </div>
          <Ruler c={c} />
        </div>
        <div className="border-2 border-ink bg-paper p-5 shadow-[5px_5px_0_var(--ink)]">
          <div className="flex items-baseline justify-between gap-4">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-text-faint">chance of a top-10k finish</div>
              <div className={`tabular font-display text-[4.2rem] font-black leading-none ${chanceNow >= 0.5 ? 'text-pitch-green' : chanceNow >= 0.2 ? 'text-broadcast-gold' : 'text-alert-red'}`}>{pct(chanceNow)}</div>
            </div>
            <div className="text-right text-[12.5px] leading-snug text-text-muted">
              {pace ? <>at your measured pace, {signed(pace.mean)} a week over {pace.weeks} gameweeks</> : <>at the plan's simulated pace</>}
              <br />
              at this week's simulated pace ({signed(c.plan_pace.mean)}): <span className="font-semibold text-text">{pct(c.chance_at_plan_pace)}</span>
            </div>
          </div>
          {c.measured.length > 0 && (
            <div className="mt-4">
              <div className="mb-1.5 text-[11px] font-bold uppercase tracking-[0.14em] text-text-faint">your points minus the top-10k average</div>
              <div className="flex items-end gap-2">
                {c.measured.map((m) => (
                  <div key={m.event} className="flex flex-1 flex-col items-center" title={`GW${m.event}: you ${m.you}, field ${m.field}`}>
                    <div className="relative h-16 w-full">
                      <div className="absolute inset-x-0 top-1/2 h-px bg-ink/40" />
                      <div
                        className={`absolute inset-x-[18%] border-2 border-ink ${m.edge >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`}
                        style={m.edge >= 0
                          ? { bottom: '50%', height: `${(m.edge / maxEdge) * 50}%` }
                          : { top: '50%', height: `${(-m.edge / maxEdge) * 50}%` }}
                      />
                    </div>
                    <div className={`tabular font-display text-[14px] font-black ${m.edge >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(m.edge)}</div>
                    <div className="font-display text-[11px] font-black text-text-faint">GW{m.event}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="mt-7">
        <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.14em] text-text-faint">This week's choices, by the chance they leave</div>
        <div className="divide-y divide-divider border-y-2 border-ink">
          {rows.map((r) => {
            const d = r.chance - base
            return (
              <div key={r.key} className="grid grid-cols-[minmax(0,1fr)_6rem_6rem_6rem] items-baseline gap-4 py-2">
                <span className="text-[14px] text-text">{r.label}</span>
                <span className="tabular text-right text-[13px] text-text-muted">{signed(r.mean)} edge</span>
                <span className="tabular text-right font-display text-lg font-black text-text">{pct(r.chance)}</span>
                <span className={`tabular text-right text-[13px] font-semibold ${Math.abs(d) < 0.0005 ? 'text-text-faint' : d > 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
                  {Math.abs(d) < 0.0005 ? "—" : `${d > 0 ? "+" : ""}${(d * 100).toFixed(1)} pp`}
                </span>
              </div>
            )
          })}
        </div>
        <p className="mt-3 max-w-4xl text-[13px] leading-relaxed text-text-muted">
          With {c.weeks_left} gameweeks left one week moves the chance by a point or two at most, and mostly through its mean: a riskier
          armband only pays when the gap is large and few weeks remain. Assumes the 10,000th scores the top-10k field's average from here
          (the field read from the last locked gameweek, aged for flags and for how much the top ten thousand improve their team each
          week); both sides' second-half chips are left out; weeks are independent.
        </p>
      </div>
    </section>
  )
}
