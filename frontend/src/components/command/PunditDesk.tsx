import { useState } from 'react'
import type { PunditBrief, PunditMove, WeekPlanPayload } from '@/lib/types'

/** THE PUNDIT'S DESK: the week plan argued across every lens the app measures (`models/pundit.py`) - fixtures fixture by
 * fixture, the football read, minutes, Solio's model, the replays, the top-10k field's ownership, price, cards and
 * midweek football - graded by how many point the same way, with the armband judged on the chance of a top-10k finish
 * (`optimization/rank_review.py`). It argues the plan's own moves; it never proposes others. */

const GRADE: Record<PunditMove['grade'], { label: string; tone: string }> = {
  strong: { label: 'Strong', tone: 'bg-pitch-green text-paper' },
  sound: { label: 'Sound', tone: 'bg-broadcast-blue text-paper' },
  marginal: { label: 'Marginal', tone: 'bg-broadcast-gold text-ink' },
  doubtful: { label: 'Doubtful', tone: 'bg-alert-red text-paper' },
}
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`)

function ChanceMeter({ brief }: { brief: PunditBrief }) {
  const rank = brief.rank
  if (!rank) return null
  const rows = rank.options
  const lo = Math.max(0, Math.min(...rows.map((r) => r.chance)) - 0.03)
  const hi = Math.min(1, Math.max(...rows.map((r) => r.chance)) + 0.02)
  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const w = ((r.chance - lo) / Math.max(hi - lo, 1e-6)) * 100
        const plan = r.key === 'plan'
        return (
          <div key={r.key} className="grid grid-cols-[minmax(0,13rem)_minmax(0,1fr)_4.5rem] items-center gap-3">
            <div className={`truncate text-[13px] ${plan ? 'font-bold text-paper' : 'text-paper/65'}`} title={r.label}>{r.label}</div>
            <div className="relative h-5 border border-paper/25 bg-paper/5">
              <div className={`pundit-bar absolute inset-y-0 left-0 ${plan ? 'bg-spot' : 'bg-paper/35'}`} style={{ width: `${Math.max(2, w)}%` }} />
            </div>
            <div className={`tabular text-right font-display text-xl font-black ${plan ? 'text-spot' : 'text-paper/70'}`}>{pct(r.chance)}</div>
          </div>
        )
      })}
      <div className="pt-1 text-[11px] text-paper/45">
        Chance of finishing top {rank.target.toLocaleString()}: this gameweek simulated against the top-10k field ({rank.field.sample_size} sampled
        managers, GW{rank.field.sample_event} picks aged to now), the rest of the horizon at each option's projected gain, the remaining weeks at your
        measured pace ({rank.pace.mean >= 0 ? '+' : ''}{rank.pace.mean.toFixed(1)} a week, sd {rank.pace.sd.toFixed(1)}, {rank.pace.weeks} weeks). Scale zoomed to the options' range.
      </div>
    </div>
  )
}

function Lines({ items, tone }: { items: string[]; tone: string }) {
  if (!items.length) return <div className="text-[13px] italic text-text-faint">Nothing on this side.</div>
  return (
    <ul className="space-y-2">
      {items.map((t, i) => (
        <li key={i} className="grid grid-cols-[0.6rem_minmax(0,1fr)] gap-2 text-[13.5px] leading-snug text-text">
          <span className={`mt-1.5 h-2 w-2 ${tone}`} />
          <span>{t}</span>
        </li>
      ))}
    </ul>
  )
}

function MoveBrief({ m, i }: { m: PunditMove; i: number }) {
  const [open, setOpen] = useState(false)
  const g = GRADE[m.grade]
  return (
    <div className="pundit-card relative border-2 border-ink bg-paper shadow-[5px_5px_0_var(--ink)]" style={{ animationDelay: `${i * 90}ms` }}>
      <div className="flex items-center justify-between gap-4 border-b-2 border-ink px-5 py-3">
        <div className="min-w-0">
          <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-text-faint">the {m.position} move</div>
          <div className="truncate font-display text-[1.7rem] font-black uppercase leading-none text-text">
            {m.into} <span className="text-text-faint">for</span> {m.out}
          </div>
        </div>
        <div className={`pundit-stamp shrink-0 -rotate-3 border-2 border-ink px-3 py-1 font-display text-[1.3rem] font-black uppercase ${g.tone}`}>
          {g.label} <span className="text-[0.9rem] opacity-80">{m.score >= 0 ? '+' : ''}{m.score}</span>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-0 md:grid-cols-2">
        <div className="border-b-2 border-ink/15 p-5 md:border-b-0 md:border-r-2">
          <div className="mb-2 font-display text-[13px] font-black uppercase tracking-[0.12em] text-pitch-green">The case for</div>
          <Lines items={m.for} tone="bg-pitch-green" />
        </div>
        <div className="p-5">
          <div className="mb-2 font-display text-[13px] font-black uppercase tracking-[0.12em] text-alert-red">The case against</div>
          <Lines items={m.against} tone="bg-alert-red" />
        </div>
      </div>
      {m.context.length > 0 && (
        <div className="border-t-2 border-ink/15 px-5 py-2.5">
          <button type="button" onClick={() => setOpen((o) => !o)} className="text-[12px] font-bold uppercase tracking-[0.1em] text-text-muted hover:text-text">
            {open ? '−' : '+'} also on the desk ({m.context.length})
          </button>
          {open && <div className="mt-2"><Lines items={m.context} tone="bg-ink/30" /></div>}
        </div>
      )}
    </div>
  )
}

function CaptainBrief({ brief }: { brief: PunditBrief }) {
  const c = brief.captain
  if (!c) return null
  return (
    <div className="pundit-card border-2 border-ink bg-paper shadow-[5px_5px_0_var(--ink)]">
      <div className="border-b-2 border-ink px-5 py-3">
        <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-text-faint">the armband</div>
        <div className="font-display text-[1.7rem] font-black uppercase leading-none text-text">{c.options.find((o) => o.chosen)?.name}</div>
      </div>
      <div className="space-y-2 px-5 py-4 text-[13.5px] leading-snug text-text">
        {c.lines.map((l, i) => <p key={i}>{l}</p>)}
      </div>
      <table className="w-full border-t-2 border-ink/15 text-[12.5px]">
        <thead>
          <tr className="text-left text-[10.5px] uppercase tracking-[0.1em] text-text-faint">
            <th className="px-5 py-1.5 font-bold">Option</th><th className="py-1.5 font-bold">Fixture</th><th className="py-1.5 text-right font-bold">xP</th>
            <th className="py-1.5 text-right font-bold">Top 10k capt.</th><th className="px-5 py-1.5 text-right font-bold">Top-10k chance</th>
          </tr>
        </thead>
        <tbody>
          {c.options.map((o) => (
            <tr key={o.player_id} className={o.chosen ? 'bg-spot/15 font-bold' : ''}>
              <td className="px-5 py-1.5">{o.name}{o.chosen ? ' (C)' : ''}</td>
              <td className="py-1.5">{o.fixture ?? '—'}{o.difficulty ? <span className="ml-1 text-text-faint">{o.difficulty}</span> : null}</td>
              <td className="tabular py-1.5 text-right">{o.xp.toFixed(2)}</td>
              <td className="tabular py-1.5 text-right">{o.field_captain_share === null ? '—' : `${Math.round(o.field_captain_share * 100)}%`}</td>
              <td className="tabular px-5 py-1.5 text-right">{pct(o.chance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function PunditDesk({ plan }: { plan: WeekPlanPayload }) {
  const brief = plan.pundit
  if (!brief || (!brief.moves.length && !brief.captain && !brief.rank)) return null
  return (
    <section className="bare">
      <div className="relative overflow-hidden border-[3px] border-ink bg-ink px-8 pb-7 pt-6 text-paper shadow-[8px_8px_0_var(--spot)]">
        <div className="pointer-events-none absolute -right-10 -top-16 h-56 w-56 rounded-full bg-spot/20 blur-3xl" />
        <div className="relative grid grid-cols-1 gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          <div>
            <div className="voice text-lg text-paper/60">the plan, argued like a pundit, judged by the goal</div>
            <h2 className="font-display text-[2.6rem] font-black uppercase leading-none text-paper">The pundit&apos;s desk</h2>
            <div className="mt-4 space-y-2 text-[14px] leading-snug text-paper/85">
              {brief.overview.map((l, i) => <p key={i}>{l}</p>)}
            </div>
          </div>
          <ChanceMeter brief={brief} />
        </div>
      </div>
      <div className="mt-6 grid grid-cols-1 gap-6 2xl:grid-cols-2">
        {brief.moves.map((m, i) => <MoveBrief key={m.into_id} m={m} i={i} />)}
        <CaptainBrief brief={brief} />
      </div>
    </section>
  )
}
