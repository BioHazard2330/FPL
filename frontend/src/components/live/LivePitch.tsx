import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import type { BonusDefconRow, LiveMatchEvent, LivePointsByPlayer, LiveSquadPlayer, UpcomingMatch } from '@/lib/types'

/** YOUR ELEVEN, LIVE: the starting eleven on a pitch in its formation, each player a card with his live points (with the
 * armband), whether he is playing now, done or still to play (and when), goals, assists, provisional bonus and progress
 * to the defensive-contribution threshold; the bench beneath in order. Everything is read from the live snapshot. */
interface Props {
  squad: LiveSquadPlayer[]
  byPlayer: Map<number, LivePointsByPlayer>
  bonus: BonusDefconRow[]
  events: LiveMatchEvent[]
  upcoming: UpcomingMatch[]
}

const ROWS = ['GKP', 'DEF', 'MID', 'FWD'] as const

function kickoffFor(pid: number, upcoming: UpcomingMatch[]): string | null {
  const m = upcoming.find((u) => u.players.some((p) => p.player_id === pid))
  if (!m) return null
  const t = new Date(m.kickoff_time)
  return `${t.toLocaleDateString([], { weekday: 'short' })} ${t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })} · ${m.home}-${m.away}`
}

function Card({ s, live, b, goals, assists, kickoff, bench }: {
  s: LiveSquadPlayer; live?: LivePointsByPlayer; b?: BonusDefconRow; goals: number; assists: number; kickoff: string | null; bench?: boolean
}) {
  const state = live?.play_state ?? 'yet_to_play'
  const started = state !== 'yet_to_play'
  const pts = started && live ? live.points * (bench ? 1 : live.multiplier) : null
  const bonus = b?.provisional_bonus ?? b?.confirmed_bonus ?? 0
  const flagged = s.classification && s.classification !== 'FIT'
  const box = state === 'live' ? 'bg-alert-red text-paper' : started ? 'bg-ink text-paper' : 'bg-paper text-ink/60 border-2 border-ink'
  return (
    <Link to={`/player/${s.player_id}`} className={`group relative flex w-[7.6rem] flex-col items-center ${bench ? 'opacity-80' : ''}`}>
      <div className="relative">
        <PlayerPhoto code={s.photo_code ?? null} teamCode={s.team_code ?? null} isGkp={s.position === 'GKP'} className="h-[4.6rem] w-16" />
        {(s.is_captain || s.is_vice) && (
          <span className={`absolute -left-2 top-0 flex size-6 items-center justify-center border-2 border-ink font-display text-[12px] font-black ${s.is_captain ? 'bg-broadcast-gold text-ink' : 'bg-paper text-ink'}`}>{s.is_captain ? 'C' : 'V'}</span>
        )}
        {state === 'live' && <span className="absolute -right-1.5 top-0 size-3 animate-pulse rounded-full border-2 border-paper bg-alert-red" title="Playing now" />}
        {flagged && <span className="absolute -right-2 bottom-1 border border-ink bg-broadcast-gold px-1 text-[9px] font-black uppercase text-ink" title={s.news ?? ''}>!</span>}
      </div>
      <div className="w-full border-2 border-ink bg-paper px-1 text-center font-display text-[13px] font-black uppercase leading-tight text-ink group-hover:bg-spot">
        <span className="block truncate">{s.web_name}</span>
      </div>
      <div className={`tabular w-full text-center font-display text-xl font-black leading-tight ${box}`}>
        {pts !== null ? pts : s.xp !== null ? <span className="text-[13px]">{s.xp.toFixed(1)} xP</span> : '-'}
      </div>
      <div className="mt-0.5 flex min-h-[1.1rem] flex-wrap items-center justify-center gap-0.5 text-[10px] font-black uppercase">
        {goals > 0 && <span className="bg-pitch-green px-1 text-paper">{goals > 1 ? `${goals}×` : ''}Goal</span>}
        {assists > 0 && <span className="bg-broadcast-gold px-1 text-ink">{assists > 1 ? `${assists}×` : ''}Ast</span>}
        {bonus > 0 && <span className="bg-spot px-1 text-ink">+{bonus} bonus</span>}
        {b?.defcon_reached && <span className="bg-ink px-1 text-paper">Defcon</span>}
        {!b?.defcon_reached && b?.defensive_contribution != null && b.defcon_threshold && (b.minutes ?? 0) > 0 && (
          <span className="text-paper/90 [text-shadow:0_1px_0_rgba(0,0,0,0.6)]">DC {b.defensive_contribution}/{b.defcon_threshold}</span>
        )}
      </div>
      <div className="text-center text-[10.5px] font-semibold leading-tight text-paper [text-shadow:0_1px_0_rgba(0,0,0,0.7)]">
        {state === 'live' ? `${b?.minutes ?? ''}' playing` : started ? `${b?.minutes ?? ''}' done` : kickoff ?? 'to play'}
      </div>
    </Link>
  )
}

export function LivePitch({ squad, byPlayer, bonus, events, upcoming }: Props) {
  const bonusBy = new Map(bonus.map((b) => [b.player_id, b]))
  const count = (pid: number, kind: string) => events.filter((e) => e.player_id === pid && e.kind === kind).reduce((n, e) => n + e.count, 0)
  const starting = squad.filter((s) => s.slot === 'starting')
  const bench = squad.filter((s) => s.slot === 'bench')
  const card = (s: LiveSquadPlayer, onBench = false) => (
    <Card key={s.player_id} s={s} live={byPlayer.get(s.player_id)} b={bonusBy.get(s.player_id)} goals={count(s.player_id, 'goal')}
      assists={count(s.player_id, 'assist')} kickoff={kickoffFor(s.player_id, upcoming)} bench={onBench} />
  )
  return (
    <div className="border-2 border-ink shadow-[6px_6px_0_var(--ink)]">
      <div className="relative overflow-hidden px-4 pb-4 pt-5" style={{ background: 'repeating-linear-gradient(0deg, #1f7a3a 0 44px, #23863f 44px 88px)' }}>
        <svg viewBox="0 0 68 60" className="pointer-events-none absolute inset-0 h-full w-full" preserveAspectRatio="none" aria-hidden="true">
          <g fill="none" stroke="white" strokeOpacity="0.35" strokeWidth="0.35">
            <rect x="1" y="1" width="66" height="58" /><rect x="18" y="1" width="32" height="12" /><rect x="26" y="1" width="16" height="4.5" />
            <path d="M 25 59 A 9 9 0 0 1 43 59" />
          </g>
        </svg>
        <div className="relative space-y-3">
          {ROWS.map((pos) => {
            const row = starting.filter((s) => s.position === pos)
            return row.length ? <div key={pos} className="flex justify-center gap-3">{row.map((s) => card(s))}</div> : null
          })}
        </div>
      </div>
      <div className="flex flex-wrap items-start justify-center gap-3 border-t-2 border-ink bg-ink/85 px-4 py-3">
        <span className="self-center font-display text-[12px] font-black uppercase tracking-[0.14em] text-paper/70">Bench</span>
        {bench.map((s) => card(s, true))}
      </div>
    </div>
  )
}
