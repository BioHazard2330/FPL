import { getJson } from '@/lib/api'
import { Info } from '@/components/ui/Info'
import { useFetch } from '@/lib/useFetch'

/** THE CHIP CALENDAR: all 38 gameweeks on one strip - blanks and doubles as FPL schedules them (with how many of your
 * fifteen they touch), the chips you played, the plan's best week for each chip still in hand, and how the managers
 * ranked around 10,000 played theirs. The halves are split at GW19/20, where the second set of chips arrives. */

interface Week { event: number; fixtures: number; blank: string[]; double: string[]; squad_blank: number; squad_double: number; finished: boolean; chip: string | null; cohort: Record<string, number> }
interface Window { name: string; start_event: number; stop_event: number; used: number | null }
interface ChipsPayload {
  status: string; weeks: Week[]; windows: Window[]; unscheduled: { home: string; away: string }[]
  plan_best: Record<string, { event: number | null; worth: number | null }>; cohort_held_first_half: Record<string, number>; announced: boolean
}

const ABBR: Record<string, string> = { wildcard: 'WC', freehit: 'FH', bboost: 'BB', '3xc': 'TC' }
const NAME: Record<string, string> = { wildcard: 'Wildcard', freehit: 'Free hit', bboost: 'Bench boost', '3xc': 'Triple captain' }
const TONE: Record<string, string> = { wildcard: 'bg-broadcast-blue text-paper', freehit: 'bg-pitch-green text-paper', bboost: 'bg-broadcast-gold text-ink', '3xc': 'bg-alert-red text-paper' }

export function ChipCalendar() {
  const state = useFetch(() => getJson<ChipsPayload>('/api/chips'), [])
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  const best = new Map(Object.entries(d.plan_best).map(([chip, b]) => [b.event, chip]))
  const halves = [1, 20].map((start) => d.windows.filter((w) => w.start_event <= start + 1 && w.stop_event >= start + 1))
  return (
    <section className="px-10 py-8">
      <div className="voice text-lg text-text-muted">every gameweek of the season, and the chips across it</div>
      <h2 className="font-display text-text">The chip calendar</h2>
      <div className="mt-5 pb-2">
        <div className="grid gap-[3px]" style={{ gridTemplateColumns: 'repeat(38, minmax(0, 1fr))' }}>
          {d.weeks.map((w) => {
            const plan = best.get(w.event)
            const cohort = Object.entries(w.cohort).sort((a, b) => b[1] - a[1])
            return (
              <div key={w.event} className={`flex flex-col items-stretch ${w.event === 20 ? 'relative before:absolute before:-left-[3px] before:-top-1 before:-bottom-1 before:w-[3px] before:bg-ink' : ''}`}>
                <div className={`text-center font-display text-[11px] font-black ${w.finished ? 'text-text-faint' : 'text-text'}`}>{w.event}</div>
                <div className={`relative flex h-14 flex-col items-center justify-center border-2 ${w.blank.length ? 'border-alert-red bg-[repeating-linear-gradient(45deg,var(--alert-red)_0_3px,transparent_3px_7px)]' : w.double.length ? 'border-broadcast-gold bg-broadcast-gold/25' : w.finished ? 'border-ink/20 bg-raised' : 'border-ink/40 bg-paper'}`}
                  title={[w.blank.length ? `blank: ${w.blank.join(', ')}` : '', w.double.length ? `double: ${w.double.join(', ')}` : ''].filter(Boolean).join(' · ') || `${w.fixtures} fixtures`}>
                  {w.chip && <span className={`px-1 font-display text-[12px] font-black ${TONE[w.chip]}`}>{ABBR[w.chip]}</span>}
                  {!w.chip && plan && <span className="border-2 border-dashed border-ink px-1 font-display text-[11px] font-black text-ink">{ABBR[plan]}?</span>}
                  {w.blank.length > 0 && <span className="mt-0.5 bg-paper px-0.5 font-display text-[10px] font-black text-alert-red">B{w.blank.length}</span>}
                  {w.double.length > 0 && <span className="mt-0.5 font-display text-[10px] font-black text-ink">D{w.double.length}</span>}
                </div>
                <div className="mt-[3px] flex h-8 flex-col-reverse border border-ink/15 bg-paper">
                  {cohort.map(([c, s]) => <div key={c} className={TONE[c]?.split(' ')[0]} style={{ height: `${Math.min(1, s) * 100}%` }} title={`${Math.round(s * 100)}% of the 10k played ${NAME[c]}`} />)}
                </div>
                {(w.squad_blank > 0 || w.squad_double > 0) && (
                  <div className="text-center text-[10px] font-bold text-text-muted">{w.squad_blank ? `−${w.squad_blank}` : `+${w.squad_double}`}</div>
                )}
              </div>
            )
          })}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">
        <Info label="Reading the calendar">
          <p>Top row: the gameweek (filled: the chip you played; dashed: the plan's best week for a chip in hand).</p>
          <p>Bottom row: share of the 10k who played each chip.</p>
          <p>{d.announced ? 'Blanks and doubles are as FPL has scheduled them.' : 'No blank or double gameweek is scheduled yet; they appear the cycle after FPL moves fixtures.'}</p>
        </Info>
        <span className="text-alert-red">hatched blank</span><span className="text-broadcast-gold">gold double</span>
        <span>dashed: best week</span>
      </div>
      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
        {halves.map((ws, i) => (
          <div key={i} className="border-2 border-ink bg-paper p-4 shadow-[4px_4px_0_var(--ink)]">
            <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-text-faint">{i === 0 ? 'first half · GW1–19' : 'second half · GW20–38'}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {ws.map((w) => (
                <span key={`${w.name}-${w.start_event}`} className={`border-2 border-ink px-2 py-0.5 font-display text-[14px] font-black ${w.used ? 'bg-raised text-text-faint line-through' : TONE[w.name]}`}>
                  {NAME[w.name]}{w.used ? ` GW${w.used}` : ''}
                </span>
              ))}
            </div>
          </div>
        ))}
        <div className="border-2 border-ink bg-paper p-4 shadow-[4px_4px_0_var(--ink)]">
          <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-text-faint">the 10k, first-half chips still in hand</div>
          <div className="mt-2 grid grid-cols-4 gap-2">
            {Object.entries(d.cohort_held_first_half).map(([c, s]) => (
              <div key={c}>
                <div className="tabular font-display text-2xl font-black text-text">{Math.round(s * 100)}%</div>
                <div className="text-[11px] text-text-muted">{NAME[c]}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {d.unscheduled.length > 0 && <div className="mt-4 text-[12.5px] text-text-muted">unscheduled: {d.unscheduled.map((u) => `${u.home} v ${u.away}`).join(', ')}</div>}
    </section>
  )
}
