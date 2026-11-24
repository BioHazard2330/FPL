import { useLocation } from 'react-router-dom'
import { SCREEN_QUESTION } from '@/lib/screens'

interface MastheadProps {
  /** Kept so existing call sites compile. */
  edition?: string
  title?: string
  right?: React.ReactNode
}

/** A screen's opening: the question it answers in the display face on a spot rule, with what the data covers and how
 * fresh it is as a chip beside it (2026-11-24: one faint line of metadata was all a screen opened with). The page name
 * stays in the header bar; this says what the page is for. */
export function Masthead({ right }: MastheadProps) {
  const seg = useLocation().pathname.split('/')[1] ?? ''
  const q = SCREEN_QUESTION[seg]
  if (!q && !right) return null
  return (
    <div className="bare flex flex-wrap items-end justify-between gap-x-6 gap-y-2 border-b-[3px] border-ink px-1 pb-3">
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
  )
}
