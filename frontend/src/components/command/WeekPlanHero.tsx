import { useState } from 'react'
import { Link } from 'react-router-dom'
import { crestUrl } from '@/lib/api'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { FixtureRun } from '@/components/football/FixtureRun'
import type { FixtureContext, WeekPlanMove, WeekPlanPayload, WeekPlanPlayer } from '@/lib/types'

const money = (tenths: number) => `£${(tenths / 10).toFixed(1)}m`

function Tag({ tone, children, title }: { tone: 'gold' | 'red' | 'blue'; children: React.ReactNode; title?: string }) {
  const fill = { gold: 'bg-broadcast-gold text-broadcast-gold-ink', red: 'bg-alert-red text-alert-red-ink', blue: 'bg-broadcast-blue text-text' }[tone]
  return (
    <span title={title} className={`px-1.5 py-px text-[11px] font-bold uppercase leading-4 tracking-[0.1em] ${fill}`}>
      {children}
    </span>
  )
}

/** One side of a transfer. The tags are the football behind the number: a
 * rotation call on the player being sold, a price about to move, and - on the
 * player coming in - the one independent projection this project has to set
 * beside its own. */
const ordinal = (n: number) => `${n}${['th', 'st', 'nd', 'rd'][n % 100 > 10 && n % 100 < 14 ? 0 : Math.min(n % 10, 4) % 4]}`

/** The football behind the player: where his club's attack and defence rank over
 * the next six gameweeks on the team model, and what it plays first. */
function ClubLine({ outlook, side }: { outlook?: NonNullable<WeekPlanPayload['team_outlook']>[string]; side: 'out' | 'into' }) {
  if (!outlook) return null
  const next = outlook.next[0]
  const good = (rank: number) => (rank <= 6 ? 'text-pitch-green' : rank >= outlook.clubs - 5 ? 'text-alert-red' : 'text-text-muted')
  return (
    <div className={`mt-1 text-[13px] leading-snug text-text-faint ${side === 'out' ? 'text-right' : ''}`}>
      {outlook.short} attack <span className={`font-bold ${good(outlook.attack_rank)}`}>{ordinal(outlook.attack_rank)}</span>, defence{' '}
      <span className={`font-bold ${good(outlook.defence_rank)}`}>{ordinal(outlook.defence_rank)}</span> of {outlook.clubs} over six gameweeks
      {next && (
        <span className="tabular">
          {' '}&middot; next {next.home ? 'v' : 'at'} {next.opponent}: {next.xg_for.toFixed(1)} scored, {next.xg_against.toFixed(1)} conceded expected
        </span>
      )}
    </div>
  )
}

