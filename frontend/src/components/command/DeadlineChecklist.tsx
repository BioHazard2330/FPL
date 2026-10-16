import { Link } from 'react-router-dom'
import type { DeskPayload, WeekPlanPayload } from '@/lib/types'

type Tone = 'ok' | 'look' | 'act'

interface Item {
  tone: Tone
  title: string
  detail: React.ReactNode
}

const TONE: Record<Tone, { label: string; chip: string; rail: string }> = {
  ok: { label: 'Clear', chip: 'bg-pitch-green text-pitch-green-ink', rail: 'border-pitch-green' },
  look: { label: 'Look', chip: 'bg-broadcast-gold text-broadcast-gold-ink', rail: 'border-broadcast-gold' },
  act: { label: 'Act', chip: 'bg-alert-red text-alert-red-ink', rail: 'border-alert-red' },
}

/** BEFORE THE DEADLINE - the things a manager checks one last time, each
 * answered from what is already on this screen and the desk: is the plan still
 * current, is anyone in the squad carrying an injury note, does the XI as set
 * match the best one, is a price about to move on a player in or out, is a
 * player coming in a rotation risk. A row is "Clear" only when the stored data
 * says so; nothing is inferred and nothing here is a new recommendation. */
export function DeadlineChecklist({ plan, desk }: { plan: WeekPlanPayload; desk: DeskPayload | null }) {
  const moves = plan.moves ?? []
  const items: Item[] = []

  if (plan.status === 'stale') {
    items.push({ tone: 'act', title: 'The plan is out of date', detail: `${(plan.stale_reasons ?? []).join('; ')}. Sync now rebuilds it.` })
  } else {
    items.push({
      tone: 'ok',
      title: 'The plan matches your squad',
      detail: `Solved ${Math.round(plan.age_hours ?? 0)}h ago against the squad, bank and free transfers you have now.`,
    })
  }

  if (desk) {
    const mine = desk.injuries.filter((i) => i.mine)
    if (mine.length === 0) {
      items.push({ tone: 'ok', title: 'No injury note on your fifteen', detail: 'No official FPL flag on any of your players in the last ten days.' })
    } else {
      const worst = mine.some((i) => (i.chance ?? 0) <= 25)
      items.push({
        tone: worst ? 'act' : 'look',
        title: `${mine.length} of your players ${mine.length === 1 ? 'is' : 'are'} flagged`,
        detail: (
          <>
            {mine.map((i, k) => (
              <span key={i.player_id}>
                {k > 0 && ' · '}
                <Link to={`/player/${i.player_id}`} className="font-semibold text-text hover:text-pitch-green">{i.name}</Link>{' '}
                <span className="tabular">{i.chance !== null ? `${i.chance}%` : 'out'}</span>
              </span>
            ))}
          </>
        ),
      })
    }
  }

  const doctor = plan.doctor
  if (doctor) {
    if (doctor.worth_changing) {
      const armband =
        doctor.captain_to && doctor.captain_from && doctor.captain_to.player_id !== doctor.captain_from.player_id
          ? `; armband to ${doctor.captain_to.name}`
          : ''
      const out = doctor.take_out.length ? `, take out ${doctor.take_out.map((p) => p.name).join(', ')}` : ''
      items.push({
        tone: 'look',
        title: 'Your lineup is not the best one from your squad',
        detail: `Bring in ${doctor.bring_in.map((p) => p.name).join(', ') || 'nobody'}${out}${armband}. Worth ${doctor.xp_gain >= 0 ? '+' : ''}${doctor.xp_gain.toFixed(1)} xP.`,
      })
    } else {
      items.push({ tone: 'ok', title: 'Your lineup is the best one from your squad', detail: 'Same eleven and armband the model would pick.' })
    }
  }

  const rising = moves.filter((m) => m.into.price_trend === 'RISE_LIKELY')
  const falling = moves.filter((m) => m.out.price_trend === 'FALL_LIKELY')
  if (rising.length || falling.length) {
    items.push({
      tone: 'look',
      title: 'A price is about to move',
      detail:
        [
          ...rising.map((m) => `${m.into.name} is leaning up before you buy him`),
          ...falling.map((m) => `${m.out.name} is leaning down, so selling later costs the drop`),
        ].join('; ') + '. A lean only: the heuristic is uncalibrated.',
    })
  } else if (moves.length) {
    items.push({ tone: 'ok', title: 'No price pressure on the moves', detail: 'Nobody in or out is leaning either way on transfers.' })
  }

  const risky = moves.filter((m) => m.into.start_percent !== null && m.into.start_percent < 70)
  if (risky.length) {
    items.push({
      tone: 'look',
      title: 'A player coming in is a rotation risk',
      detail: `${risky.map((m) => `${m.into.name} is predicted ${m.into.start_percent}% to start`).join('; ')}. Check team news before confirming.`,
    })
  } else if (moves.length) {
    items.push({ tone: 'ok', title: 'Everyone coming in is expected to start', detail: 'Predicted start probability is 70% or higher for each.' })
  }

  const order: Tone[] = ['act', 'look', 'ok']
  items.sort((a, b) => order.indexOf(a.tone) - order.indexOf(b.tone))
  const open = items.filter((i) => i.tone !== 'ok').length

  return (
    <section className="bg-void px-10 py-10">
      <div className="mb-1 flex items-baseline gap-4">
        <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Before the deadline</span>
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-text-faint">
          {open === 0 ? 'nothing open' : `${open} thing${open === 1 ? '' : 's'} to look at`}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-px bg-divider">
        {items.map((it) => (
          <div key={it.title} className={`border-l-4 bg-panel px-5 py-3.5 ${TONE[it.tone].rail}`}>
            <div className="flex items-center gap-3">
              <span className={`px-1.5 text-[9px] font-bold uppercase leading-4 tracking-[0.12em] ${TONE[it.tone].chip}`}>{TONE[it.tone].label}</span>
              <span className="text-sm font-bold text-text">{it.title}</span>
            </div>
            <div className="mt-1 text-xs leading-relaxed text-text-muted">{it.detail}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
