import { Link } from 'react-router-dom'
import { crestUrl, getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { LivePointsByPlayer, LiveSquadPlayer, LiveThreat } from '@/lib/types'

/** THE MATCH RAIL: every fixture of the gameweek as a scorebug, in kickoff order and by day - kickoff time, live minute or
 * full time and the score - with your players in each and their live points; then the template players you do not own
 * who are scoring. Beside the live pitch on Live. */
interface Side { team_id: number; short: string; code: number | null }
interface Fixture { fixture_id: number; match_id: number | null; kickoff: string; status: string; minute: string | null; score: [number | null, number | null]; home: Side; away: Side }

function Crest({ code }: { code: number | null }) {
  const url = crestUrl(code)
  return url ? <img src={url} alt="" className="size-6 shrink-0" /> : <span className="size-6 shrink-0" />
}

export function MatchRail({ squad, byPlayer, threats }: { squad: LiveSquadPlayer[]; byPlayer: Map<number, LivePointsByPlayer>; threats: LiveThreat[] }) {
  const state = useFetch(() => getJson<{ event: number; fixtures: Fixture[] }>('/api/gwfixtures'), [], 20000)
  if (state.status !== 'ready') return null
  const days: Record<string, Fixture[]> = {}
  for (const f of state.data.fixtures) {
    const d = new Date(f.kickoff).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' })
    ;(days[d] ??= []).push(f)
  }
  return (
    <div className="space-y-4">
      {Object.entries(days).map(([day, list]) => (
        <div key={day}>
          <div className="mb-1 font-display text-[12px] font-black uppercase tracking-[0.14em] text-text-faint">{day}</div>
          <div className="space-y-1.5">
            {list.map((f) => {
              const mine = squad.filter((s) => s.team_code != null && (s.team_code === f.home.code || s.team_code === f.away.code))
              const live = f.status === 'LIVE' || f.status === 'HALFTIME'
              const done = f.status === 'FULL_TIME'
              const tile = (
                <div className={`border-2 border-ink ${live ? 'bg-ink text-paper shadow-[3px_3px_0_var(--alert-red,#d33)]' : mine.length ? 'bg-paper shadow-[3px_3px_0_var(--ink)]' : 'bg-paper/60'}`}>
                  <div className="grid grid-cols-[minmax(0,1fr)_4.2rem_minmax(0,1fr)] items-center gap-1 px-2 py-1.5">
                    <div className="flex min-w-0 items-center gap-1.5"><Crest code={f.home.code} /><span className="font-display text-[15px] font-black uppercase">{f.home.short}</span></div>
                    <div className="text-center">
                      {live || done ? (
                        <div className="tabular font-display text-xl font-black leading-none">{f.score[0] ?? 0}–{f.score[1] ?? 0}</div>
                      ) : (
                        <div className="tabular font-display text-[15px] font-black leading-none">{new Date(f.kickoff).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })}</div>
                      )}
                      <div className={`mt-0.5 text-[10px] font-black uppercase ${live ? 'text-alert-red' : 'text-text-faint'}`}>
                        {live ? <span className="inline-flex items-center gap-1"><span className="size-1.5 animate-pulse rounded-full bg-alert-red" />{f.status === 'HALFTIME' ? 'HT' : f.minute ?? 'live'}</span> : done ? 'FT' : 'KO'}
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center justify-end gap-1.5"><span className="font-display text-[15px] font-black uppercase">{f.away.short}</span><Crest code={f.away.code} /></div>
                  </div>
                  {mine.length > 0 && (
                    <div className={`flex flex-wrap gap-1 border-t px-2 py-1 ${live ? 'border-paper/20' : 'border-ink/15'}`}>
                      {mine.map((s) => {
                        const p = byPlayer.get(s.player_id)
                        const started = p && p.play_state !== 'yet_to_play'
                        const pts = started ? p!.points * (s.slot === 'bench' ? 1 : p!.multiplier) : null
                        return (
                          <span key={s.player_id} className={`inline-flex items-center gap-1 px-1 text-[11.5px] font-bold ${s.slot === 'bench' ? 'opacity-60' : ''}`}>
                            {s.is_captain && <span className="bg-broadcast-gold px-0.5 text-[9px] font-black text-ink">C</span>}
                            {s.web_name}
                            <span className={`tabular px-1 font-black ${pts == null ? 'text-text-faint' : pts > 0 ? 'bg-pitch-green text-paper' : 'bg-ink/20'}`}>{pts ?? '–'}</span>
                          </span>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
              return f.match_id ? <Link key={f.fixture_id} to={`/match/${f.match_id}`} className="block hover:-translate-y-px">{tile}</Link> : <div key={f.fixture_id}>{tile}</div>
            })}
          </div>
        </div>
      ))}
      {threats.filter((t) => t.points >= 3).length > 0 && (
        <div>
          <div className="mb-1 font-display text-[12px] font-black uppercase tracking-[0.14em] text-alert-red">Hurting you: template picks you don&apos;t own</div>
          <div className="space-y-1">
            {threats.filter((t) => t.points >= 3).slice(0, 6).map((t) => (
              <Link key={t.player_id} to={`/player/${t.player_id}`} className="flex items-center gap-2 border-2 border-ink bg-paper px-2 py-1 text-[13px] hover:bg-spot">
                <span className="tabular w-7 bg-alert-red text-center font-display font-black text-paper">{t.points}</span>
                <span className="font-display font-black uppercase">{t.web_name}</span>
                <span className="ml-auto text-[11px] text-text-faint">{t.ownership_percent.toFixed(0)}% owned</span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