function PlayerSide({ p, side, fixtures, outlook }: { p: WeekPlanPlayer; side: 'out' | 'into'; fixtures?: FixtureContext; outlook?: WeekPlanPayload['team_outlook'] }) {
  const crest = crestUrl(p.team_code)
  const run = p.team_code !== null ? fixtures?.[String(p.team_code)] : undefined
  const rotation = p.start_percent !== null && p.start_percent < 70
  const solioGap = p.solio_next !== null ? p.xp_next - p.solio_next : null
  const disagree = side === 'into' && solioGap !== null && Math.abs(solioGap) >= 1
  const mirrored = side === 'out'

  return (
    <div className={`flex items-center gap-4 ${mirrored ? 'flex-row-reverse text-right' : ''}`}>
      <div className="relative shrink-0">
        <PlayerPhoto code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} className={side === 'into' ? 'h-24 w-[4.75rem]' : 'h-20 w-16'} muted={side === 'out'} />
        {crest && <img src={crest} alt="" className="absolute -bottom-1 -right-1 h-6 w-6 rounded-full bg-void ring-2 ring-void" />}
      </div>
      <div className="min-w-0">
        <Link
          to={`/player/${p.player_id}`}
          className={`block truncate font-display font-bold uppercase leading-none hover:text-pitch-green ${
            side === 'into' ? 'text-3xl text-text' : 'text-2xl text-text-muted'
          }`}
        >
          {p.name}
        </Link>
        <div className="mt-1 text-[13px] font-semibold uppercase tracking-wide text-text-faint">
          {p.team_short} &middot; {p.position} &middot; <span className="tabular">{money(p.price_tenths)}</span>
        </div>
        <ClubLine outlook={outlook?.[String(p.team_id)]} side={side} />
        <div className={`mt-1.5 flex items-baseline gap-1.5 ${mirrored ? 'justify-end' : ''}`}>
          <span className={`tabular font-bold ${side === 'into' ? 'text-2xl text-pitch-green' : 'text-xl text-text-muted'}`}>
            {p.xp_next.toFixed(1)}
          </span>
          <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">xP next GW</span>
        </div>
        <div className={`mt-1.5 flex flex-wrap items-center gap-1.5 ${mirrored ? 'justify-end' : ''}`}>
          {rotation && (
            <Tag tone={p.start_percent! < 40 ? 'red' : 'gold'} title="Predicted start probability from the team-news feed">
              {p.start_percent}% to start
            </Tag>
          )}
          {side === 'out' && p.price_trend === 'FALL_LIKELY' && (
            <Tag tone="red" title="Probability the price drops at tonight's overnight run, from the fitted price model">price falling{p.price_p_fall != null ? ` ${Math.round(p.price_p_fall * 100)}%` : ''}</Tag>
          )}
          {side === 'into' && p.price_trend === 'RISE_LIKELY' && (
            <Tag tone="gold" title="Probability the price rises at tonight's overnight run, from the fitted price model">price rising{p.price_p_rise != null ? ` ${Math.round(p.price_p_rise * 100)}%` : ''}</Tag>
          )}
          {(p.duties ?? []).length > 0 && (
            <Tag
              tone={side === 'out' && p.duties!.includes('penalties') ? 'red' : 'gold'}
              title={
                side === 'out'
                  ? 'First choice on these set pieces, per the FPL site. Selling him gives that up.'
                  : 'First choice on these set pieces, per the FPL site.'
              }
            >
              {p.duties!.map((d) => (d === 'penalties' ? 'pens' : d === 'free kicks' ? 'free kicks' : d)).join(' · ')}
            </Tag>
          )}
          {side === 'into' && (p.match_analysis_xp ?? 0) >= 0.3 && (
            <Tag tone="blue" title="Part of the projection comes from the match-analysis signal (a persistent trend over two or more matches), already counted in the xP shown">
              +{p.match_analysis_xp!.toFixed(1)} from match analysis
            </Tag>
          )}
          {p.luck && Math.abs(p.luck.z) >= 1.5 && (
            <Tag
              tone={p.luck.z > 0 ? 'gold' : 'blue'}
              title={`${p.luck.actual} points so far against ${p.luck.deserved.toFixed(0)} from the chances behind them (z ${p.luck.z.toFixed(1)})`}
            >
              {p.luck.z > 0 ? `+${p.luck.luck.toFixed(0)} lucky` : `${p.luck.luck.toFixed(0)} owed`}
            </Tag>
          )}
          {disagree && (
            <Tag tone="blue" title="Solio Analytics' independent projection for the same gameweek">
              Solio has {p.solio_next!.toFixed(1)}
            </Tag>
          )}
        </div>
        {p.analyst && (
          <Link to={`/match/${p.analyst.match_id}`} className={`mt-2 block max-w-xs border-l-2 pl-2 text-[12px] leading-snug text-text-muted hover:text-text ${mirrored ? 'ml-auto text-right' : ''} ${p.analyst.direction === 'NEGATIVE' ? 'border-alert-red' : p.analyst.direction === 'WATCH' ? 'border-broadcast-gold' : p.analyst.direction === 'POSITIVE' ? 'border-pitch-green' : 'border-divider'}`}>
            <span className="font-bold uppercase tracking-[0.08em] text-text-faint">{p.analyst.match}</span> {p.analyst.observed}
          </Link>
        )}
        {side === 'into' && run && (
          <div className="mt-2">
            <FixtureRun fixtures={run} max={4} showEvent />
          </div>
        )}
      </div>
    </div>
  )
}

