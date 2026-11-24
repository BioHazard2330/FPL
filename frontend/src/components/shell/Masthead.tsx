import { useLocation } from 'react-router-dom'
import { SCREEN_QUESTION } from '@/lib/screens'

export interface LeadStat { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: 'good' | 'bad' | 'spot' }

interface MastheadProps {
  /** Kept so existing call sites compile. */
  edition?: string
  title?: string
  right?: React.ReactNode
  /** The screen's own lead figures, shown as a row of big numbers under its question. */
  stats?: LeadStat[]
}

const TONE: Record<string, string> = { good: 'text-pitch-green', bad: 'text-alert-red', spot: 'text-spot' }

/** A screen's opening: the question it answers in the display face on a heavy rule, the coverage line as a chip, and the
 * screen's lead figures as a scoreboard row (2026-11-24: one faint line of metadata was all most screens opened with). */
export function Masthead({ right, stats }: MastheadProps) {
  const seg = useLocation().pathname.split('/')[1] ?? ''
  const q = SCREEN_QUESTION[seg]
  if (!q && !right && !stats?.length) return null
  return (
    <div className="bare space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 border-b-[3px] border-ink px-1 pb-3">
        {q && (
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11.5px] font-black uppercase tracking-[0.18em] text-spot">
              <span className="inline-block h-[3px] w-6 bg-spot" />{q.kicker}
            </div>
            <div className="mt-1 font-display text-[clamp(1.7rem,2.6vw,2.6rem)] font-black uppercase leading-[0.95] text-text">{q.question}</div>
          </div>
        )}
        {right && <div className="tabular shrink-0 border-2 border-ink bg-paper px-3 py-1 text-[12.5px] text-text-muted shadow-[3px_3px_0_var(--ink)]">{right}</div>}
      </div>
      {stats && stats.length > 0 && (
        <div className="grid divide-x-2 divide-ink border-2 border-ink bg-panel shadow-[5px_5px_0_var(--ink)]" style={{ gridTemplateColumns: `repeat(${stats.length}, minmax(0, 1fr))` }}>
          {stats.map((s, i) => (
            <div key={i} className={`min-w-0 px-5 py-3 ${i === 0 ? 'bg-ink text-paper' : ''}`}>
              <div className={`text-[11px] font-bold uppercase tracking-[0.14em] ${i === 0 ? 'text-paper/60' : 'text-text-faint'}`}>{s.label}</div>
              <div className={`tabular mt-1 truncate font-display text-[clamp(1.6rem,2.4vw,2.5rem)] font-black leading-none ${s.tone ? TONE[s.tone] : i === 0 ? 'text-paper' : 'text-text'}`}>{s.value}</div>
              {s.sub && <div className={`mt-1 truncate text-[12px] ${i === 0 ? 'text-paper/70' : 'text-text-muted'}`}>{s.sub}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
