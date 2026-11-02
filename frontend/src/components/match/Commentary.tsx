import { useState } from 'react'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** COMMENTARY: the Premier League's own text commentary for the match, newest first, refreshed every 30 seconds while
 * it is on. Goals, cards, substitutions and whistles are marked; the rest is the play as the league wrote it. */
interface Event { type: string | null; minute: string | null; text: string }
interface CommentaryPayload { status: string; live?: boolean; events?: Event[] }

function mark(type: string | null) {
  const t = (type ?? '').toLowerCase()
  if (t.includes('goal') && !t.includes('attempt')) return { label: 'GOAL', tone: 'bg-broadcast-gold text-ink' }
  if (t.includes('red')) return { label: 'RED', tone: 'bg-alert-red text-alert-red-ink' }
  if (t.includes('yellow')) return { label: 'YC', tone: 'bg-[#ffd400] text-ink' }
  if (t.includes('substitution')) return { label: 'SUB', tone: 'bg-broadcast-blue text-paper' }
  if (t.includes('penalty')) return { label: 'PEN', tone: 'bg-spot text-ink' }
  if (t.includes('end') || t.includes('start') || t.includes('kick off')) return { label: 'WHISTLE', tone: 'bg-ink text-paper' }
  if (t.includes('var')) return { label: 'VAR', tone: 'bg-ink text-paper' }
  return null
}

export function Commentary({ fixtureId, live }: { fixtureId: number; live: boolean }) {
  const state = useFetch(() => getJson<CommentaryPayload>(`/api/commentary?fixture=${fixtureId}`), [fixtureId], live ? 30000 : undefined)
  const [all, setAll] = useState(false)
  if (state.status !== 'ready' || state.data.status !== 'ok' || !(state.data.events ?? []).length) return null
  const events = state.data.events!
  const keyOnly = events.filter((e) => mark(e.type))
  const shown = all ? events : keyOnly.length >= 4 ? keyOnly : events.slice(0, 25)
  return (
    <div className="border-b border-divider px-10 py-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <div className="text-[13px] font-bold text-pitch-green">The commentary{live ? ' · live' : ''}</div>
          <h2 className="font-display text-[1.75rem] font-semibold leading-tight text-text">As the league called it</h2>
        </div>
        <button type="button" onClick={() => setAll((v) => !v)} className="border-2 border-ink bg-paper px-3 py-1 font-display text-[13px] font-black uppercase text-ink shadow-[3px_3px_0_var(--ink)] hover:bg-spot">
          {all ? 'Key moments only' : `Every line (${events.length})`}
        </button>
      </div>
      <ol className="mt-4 max-h-[34rem] space-y-1.5 overflow-y-auto pr-2">
        {shown.map((e, i) => {
          const m = mark(e.type)
          return (
            <li key={`${e.minute}-${i}`} className="grid grid-cols-[3.2rem_4.6rem_minmax(0,1fr)] items-start gap-3 border-b border-divider/60 pb-1.5">
              <span className="tabular pt-0.5 text-right font-display text-[15px] font-black text-text">{m?.label === 'WHISTLE' && /^\d{2}$/.test(e.minute ?? '') && Number(e.minute) < 5 && i === 0 ? 'FT' : `${e.minute ?? ''}'`}</span>
              <span>{m && <span className={`inline-block px-1.5 py-0.5 font-display text-[11px] font-black ${m.tone}`}>{m.label}</span>}</span>
              <span className={`text-[14px] leading-snug ${m ? 'font-semibold text-text' : 'text-text-muted'}`}>{e.text}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
