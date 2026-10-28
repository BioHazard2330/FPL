import { useState } from 'react'
import { Link } from 'react-router-dom'
import { chipName, Pill, money } from '@/components/ui/kit'
import { Face } from '@/components/ui/Face'
import { NextFixture } from '@/components/football/FixtureRun'
import { clubColors } from '@/lib/clubs'
import type { WeekPlanMove, WeekPlanPayload } from '@/lib/types'
import { MadeItButton, RecordedStrip } from '@/components/command/MadeTransfer'

const ago = (hours: number) => (hours < 1 ? `${Math.max(1, Math.round(hours * 60))} min ago` : hours < 48 ? `${Math.round(hours)}h ago` : `${Math.round(hours / 24)}d ago`)

function confidence(m: WeekPlanMove) {
  const c = m.confidence
  if (!c) return null
  const tone = c.win_prob >= 0.65 ? 'green' : c.win_prob >= 0.55 ? 'gold' : 'red'
  const word = c.win_prob >= 0.65 ? 'Solid' : c.win_prob >= 0.55 ? 'Lean' : 'Thin'
  return (
    <Pill
      tone={tone}
      title={`Replayed ${c.trials.toLocaleString()} times with match and talent uncertainty, ${m.into.name} out-scores ${m.out.name} over ${c.horizon} gameweeks in ${Math.round(c.win_prob * 100)}% of them. The middle 80% of the difference runs ${c.p10} to +${c.p90} points.`}
    >
      {word} · {Math.round(c.win_prob * 100)}% to pay off
    </Pill>
  )
}

function Column({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 px-6 py-5">
      <div className="mb-3 text-[13px] font-medium text-text-faint">{title}</div>
      {children}
    </div>
  )
}