function MoveRow({ m, horizon, maxGain, fixtures, outlook }: { m: WeekPlanMove; horizon: number; maxGain: number; fixtures?: FixtureContext; outlook?: WeekPlanPayload['team_outlook'] }) {
  return (
    <div className="data-in grid grid-cols-1 items-center gap-6 border-l-4 border-pitch-green bg-panel px-6 py-5 lg:grid-cols-[1fr_11rem_1fr]">
      <PlayerSide p={m.out} side="out" fixtures={fixtures} outlook={outlook} />
      <div className="flex flex-col items-center">
        <div className="tabular font-display text-5xl font-bold leading-none text-pitch-green">+{m.gain.toFixed(1)}</div>
        <div className="mt-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">pts over {horizon} GW</div>
        <div className="mt-2 h-1.5 w-full bg-raised">
          <div className="bar-draw h-full bg-pitch-green" style={{ width: `${Math.max(6, (m.gain / maxGain) * 100)}%` }} />
        </div>
        <div className="mt-2 flex items-center gap-1 text-text-faint">
          <span className="h-px w-8 bg-divider" />
          <span aria-hidden>&#9654;</span>
        </div>
        <div className="tabular mt-1 text-[12px] font-semibold text-text-faint">
          {m.cost_tenths > 0 ? `costs ${money(m.cost_tenths)}` : m.cost_tenths < 0 ? `frees ${money(-m.cost_tenths)}` : 'like for like'}
        </div>
        {m.timing && m.timing !== 'any' && (
          <div className="mt-2 max-w-[11rem] text-center">
            <Tag tone={m.timing === 'early' ? 'gold' : m.timing === 'late' ? 'blue' : 'red'} title={m.timing_note}>
              {m.timing === 'early' ? 'do early' : m.timing === 'late' ? 'wait for team news' : 'price vs news'}
            </Tag>
            <div className="mt-1 text-[12px] leading-snug text-text-faint">{m.timing_note}</div>
          </div>
        )}
      </div>
      <PlayerSide p={m.into} side="into" fixtures={fixtures} outlook={outlook} />
      <div className="border-t border-divider pt-3 lg:col-span-3">
        <Link to={`/compare?a=${m.out.player_id}&b=${m.into.player_id}`} className="float-right text-[12px] font-bold uppercase tracking-[0.1em] text-text-faint hover:text-text">Compare {m.out.name} and {m.into.name} &rarr;</Link>
        {(m.alternatives ?? []).length > 0 && (
          <>
            <span className="mr-4 text-[12px] font-bold uppercase tracking-[0.1em] text-text-faint">If not {m.into.name}</span>
            {m.alternatives!.map((a) => (
              <span key={a.into.player_id} className="mr-6 inline-block text-sm text-text-muted">
                <span className="font-semibold text-text">{a.into.name}</span>{' '}
                <span className="text-text-faint">({a.into.team_short}, {money(a.into.price_tenths)})</span>{' '}
                <span className="tabular font-bold text-pitch-green">+{a.gain.toFixed(1)}</span>
                <span className="text-text-faint"> in that slot over {horizon} GW</span>
              </span>
            ))}
          </>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, tone = 'text-text' }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div>
      <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">{label}</div>
      <div className={`tabular mt-0.5 font-display text-2xl font-bold leading-none ${tone}`}>{value}</div>
    </div>
  )
}

/** The moves as plain text, in the order to make them, for pasting into a note
 * or a message while the FPL transfers page is open. The app recommends and
 * never submits anything, so this is the closest it gets to the last step. */
function ChecklistActions({ plan }: { plan: WeekPlanPayload }) {
  const [copied, setCopied] = useState(false)
  const moves = plan.moves ?? []
  if (moves.length === 0) return null
  const text = [
    `GW${plan.event} transfers`,
    ...moves.map((m, i) => `${i + 1}. ${m.out.name} (${money(m.out.price_tenths)}) -> ${m.into.name} (${money(m.into.price_tenths)})`),
  ].join('\n')
  return (
    <div className="flex flex-wrap items-center gap-4 text-[13px] font-bold uppercase tracking-[0.1em]">
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard?.writeText(text).then(() => {
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
          })
        }}
        className="bg-raised px-2.5 py-1.5 text-text-muted hover:text-text"
      >
        {copied ? 'Copied' : 'Copy the moves'}
      </button>
      <a
        href="https://fantasy.premierleague.com/transfers"
        target="_blank"
        rel="noreferrer"
        className="text-text-faint hover:text-text"
      >
        Open the FPL transfers page &#8599;
      </a>
    </div>
  )
}

