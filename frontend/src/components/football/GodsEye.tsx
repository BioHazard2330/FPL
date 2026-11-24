import { Link } from 'react-router-dom'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** GOD'S EYE on a player page (`models/gods_eye.py`): the pundit's call, his role and its history, his profile against
 * players in the same role, his set-piece duties, how his manager uses him, and a read of each recent match. */
interface Stat { per90: number; pct: number; peers: number }
interface Payload {
  status: string; usual_role: string; role_change: { from: string; to: string } | null; judgement: string | null
  strip: { match_id: number; opponent: string; started?: boolean; slot: string | null; minutes: number; rating: number | null; goals: number; assists: number }[]
  profile: Record<string, Stat>; defcon: { hits: number; matches: number } | null
  duties: { corners: number; corner_share: number | null; penalties: number; free_kicks: number }
  manager: { first_off: { times: number; usual_minute: number } | null; typical_off: number | null; security: string | null; starts: string | null
    covered_by: { name: string; player_id: number }[]; covers_for: string[] }
  reads: { match_id: number; opponent: string; where: string; rating: number | null; read: string }[]
}

const LABEL: Record<string, string> = {
  touches_opp_box: 'Box touches', total_shots: 'Shots', chances_created: 'Chances created', expected_assists: 'xA', accurate_crosses: 'Crosses',
  passes_into_final_third: 'Final-third passes', line_breaking_passes: 'Line-breaking passes', dribbles_succeeded: 'Dribbles',
  recoveries: 'Recoveries', cbit: 'Clearances, blocks, interceptions, tackles',
}
const SLOT: Record<string, string> = { GK: 'GK', CB: 'CB', 'FB-L': 'LB', 'FB-R': 'RB', 'WB-L': 'LWB', 'WB-R': 'RWB', DM: 'DM', CM: 'CM', AM: '10', 'W-L': 'LW', 'W-R': 'RW', ST: 'ST' }

export function GodsEye({ playerId }: { playerId: number }) {
  const state = useFetch(() => getJson<Payload>(`/api/godseye?player=${playerId}`), [playerId])
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  const m = d.manager
  return (
    <section className="border-b border-divider px-10 py-8">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="font-display text-text">God&apos;s eye</h2>
        <span className="font-display text-xl font-black uppercase text-spot">{d.usual_role}</span>
        {d.role_change && <span className="bg-spot px-2 font-display text-[13px] font-black uppercase text-ink">New role: {SLOT[d.role_change.from] ?? d.role_change.from} → {SLOT[d.role_change.to] ?? d.role_change.to}</span>}
      </div>
      {d.judgement && <div className="mt-2 max-w-3xl border-l-4 border-spot pl-3 text-[16px] font-semibold leading-snug text-text">{d.judgement}</div>}

      <div className="mt-4 flex gap-1 overflow-x-auto">
        {d.strip.map((s) => (
          <Link key={s.match_id} to={`/match/${s.match_id}`} className="w-16 shrink-0 border-2 border-ink bg-paper text-center hover:bg-spot">
            <div className="bg-ink font-display text-[11px] font-black uppercase text-paper">{s.opponent}</div>
            <div className={`font-display text-lg font-black ${s.started === false ? 'text-alert-red' : 'text-text'}`}>{s.started === false ? 'SUB' : s.slot ? SLOT[s.slot] ?? s.slot : '-'}</div>
            <div className="tabular text-[11px] text-text/70">{s.minutes}&apos; · {s.rating?.toFixed(1) ?? '-'}</div>
            <div className="h-4 text-[10.5px] font-black uppercase text-pitch-green">{s.goals ? `${s.goals}G ` : ''}{s.assists ? `${s.assists}A` : ''}</div>
          </Link>
        ))}
      </div>

      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div>
          <div className="font-display text-xl font-black uppercase text-text">Against every {d.usual_role}</div>
          <div className="mt-2 space-y-1.5">
            {Object.entries(d.profile).filter(([k]) => k in LABEL).sort((a, b) => b[1].pct - a[1].pct).map(([k, s]) => (
              <div key={k} className="grid grid-cols-[12rem_minmax(0,1fr)_3.2rem_2.4rem] items-center gap-2 text-[13px]">
                <span className="truncate font-bold uppercase text-text/75" title={LABEL[k] ?? k}>{LABEL[k] ?? k}</span>
                <span className="relative h-4 border-2 border-ink bg-paper">
                  <span className={`block h-full ${s.pct >= 80 ? 'bg-pitch-green' : s.pct <= 20 ? 'bg-alert-red' : 'bg-ink'}`} style={{ width: `${Math.max(2, s.pct)}%` }} />
                </span>
                <span className="tabular text-right font-black text-text">{s.per90}</span>
                <span className="tabular text-right text-[11.5px] text-text/60">{s.pct}</span>
              </div>
            ))}
          </div>
          <div className="mt-1 text-[11.5px] text-text/60">Per 90, percentile among players who usually play {d.usual_role} ({Object.values(d.profile)[0]?.peers ?? 0}, 270+ minutes).</div>
        </div>
        <div className="space-y-3 text-[13.5px]">
          <div className="font-display text-xl font-black uppercase text-text">Duties and his manager</div>
          <div><b className="font-display uppercase">Set pieces:</b> {d.duties.corners} corners{d.duties.corner_share != null && d.duties.corners > 0 ? ` (${Math.round(d.duties.corner_share * 100)}% of the club's)` : ''} · {d.duties.penalties} penalties · {d.duties.free_kicks} direct free kicks</div>
          {d.defcon && <div><b className="font-display uppercase">Defensive contribution:</b> reached in {d.defcon.hits} of {d.defcon.matches} matches of 60+</div>}
          <div><b className="font-display uppercase">Selection:</b> started {m.starts ?? '-'} · {m.security ?? '-'}{m.typical_off != null ? ` · usually off around ${m.typical_off}'` : ' · plays the full match'}{m.first_off ? ` · first off ${m.first_off.times} times` : ''}</div>
          {m.covered_by.length > 0 && <div><b className="font-display uppercase">If he is out:</b> {m.covered_by.map((c) => c.name).join(', ')}</div>}
          {m.covers_for.length > 0 && <div><b className="font-display uppercase">He comes in for:</b> {m.covers_for.join(', ')}</div>}
        </div>
      </div>

      <div className="mt-6">
        <div className="font-display text-xl font-black uppercase text-text">How he played</div>
        <div className="mt-2 divide-y divide-ink/15 border-y-2 border-ink">
          {d.reads.map((r) => (
            <div key={r.match_id} className="grid grid-cols-[3.5rem_9rem_minmax(0,1fr)_3rem] items-baseline gap-3 py-1.5 text-[13.5px]">
              <Link to={`/match/${r.match_id}`} className="font-display font-black uppercase text-text hover:underline">{r.opponent}</Link>
              <span className="text-text/60">{r.where}</span>
              <span className="font-semibold text-text">{r.read}</span>
              <span className="tabular text-right font-black text-text">{r.rating?.toFixed(1) ?? ''}</span>
            </div>
          ))}
        </div>
        <div className="mt-1 text-[11.5px] text-text/60">Each match against his own per-90 numbers: what was 1.6 times his usual or more, or under half.</div>
      </div>
    </section>
  )
}