function Moves({ plan }: { plan: WeekPlanPayload }) {
  const moves = plan.moves ?? []
  const horizon = plan.horizon ?? 5
  if (moves.length === 0) {
    return (
      <>
        <div className="font-display text-3xl font-semibold leading-none text-text">Roll</div>
        <p className="mt-3 text-[14px] leading-snug text-text-muted">
          No transfer adds {plan.min_move_gain} points or more over {horizon} gameweeks.{' '}
          {(plan.free_transfers ?? 0) >= 5 ? 'You hold the maximum of five, so rolling still costs you one.' : `Rolling banks a free transfer: ${Math.min((plan.free_transfers ?? 0) + 1, 5)} next week.`}
        </p>
        {(plan.curve ?? []).filter((c) => c.moves > 0).length > 0 && (
          <p className="mt-2 text-[13px] leading-snug text-text-faint">
            Closest it came:{' '}
            {(plan.curve ?? [])
              .filter((c) => c.moves > 0)
              .map((c) => `${c.moves} move${c.moves === 1 ? '' : 's'} ${c.gain_vs_roll >= 0 ? '+' : ''}${c.gain_vs_roll.toFixed(1)} (needs ${(c.moves * (plan.min_move_gain ?? 1.5)).toFixed(1)})`)
              .join(' · ')}
            .
          </p>
        )}
      </>
    )
  }
  const late = moves.some((m) => m.timing === 'late')
  return (
    <>
      <div className="space-y-5">
        {moves.map((m) => (
          <div key={m.into.player_id} className="flex items-center gap-4">
            <Link to={`/player/${m.out.player_id}`} className="block">
              <Face code={m.out.photo_code} teamCode={m.out.team_code} isGkp={m.out.position === 'GKP'} size="md" muted />
            </Link>
            <span aria-hidden className="text-xl text-text-faint">&rarr;</span>
            <Link to={`/player/${m.into.player_id}`} className="block">
              <Face code={m.into.photo_code} teamCode={m.into.team_code} isGkp={m.into.position === 'GKP'} size="lg" />
            </Link>
            <div className="min-w-0">
              <div className="truncate font-display text-lg leading-tight text-text-muted">{m.out.name}</div>
              <div className="truncate font-display text-[1.7rem] font-semibold leading-tight text-text">{m.into.name}</div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px] text-text-muted">
                {moves.length > 1 && <span className="tabular font-semibold text-pitch-green">+{m.gain.toFixed(1)} pts</span>}
                <span className="tabular">{m.cost_tenths > 0 ? `costs ${money(m.cost_tenths)}` : m.cost_tenths < 0 ? `frees ${money(-m.cost_tenths)}` : 'like for like'}</span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-3">
                {confidence(m)}
                <MadeItButton outId={m.out.player_id} inId={m.into.player_id} decisionId={plan.decision_id} />
              </div>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-5 text-[14px] leading-snug text-text-muted">
        <span className="tabular font-semibold text-text">+{(plan.gain_vs_roll ?? 0).toFixed(1)} points</span> over the next {horizon} gameweeks against rolling.
        {late && ' At least one of these is better made after team news.'}
      </p>
    </>
  )
}

/** Floor, expected and ceiling on one track: how wide the outcome is, not just where the middle sits. */
function RangeBar({ floor, median, ceiling, top, color }: { floor: number; median: number; ceiling: number; top: number; color: string }) {
  const at = (v: number) => `${Math.min(100, Math.max(0, (v / top) * 100))}%`
  return (
    <div className="relative mt-3 h-2 rounded-full bg-void/70">
      <div className="absolute inset-y-0 rounded-full opacity-35" style={{ left: at(floor), right: `calc(100% - ${at(ceiling)})`, background: color }} />
      <div className="absolute -inset-y-[3px] w-[3px] rounded-full" style={{ left: at(median), background: color }} />
    </div>
  )
}

function Armband({ plan }: { plan: WeekPlanPayload }) {
  const cap = plan.captain
  const vice = plan.lineup_after?.starting.concat(plan.lineup_after.bench).find((p) => p.player_id === plan.lineup_after?.vice_id)
  if (!cap) return <p className="text-[14px] text-text-muted">No armband projection yet.</p>
  const run = cap.best.team_code !== null ? plan.fixtures?.[String(cap.best.team_code)] : undefined
  const color = clubColors(cap.best.team_code).accent
  const top = Math.max(cap.best.ceiling ?? cap.best.median * 2, 1)
  return (
    <>
      <div className="flex items-start gap-4">
        <Link to={`/player/${cap.best.player_id}`} className="block">
          <Face
            code={cap.best.photo_code}
            teamCode={cap.best.team_code}
            isGkp={cap.best.position === 'GKP'}
            size="xl"
            badge={<span className="flex size-6 items-center justify-center rounded-full bg-broadcast-gold text-[12px] font-bold text-broadcast-gold-ink ring-2 ring-panel">C</span>}
          />
        </Link>
        <div className="min-w-0 flex-1">
          <Link to={`/player/${cap.best.player_id}`} className="block font-display text-3xl font-semibold leading-none text-text hover:text-pitch-green">
            {cap.best.name}
          </Link>
          <div className="tabular mt-2 flex items-baseline gap-2">
            <span className="font-display text-2xl font-semibold text-pitch-green">{cap.best.median.toFixed(1)}</span>
            <span className="text-[13px] text-text-faint">xP</span>
            <NextFixture fixtures={run} className="ml-1 rounded-sm" />
          </div>
          {cap.best.floor !== null && cap.best.ceiling !== null && (
            <>
              <RangeBar floor={cap.best.floor} median={cap.best.median} ceiling={cap.best.ceiling} top={top} color={color} />
              <div className="tabular mt-1 flex justify-between text-[12px] text-text-faint">
                <span>{cap.best.floor.toFixed(1)}</span>
                <span>{cap.best.ceiling.toFixed(1)}</span>
              </div>
            </>
          )}
        </div>
      </div>
      <p className="mt-4 text-[14px] leading-snug text-text-muted">
        {cap.second && (
          <>
            Next best is <span className="font-semibold text-text">{cap.second.name}</span> on {cap.second.median.toFixed(1)}.{' '}
          </>
        )}
        {vice && <>Vice: <span className="font-semibold text-text">{vice.name}</span>.</>}
      </p>
      {cap.note && <p className="mt-2 text-[13px] leading-snug text-text-faint">{cap.note}</p>}
    </>
  )
}

function Lineup({ plan }: { plan: WeekPlanPayload }) {
  const d = plan.doctor
  if (!d) return <p className="text-[14px] text-text-muted">Your eleven is set; nothing to change.</p>
  if (!d.worth_changing) {
    return (
      <>
        <div className="font-display text-3xl font-semibold leading-none text-text">Keep it</div>
        <p className="mt-3 text-[14px] leading-snug text-text-muted">The eleven you have on the FPL site is the best this squad allows, within a tenth of a point.</p>
      </>
    )
  }
  return (
    <>
      <div className="font-display text-3xl font-semibold leading-none text-text">
        <span className="tabular text-pitch-green">+{d.xp_gain.toFixed(1)}</span> xP
      </div>
      <div className="mt-4 flex items-center gap-3">
        <div className="flex -space-x-2">
          {d.bring_in.map((p) => (
            <Link key={p.player_id} to={`/player/${p.player_id}`} title={`${p.name} comes in`}>
              <Face code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} size="sm" />
            </Link>
          ))}
        </div>
        {d.take_out.length > 0 && <span aria-hidden className="text-text-faint">&larr;</span>}
        <div className="flex -space-x-2">
          {d.take_out.map((p) => (
            <Link key={p.player_id} to={`/player/${p.player_id}`} title={`${p.name} goes to the bench`}>
              <Face code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} size="sm" muted />
            </Link>
          ))}
        </div>
      </div>
      <p className="mt-3 text-[14px] leading-snug text-text-muted">
        Start <span className="font-semibold text-text">{d.bring_in.map((p) => p.name).join(' and ')}</span>
        {d.take_out.length > 0 && (
          <>
            {' '}for <span className="font-semibold text-text">{d.take_out.map((p) => p.name).join(' and ')}</span>
          </>
        )}
        {d.captain_to && d.captain_from && d.captain_to.player_id !== d.captain_from.player_id && <>, armband to {d.captain_to.name}</>}. Costs nothing, and counts even if you make no transfer.
      </p>
    </>
  )
}