function ago(hours: number) {
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min ago`
  if (hours < 48) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}

/** THIS WEEK'S TRANSFERS - the decision, as the set of moves a manager would
 * actually make, each with what it earns.
 *
 * It replaces a hero that named a single swap and then argued with itself
 * about whether that swap was inside the noise. A manager holding five free
 * transfers is not choosing one swap or a roll; they are choosing how many of
 * the five to use and on whom, and rolling at the cap throws one away. */
export function WeekPlanHero({ plan, chips }: { plan: WeekPlanPayload; chips: string[] }) {
  const moves = plan.moves ?? []
  const declined = plan.declined ?? []
  const horizon = plan.horizon ?? 5
  const maxGain = Math.max(...moves.map((m) => m.gain), 1)
  const rolling = moves.length === 0
  const word = rolling ? 'Roll' : `${moves.length} transfer${moves.length === 1 ? '' : 's'}`
  const gw = `GW${plan.event}`
  const ft = plan.free_transfers ?? 0
  const stale = plan.status === 'stale'

  return (
    <section className="relative overflow-hidden bg-void pb-12 pt-10">
      <span className="ghost-watermark pointer-events-none absolute -right-10 -top-6 select-none font-display text-[22rem] font-bold uppercase leading-none">
        {gw}
      </span>

      <div className="relative px-10">
        <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
          <span className="font-mono text-[13px] uppercase tracking-[0.25em] text-text-faint">{gw} &middot; This week&apos;s transfers</span>
          {plan.computed_at && (
            <span className="font-mono text-[12px] uppercase tracking-[0.1em] text-text-faint">
              solved {ago(plan.age_hours ?? 0)} &middot; {plan.proven_optimal ? 'proven best plan' : 'best plan found, not proven'}
            </span>
          )}
        </div>

        {stale && (
          <div className="mt-4 max-w-2xl border-l-4 border-alert-red bg-panel px-4 py-3">
            <div className="text-[12px] font-bold uppercase tracking-[0.1em] text-alert-red">This plan is out of date</div>
            <ul className="mt-1 space-y-0.5 text-sm text-text-muted">
              {(plan.stale_reasons ?? []).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            <div className="mt-1 text-xs text-text-faint">
              The next scheduled sync rebuilds it, or run <code className="font-mono text-text">fpl week-plan</code> now. Treat the moves below as a
              guide to last sync&apos;s squad, not an instruction.
            </div>
          </div>
        )}

        <div className="verdict-block mt-5 inline-block bg-pitch-green py-5 pl-7 pr-16">
          <h1 className="font-display text-6xl font-bold uppercase leading-[0.88] text-pitch-green-ink md:text-7xl">{word}</h1>
        </div>

        <p className="mt-4 max-w-3xl text-lg leading-snug text-text-muted">
          {rolling ? (
            <>
              No transfer adds {plan.min_move_gain} points or more over {horizon} gameweeks.{' '}
              {ft >= 5
                ? 'You hold the maximum of five, so rolling still costs you one.'
                : `Rolling banks a free transfer: you will have ${Math.min(ft + 1, 5)} next week.`}
            </>
          ) : (
            <>
              <span className="tabular font-display text-3xl font-bold text-pitch-green">+{(plan.gain_vs_roll ?? 0).toFixed(1)}</span>{' '}
              points over the next {horizon} gameweeks, against rolling and making your moves next week. Uses {moves.length} of your {ft} free
              transfer{ft === 1 ? '' : 's'}.
            </>
          )}
        </p>

        {!rolling && !stale && (
          <div className="mt-6">
            <ChecklistActions plan={plan} />
          </div>
        )}

        <div className="mt-8 flex flex-wrap gap-x-10 gap-y-4 border-t border-divider pt-5">
          <Stat label="Free transfers now" value={ft} />
          <Stat label="After this plan" value={plan.ft_after ?? '—'} tone="text-pitch-green" />
          <Stat label="Bank now" value={money(plan.bank_tenths ?? 0)} />
          <Stat label="Bank after" value={money(plan.bank_after_tenths ?? 0)} tone="text-pitch-green" />
          {chips.length > 0 && <Stat label="Chips left" value={chips.join(' · ')} tone="text-broadcast-gold" />}
        </div>
      </div>

      {!rolling && (
        <div className="relative mt-10 space-y-px px-10">
          {moves.map((m) => (
            <MoveRow key={m.into.player_id} m={m} horizon={horizon} maxGain={maxGain} fixtures={plan.fixtures} outlook={plan.team_outlook} />
          ))}
        </div>
      )}

      {declined.length > 0 && (
        <div className="relative mt-4 px-10">
          {declined.map((m) => (
            <div key={m.into.player_id} className="flex flex-wrap items-baseline gap-x-3 border-l-4 border-divider bg-panel/60 px-6 py-3 text-sm text-text-muted">
              <span className="text-[12px] font-bold uppercase tracking-[0.1em] text-text-faint">Left out</span>
              <span className="font-semibold text-text">
                {m.out.name} &rarr; {m.into.name}
              </span>
              <span className="tabular">
                adds {m.gain >= 0 ? '+' : ''}
                {m.gain.toFixed(1)} over {horizon} GW, under the {plan.min_move_gain} a move has to earn
              </span>
            </div>
          ))}
        </div>
      )}

      {plan.affordability && !rolling && (
        <div className="relative mt-4 px-10 text-xs text-text-faint">{plan.affordability}</div>
      )}
      {(plan.notes ?? []).map((n) => (
        <div key={n} className="relative mt-1 px-10 text-xs text-text-faint">
          {n}
        </div>
      ))}
    </section>
  )
}
