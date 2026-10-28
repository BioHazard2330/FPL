import { Link } from 'react-router-dom'
import { fetchLeagues } from '@/lib/api'
import { formatCountdown, useCountdown } from '@/lib/clock'
import { useFetch } from '@/lib/useFetch'
import { useLiveMeta } from '@/lib/useLiveMeta'
import type { WeekPlanPayload } from '@/lib/types'

/** THE MATCHDAY BUG: the week's call and the season's state in one strip across the top of Command, the way a broadcast
 * opens on the scoreboard before anything else. The call sits on an angled pitch-green slab; the clock, the rank, the
 * points and the mini-league race sit beside it as oversized figures. Every number is one the page already holds: the
 * stored plan, the live poll's gameweek series, the mini-league odds. */
function Figure({ label, value, sub, tone = 'text-text' }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="min-w-0 px-7 py-5">
      <div className="text-[11.5px] font-semibold uppercase tracking-[0.14em] text-text-faint">{label}</div>
      <div className={`mt-1.5 font-display text-[2.6rem] font-bold leading-none tabular ${tone}`}>{value}</div>
      {sub && <div className="mt-2 line-clamp-2 text-[13px] leading-snug text-text-muted">{sub}</div>}
    </div>
  )
}

export function MatchdayHeader({ plan }: { plan: WeekPlanPayload }) {
  const live = useLiveMeta()
  const countdown = useCountdown(live?.gw?.next_deadline_time ?? null)
  const leagues = useFetch(fetchLeagues, [], 300000)
  const gw = live?.charts?.gw_points
  const ranks = (live?.charts?.rank?.values ?? []).filter((v): v is number => v !== null)
  const rank = ranks[ranks.length - 1]
  const prevRank = ranks[ranks.length - 2]
  const total = gw ? gw.you.reduce((a, b) => a + b, 0) : null
  const last = gw ? gw.you[gw.you.length - 1] : null
  const lastAvg = gw ? gw.average[gw.average.length - 1] : null
  const fmtRank = (v: number) => (v >= 1_000_000 ? `${(v / 1_000_000).toFixed(2)}m` : v >= 1000 ? `${Math.round(v / 1000)}k` : `${v}`)

  const moves = plan.moves ?? []
  const call = moves.length === 0 ? 'Roll' : moves.length === 1 ? '1 transfer' : `${moves.length} transfers`
  const callSub = moves.length === 0
    ? `${plan.free_transfers ?? 0} free transfer${plan.free_transfers === 1 ? '' : 's'} · ${Math.min((plan.free_transfers ?? 0) + 1, 5)} next week`
    : `+${(plan.gain_vs_roll ?? 0).toFixed(1)} over ${plan.horizon ?? 5} GWs against rolling`

  const race = leagues.status === 'ready'
    ? leagues.data.leagues.filter((l) => l.odds?.p_lead != null).sort((a, b) => (b.odds?.p_lead ?? 0) - (a.odds?.p_lead ?? 0))[0]
    : undefined
  const captain = plan.captain?.best?.name

  return (
    <section className="bare !overflow-visible">
      <div className="grid grid-cols-[minmax(0,1.15fr)_repeat(4,minmax(0,1fr))] items-stretch overflow-hidden rounded-md bg-panel shadow-[inset_0_1px_0_0_rgba(237,240,245,0.07),0_22px_44px_-26px_rgba(0,0,0,0.9)]">
        <div className="verdict-block relative bg-pitch-green px-8 py-5 pr-16 text-pitch-green-ink">
          <div className="text-[11.5px] font-bold uppercase tracking-[0.16em] opacity-70">GW{plan.event} · the call</div>
          <div className="mt-1 font-display text-[3.4rem] font-bold uppercase leading-[0.9]">{call}</div>
          <div className="mt-2 text-[13px] font-semibold opacity-80">
            {callSub}
            {captain && <> · armband {captain}</>}
          </div>
        </div>
        <Figure
          label="Deadline"
          value={countdown && !countdown.expired ? formatCountdown(countdown) : '—'}
          tone={countdown && countdown.totalMs < 6 * 3600_000 ? 'text-alert-red' : 'text-text'}
          sub={live?.gw?.next_deadline_time ? new Date(live.gw.next_deadline_time).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : undefined}
        />
        <Figure
          label="Overall rank"
          value={rank ? fmtRank(rank) : '—'}
          sub={rank && prevRank ? (
            <span className={rank < prevRank ? 'text-pitch-green' : rank > prevRank ? 'text-alert-red' : ''}>
              {rank < prevRank ? '▲' : rank > prevRank ? '▼' : '='} {fmtRank(Math.abs(prevRank - rank))} last gameweek
            </span>
          ) : undefined}
        />
        <Figure
          label="Season points"
          value={total ?? '—'}
          sub={last !== null ? <>GW{gw?.events[gw.events.length - 1]}: <span className="font-semibold text-text">{last}</span>{lastAvg !== null && lastAvg !== undefined ? <> against {lastAvg} average</> : null}</> : undefined}
        />
        {race ? (
          <Link to="/leagues" className="block hover:bg-raised/40">
            <Figure
              label="Mini-league race"
              value={`${Math.round((race.odds?.p_lead ?? 0) * 100)}%`}
              tone={(race.odds?.p_lead ?? 0) >= 0.5 ? 'text-pitch-green' : (race.odds?.p_lead ?? 0) >= 0.2 ? 'text-broadcast-gold' : 'text-text'}
              sub={<>to lead {race.name} after GW{plan.event}</>}
            />
          </Link>
        ) : (
          <Figure label="Mini-league race" value="—" sub="no fully followed league" />
        )}
      </div>
    </section>
  )
}