function CopyMoves({ plan }: { plan: WeekPlanPayload }) {
  const [copied, setCopied] = useState(false)
  const moves = plan.moves ?? []
  if (moves.length === 0) return null
  const text = [`GW${plan.event} transfers`, ...moves.map((m, i) => `${i + 1}. ${m.out.name} (${money(m.out.price_tenths)}) -> ${m.into.name} (${money(m.into.price_tenths)})`)].join('\n')
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 2000)
        })
      }}
      className="rounded-md bg-raised px-3 py-1.5 text-[13px] font-semibold text-text hover:bg-divider"
    >
      {copied ? 'Copied' : 'Copy the moves'}
    </button>
  )
}

/** THE WEEK'S CALL, on one sheet: transfers, armband, lineup. The three things a manager changes before a deadline, each with
 * its size, side by side, and the account (free transfers, bank, chips) underneath. Everything else on the page is the evidence
 * for one of these three. */
export function DecisionSheet({ plan, chips }: { plan: WeekPlanPayload; chips: string[] }) {
  const stale = plan.status === 'stale'
  const ft = plan.free_transfers ?? 0
  const moves = plan.moves ?? []
  return (
    <section className="overflow-hidden slab">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-divider px-6 py-4">
        <div className="flex items-baseline gap-3">
          <h2 className="font-display text-2xl font-semibold leading-none text-text">GW{plan.event}: what to do</h2>
          {plan.computed_at && (
            <span className="text-[13px] text-text-faint">
              planned {ago(plan.age_hours ?? 0)}
              {(plan.new_results ?? 0) > 0 && <span className="text-broadcast-gold"> &middot; {plan.new_results} match{plan.new_results === 1 ? '' : 'es'} finished since, refreshing</span>}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <CopyMoves plan={plan} />
          <a href="https://fantasy.premierleague.com/transfers" target="_blank" rel="noreferrer" className="text-[13px] font-medium text-text-muted hover:text-text">
            Open FPL transfers &#8599;
          </a>
        </div>
      </header>

      <RecordedStrip plan={plan} />

      {stale && (
        <div className="border-b border-divider bg-alert-red/10 px-6 py-3 text-[14px] text-text-muted">
          <span className="font-semibold text-alert-red">This plan is out of date.</span> {(plan.stale_reasons ?? []).join('; ')}. Sync rebuilds it; until then treat the moves as a guide to the last sync.
        </div>
      )}

      <div className="grid grid-cols-1 divide-y divide-divider lg:grid-cols-[1.35fr_1fr_1fr] lg:divide-x lg:divide-y-0">
        <Column title={moves.length === 0 ? 'Transfers' : moves.length === 1 ? 'Transfer' : `Transfers (${moves.length})`}>
          <Moves plan={plan} />
        </Column>
        <Column title="Armband">
          <Armband plan={plan} />
        </Column>
        <Column title="Lineup">
          <Lineup plan={plan} />
        </Column>
      </div>

      <footer className="flex flex-wrap items-center gap-x-8 gap-y-2 border-t border-divider px-6 py-3.5 text-[13px] text-text-muted">
        <span>
          Free transfers <span className="tabular font-semibold text-text">{ft}</span>
          {moves.length > 0 && <> &rarr; <span className="tabular font-semibold text-text">{plan.ft_after ?? '—'}</span></>}
        </span>
        <span>
          Bank <span className="tabular font-semibold text-text">{money(plan.bank_tenths ?? 0)}</span>
          {moves.length > 0 && <> &rarr; <span className="tabular font-semibold text-text">{money(plan.bank_after_tenths ?? 0)}</span></>}
        </span>
        {chips.length > 0 && (
          <span>
            Chips left <span className="font-semibold text-text">{chips.map(chipName).join(', ')}</span>
          </span>
        )}
        {plan.affordability && moves.length > 0 && <span className="text-text-faint">{plan.affordability}</span>}
      </footer>
    </section>
  )
}
