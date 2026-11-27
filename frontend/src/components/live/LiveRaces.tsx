import { crestUrl, getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** The bonus race and defensive contributions, live (`/api/bonusrace`, every 20 seconds). Each match's BPS table as bars
 * against the last bonus place, your players marked and how many BPS each needs, with what a goal or an assist would add
 * by FPL's scoring; and each of your players the defensive-contribution rule applies to, his count against the line. */
interface Row { player_id: number; name: string; position: string; bps: number; bonus: number | null; confirmed: boolean; mine: boolean; starting: boolean
  minutes: number; to_bonus: number | null; goal_adds: number; assist_adds: number }
interface Match { fixture: number; home: string; away: string; home_code: number | null; away_code: number | null; finished: boolean
  score: [number | null, number | null]; bonus_line: number | null; top: Row[]; yours_below: Row[]; has_yours: boolean }
interface Defcon { player_id: number; name: string; position: string; count: number; threshold: number; reached: boolean; minutes: number; starting: boolean }
interface Payload { status: string; matches?: Match[]; defcon?: Defcon[] }

const BONUS_BG = ['', 'bg-broadcast-gold/40', 'bg-broadcast-gold/70', 'bg-broadcast-gold']

function MatchRace({ m }: { m: Match }) {
  const rows = [...m.top, ...m.yours_below]
  const max = Math.max(...rows.map((r) => r.bps), (m.bonus_line ?? 0) + 6, 10)
  return (
    <div className={`border-2 ${m.has_yours ? 'border-ink' : 'border-ink/30'} bg-paper p-3`}>
      <div className="mb-2 flex items-center gap-2 font-display text-lg font-black uppercase">
        {crestUrl(m.home_code) && <img src={crestUrl(m.home_code)!} alt="" className="size-5" />}{m.home}
        <span className="tabular">{m.score[0] ?? 0}–{m.score[1] ?? 0}</span>
        {m.away}{crestUrl(m.away_code) && <img src={crestUrl(m.away_code)!} alt="" className="size-5" />}
        <span className="ml-auto text-[11px] font-bold tracking-[0.14em] text-text-faint">{m.finished ? 'full time · bonus to confirm' : 'provisional'}</span>
      </div>
      <div className="space-y-1">
        {rows.map((r, i) => (
          <div key={r.player_id}>
            {i === m.top.length && m.yours_below.length > 0 && <div className="my-1 border-t border-dashed border-ink/30" />}
            <div className="grid grid-cols-[7.5rem_minmax(0,1fr)_2.2rem_2rem] items-center gap-2">
              <span className={`truncate text-[13px] ${r.mine ? 'font-black text-text' : 'text-text-muted'}`}>{r.mine && <span className="mr-1 text-spot">●</span>}{r.name}</span>
              <span className="relative h-3.5 bg-raised">
                <span className={`absolute inset-y-0 left-0 ${r.mine ? 'bg-spot' : r.bonus ? 'bg-ink/70' : 'bg-ink/30'}`} style={{ width: `${(Math.max(0, r.bps) / max) * 100}%` }} />
                {m.bonus_line != null && <span className="absolute inset-y-[-3px] w-[2px] bg-broadcast-gold" style={{ left: `${(m.bonus_line / max) * 100}%` }} title="last bonus place" />}
              </span>
              <span className="tabular text-right text-[13px] font-black">{r.bps}</span>
              {r.bonus ? <span className={`tabular text-center text-[12px] font-black ${BONUS_BG[r.bonus] ?? ''}`}>+{r.bonus}</span> : <span />}
            </div>
            {r.mine && !r.bonus && r.to_bonus != null && (
              <div className="ml-[8rem] text-[11.5px] text-text-muted">
                {r.to_bonus} BPS from a bonus point · a goal adds {r.goal_adds}, an assist {r.assist_adds}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function LiveRaces() {
  const st = useFetch(() => getJson<Payload>('/api/bonusrace'), [], 20000)
  if (st.status !== 'ready' || st.data.status !== 'ok') return null
  const d = st.data
  const matches = (d.matches ?? []).filter((m) => m.has_yours || !m.finished).slice(0, 6)
  const defcon = d.defcon ?? []
  if (!matches.length && !defcon.length) return null
  return (
    <section className="px-10 py-7">
      <h2 className="font-display text-text">Bonus and defensive points, live</h2>
      <p className="voice mt-1 text-[15px] text-text-muted">The gold line is the last bonus place in each match. Your players are in orange.</p>
      <div className="mt-4 grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="grid gap-3 lg:grid-cols-2">{matches.map((m) => <MatchRace key={m.fixture} m={m} />)}</div>
        {defcon.length > 0 && (
          <div className="border-2 border-ink bg-paper p-3">
            <div className="mb-2 font-display text-lg font-black uppercase">Defensive contribution</div>
            <div className="mb-3 text-[12px] text-text-faint">2 points at {defcon.find((x) => x.position === 'DEF')?.threshold ?? 10} for defenders, {defcon.find((x) => x.position === 'MID' || x.position === 'FWD')?.threshold ?? 12} for midfielders and forwards (tackles, interceptions, clearances, blocks; recoveries count beyond defence)</div>
            <div className="space-y-2">
              {defcon.map((x) => (
                <div key={x.player_id} className={x.minutes > 0 || x.starting ? '' : 'opacity-50'}>
                  <div className="flex items-baseline justify-between text-[13px]">
                    <span className="font-black text-text">{x.name} <span className="font-normal text-text-faint">{x.position}{x.starting ? '' : ' · bench'}</span></span>
                    <span className={`tabular font-black ${x.reached ? 'text-pitch-green' : 'text-text'}`}>{x.count}/{x.threshold}{x.reached ? ' · +2' : x.minutes > 0 ? ` · needs ${x.threshold - x.count}` : ''}</span>
                  </div>
                  <div className="mt-0.5 flex gap-[2px]">
                    {Array.from({ length: x.threshold }).map((_, i) => (
                      <span key={i} className={`h-2.5 flex-1 ${i < x.count ? (x.reached ? 'bg-pitch-green' : 'bg-spot') : 'bg-raised'}`} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
