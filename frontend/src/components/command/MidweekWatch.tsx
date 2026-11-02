import { Link } from 'react-router-dom'
import { crestUrl, getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** MIDWEEK WATCH: the squad's and the plan's targets' cup and European matches either side of today, read from FotMob's
 * lineups: who started, who came on, who was taken off and when, who was listed out. FPL sees none of it until the
 * press conference. A starter off before minute 36 is marked red: in league matches every one was injury-linked. */
interface CupPlayer {
  player_id: number; name: string | null; mine: boolean; role: 'STARTED' | 'BENCH' | 'UNAVAILABLE' | null
  minutes: number | null; sub_on_minute: number | null; sub_off_minute: number | null; goals: number | null; assists: number | null
  absent_kind: string | null; absent_return: string | null
}
interface CupMatch {
  fotmob_match_id: string; competition: string | null; team: string; team_code: number | null; opponent: string | null; is_home: boolean
  kickoff_utc: string; status: string; live_minute: string | null; score: [number, number] | null; players: CupPlayer[]
}
interface MidweekPayload { status: string; matches: CupMatch[]; events: { player_id: number; severity: string; fpl_impact: string }[] }

const SHORT: Record<string, string> = {
  'Champions League': 'UCL', 'Europa League': 'UEL', 'Conference League': 'UECL', 'FA Cup': 'FA CUP', 'EFL Cup': 'EFL CUP', 'League Cup': 'EFL CUP',
}

function Part({ p, played }: { p: CupPlayer; played: boolean }) {
  const base = 'inline-flex items-center gap-1 border-2 px-1.5 py-0.5 text-[12px] font-bold'
  const label = p.mine ? '' : ' opacity-70'
  if (!played || p.role === null) {
    return <Link to={`/player/${p.player_id}`} className={`${base} border-divider text-text-faint${label}`}>{p.name}</Link>
  }
  if (p.role === 'UNAVAILABLE') {
    return (
      <Link to={`/player/${p.player_id}`} className={`${base} border-alert-red bg-alert-red text-alert-red-ink${label}`} title={p.absent_return ?? undefined}>
        {p.name} <span className="font-display uppercase">out{p.absent_kind ? ` · ${p.absent_kind}` : ''}</span>
      </Link>
    )
  }
  const off = p.sub_off_minute
  const early = p.role === 'STARTED' && off !== null && off > 0 && off <= 35
  const tone = early ? 'border-alert-red bg-alert-red text-alert-red-ink' : p.role === 'STARTED' ? 'border-ink bg-paper text-text' : 'border-ink/40 bg-raised text-text-muted'
  const what = p.role === 'STARTED'
    ? off ? `off ${off}'` : `${p.minutes ?? 90}'`
    : p.sub_on_minute ? `on ${p.sub_on_minute}'` : 'unused'
  return (
    <Link to={`/player/${p.player_id}`} className={`${base} ${tone}${label}`}>
      {p.name} <span className="tabular font-display">{what}</span>
      {(p.goals ?? 0) > 0 && <span className="bg-broadcast-gold px-1 text-ink">{p.goals}G</span>}
      {(p.assists ?? 0) > 0 && <span className="bg-pitch-green px-1 text-paper">{p.assists}A</span>}
    </Link>
  )
}

export function MidweekWatch() {
  const state = useFetch(() => getJson<MidweekPayload>('/api/midweek'), [], 60000)
  if (state.status !== 'ready' || state.data.status !== 'ok' || state.data.matches.length === 0) return null
  const { matches } = state.data
  return (
    <section className="slab overflow-hidden !p-0">
      <div className="flex items-end justify-between gap-4 bg-ink px-6 py-4 text-paper">
        <div>
          <div className="font-display text-[12px] font-black uppercase tracking-[0.24em] text-spot">Midweek watch</div>
          <h2 className="font-display text-paper">Europe and the cups</h2>
        </div>
        <p className="max-w-[18rem] text-right text-[12px] leading-snug text-paper/60">FPL sees none of this until the press conference. Red: a starter off before minute 36.</p>
      </div>
      <div className="divide-y-2 divide-ink/10 px-6 py-2">
        {matches.map((m) => {
          const kick = new Date(m.kickoff_utc)
          const played = m.status !== 'PRE_MATCH'
          const live = m.status === 'LIVE' || m.status === 'HALFTIME'
          const crest = crestUrl(m.team_code)
          const ours = m.players.filter((p) => p.mine)
          const theirs = m.players.filter((p) => !p.mine)
          return (
            <div key={m.fotmob_match_id} className="py-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="bg-broadcast-blue px-1.5 py-0.5 font-display text-[11px] font-black uppercase tracking-[0.08em] text-paper">
                  {SHORT[m.competition ?? ''] ?? m.competition}
                </span>
                {crest && <img src={crest} alt="" className="size-5" onError={(e) => { e.currentTarget.style.display = 'none' }} />}
                <span className="font-display text-[17px] font-black uppercase text-text">
                  {m.is_home ? `${m.team} v ${m.opponent}` : `${m.opponent} v ${m.team}`}
                </span>
                <span className={`ml-auto tabular font-display text-[15px] font-black ${live ? 'text-alert-red' : 'text-text-muted'}`}>
                  {played && m.score ? `${m.score[0]}–${m.score[1]}` : ''}
                  {live ? ` · ${m.live_minute ?? 'live'}` : !played ? kick.toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) : ' FT'}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {ours.map((p) => <Part key={p.player_id} p={p} played={played} />)}
                {theirs.length > 0 && <span className="self-center text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">plan targets</span>}
                {theirs.map((p) => <Part key={p.player_id} p={p} played={played} />)}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
