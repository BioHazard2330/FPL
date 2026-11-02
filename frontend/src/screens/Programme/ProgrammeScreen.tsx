import { useRef, useState } from 'react'
import { toPng } from 'html-to-image'
import { Masthead } from '@/components/shell/Masthead'
import { ProgrammeCover } from '@/components/programme/ProgrammeCover'
import { fetchWeekPlanPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { useLiveMeta } from '@/lib/useLiveMeta'

/** THE PROGRAMME - this gameweek's cover, to look at or to save as a picture (2x, for sharing). */
export function ProgrammeScreen() {
  const plan = useFetch(fetchWeekPlanPayload, [])
  const live = useLiveMeta()
  const cover = useRef<HTMLDivElement>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const save = async () => {
    if (!cover.current) return
    setBusy(true)
    setErr(null)
    try {
      const url = await toPng(cover.current, { pixelRatio: 2 })
      const a = document.createElement('a')
      a.href = url
      a.download = `fpl-programme-gw${plan.status === 'ready' ? plan.data.event : ''}.png`
      a.click()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const replay = () => {
    try {
      localStorage.removeItem('fpl-programme-seen')
    } catch {
      /* storage unavailable */
    }
    window.location.assign('/')
  }

  return (
    <div>
      <Masthead right={
        <span className="flex items-center gap-3">
          <button type="button" onClick={save} disabled={busy || plan.status !== 'ready'}
            className="border-2 border-ink bg-spot px-3 py-1 font-display text-[13px] font-black uppercase text-ink shadow-[3px_3px_0_var(--ink)] hover:bg-paper disabled:opacity-50">
            {busy ? 'Printing…' : 'Save as picture'}
          </button>
          <button type="button" onClick={replay} className="border-2 border-ink bg-paper px-3 py-1 font-display text-[13px] font-black uppercase text-ink hover:bg-raised">
            Play the opening
          </button>
        </span>
      } />
      <div className="bare flex justify-center py-6">
        <div className="w-full max-w-[760px] shadow-[12px_12px_0_var(--ink)]">
          {plan.status === 'ready' && <ProgrammeCover ref={cover} plan={plan.data} deadline={live?.gw?.next_deadline_time ?? null} />}
        </div>
      </div>
      {err && <p className="text-center text-[13px] text-alert-red">The picture could not be made: {err}</p>}
    </div>
  )
}
