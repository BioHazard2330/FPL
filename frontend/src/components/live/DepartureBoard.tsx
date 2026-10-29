import { Flap } from '@/components/ui/Flap'
import { useCountdown } from '@/lib/clock'
import type { UpcomingMatch } from '@/lib/types'

/** DEPARTURES - the gameweek's remaining matches on a station split-flap board: kickoff, the tie, which of your players
 * travel with it and their expected points, and a remark (the armband, boarding inside 90 minutes, none of yours). The
 * clock in the corner counts to the first kickoff and flips every second. Reads the live snapshot's `upcoming` block. */

const pad2 = (n: number) => String(n).padStart(2, '0')
const plain = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ø/gi, 'o')

function remark(m: UpcomingMatch): string {
  const mins = (new Date(m.kickoff_time).getTime() - Date.now()) / 60000
  if (mins <= 90) return 'BOARDING'
  if (m.players.some((x) => x.is_captain && x.slot === 'starting')) return 'ARMBAND'
  if (m.players.some((x) => x.slot === 'starting')) return 'ON TIME'
  if (m.players.length) return 'BENCH ONLY'
  return ''
}

export function DepartureBoard({ matches }: { matches: UpcomingMatch[] }) {
  const first = useCountdown(matches[0]?.kickoff_time ?? null)
  const clock = first && !first.expired
    ? `${first.days > 0 ? `${first.days}D ` : ''}${pad2(first.hours)}:${pad2(first.minutes)}:${pad2(first.seconds)}`
    : 'KICKOFF'
  return (
    <div className="border-2 border-ink bg-[#0e0f12] p-5 shadow-[6px_6px_0_var(--spot)]">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-4">
        <div>
          <div className="font-display text-[13px] font-black uppercase tracking-[0.3em] text-[#ffc400]">Departures · GW{matches[0]?.event}</div>
          <div className="mt-1 text-[12px] uppercase tracking-[0.14em] text-white/45">your eleven, by kickoff</div>
        </div>
        <div className="text-right">
          <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.16em] text-white/45">first kickoff in</div>
          <Flap text={clock} width={11} className="text-[2.4rem]" stagger={0} />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-[auto_auto_minmax(0,1fr)_auto_auto] items-center gap-x-5 gap-y-2 text-[1.35rem]">
        {['time', 'match', 'your players', 'xp', 'remarks'].map((h) => (
          <div key={h} className="text-[11px] font-bold uppercase tracking-[0.16em] text-white/40">{h}</div>
        ))}
        {matches.map((m, i) => {
          const k = new Date(m.kickoff_time)
          const when = `${k.toLocaleDateString('en-GB', { weekday: 'short' })} ${pad2(k.getHours())}:${pad2(k.getMinutes())}`
          const starters = m.players.filter((x) => x.slot === 'starting')
          const names = [...(starters.length ? starters : m.players)].sort((a, b) => Number(b.is_captain) - Number(a.is_captain)).map((x) => (x.is_captain ? `${plain(x.web_name)}·C` : plain(x.web_name))).join(' ')
          const xp = starters.reduce((s, x) => s + (x.xp ?? 0) * (x.is_captain ? 2 : 1), 0)
          const r = remark(m)
          return [
            <Flap key={`t${i}`} text={when} width={9} stagger={22} />,
            <Flap key={`m${i}`} text={`${m.home} V ${m.away}`} width={9} stagger={22} />,
            <span key={`p${i}`} className="min-w-0 overflow-hidden" title={m.players.map((x) => x.web_name).join(', ')}>
              <Flap text={names} width={28} stagger={14} className={`text-[0.7em] ${starters.length ? '' : 'opacity-45'}`} />
            </span>,
            <Flap key={`x${i}`} text={starters.length ? xp.toFixed(1) : ''} width={4} stagger={22} />,
            <span key={`r${i}`} className={r === 'BOARDING' ? 'animate-pulse text-[#ff4614]' : r === 'ARMBAND' ? 'text-[#ffc400]' : ''}>
              <Flap text={r} width={10} stagger={22} className={r === 'ARMBAND' ? '[&_.flap]:!text-[#ffc400]' : r === 'BOARDING' ? '[&_.flap]:!text-[#ff4614]' : ''} />
            </span>,
          ]
        })}
      </div>
    </div>
  )
}
