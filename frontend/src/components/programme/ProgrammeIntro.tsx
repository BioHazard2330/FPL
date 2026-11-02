import { useEffect, useState } from 'react'
import { ProgrammeCover } from '@/components/programme/ProgrammeCover'
import { fetchWeekPlanPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { useLiveMeta } from '@/lib/useLiveMeta'

/** THE OPENING - the first visit of the day starts on the programme cover, which swings open like a page onto the app.
 * Once a day (remembered in this browser), skippable, never shown with reduced motion. */
const KEY = 'fpl-programme-seen'

function seenToday(): boolean {
  try {
    return localStorage.getItem(KEY) === new Date().toDateString()
  } catch {
    return true
  }
}

export function ProgrammeIntro() {
  const [phase, setPhase] = useState<'hidden' | 'in' | 'open'>(() =>
    seenToday() || window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'hidden' : 'in')
  const plan = useFetch(fetchWeekPlanPayload, [])
  const live = useLiveMeta()

  const open = () => {
    setPhase('open')
    try {
      localStorage.setItem(KEY, new Date().toDateString())
    } catch {
      /* storage unavailable */
    }
    window.setTimeout(() => setPhase('hidden'), 1500)
  }

  useEffect(() => {
    if (phase !== 'in' || plan.status !== 'ready') return
    const t = window.setTimeout(open, 3400)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, plan.status])

  if (phase === 'hidden' || plan.status === 'error') return null
  return (
    <div className={`prog-intro fixed inset-0 z-[100] flex items-center justify-center ${phase === 'open' ? 'prog-intro-out' : ''}`} onClick={open}>
      <div className="prog-stage">
        <div className={`prog-cover ${phase === 'open' ? 'prog-cover-open' : ''}`} style={{ width: 'min(46vw, 64vh)' }}>
          {plan.status === 'ready'
            ? <ProgrammeCover plan={plan.data} deadline={live?.gw?.next_deadline_time ?? null} />
            : <div className="aspect-[1/1.414] w-full bg-[#f3ead6]" />}
        </div>
      </div>
      <button type="button" onClick={open} className="absolute bottom-8 right-10 font-display text-[13px] font-black uppercase tracking-[0.2em] text-paper/70 hover:text-paper">
        Open the programme →
      </button>
    </div>
  )
}
