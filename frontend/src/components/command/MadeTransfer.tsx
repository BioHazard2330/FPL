import { useState } from 'react'
import { money } from '@/components/ui/kit'
import { recordMadeTransfers, undoMadeTransfers, fetchWeekPlanPayload } from '@/lib/api'
import type { WeekPlanPayload } from '@/lib/types'

/** FPL's public log shows a transfer only after the deadline, so a move made in FPL before then is told to the app here.
 * The squad, bank and free transfers follow at once; the plan re-solves in the background and the page reloads when the
 * new plan is stored (`POST /api/made-transfer`). */

async function waitForNewPlan(previous: number | undefined) {
  for (let i = 0; i < 24; i++) {
    await new Promise((r) => setTimeout(r, 5000))
    try {
      const p = await fetchWeekPlanPayload()
      if (p.decision_id !== previous && p.status === 'current') break
    } catch {
      /* keep waiting */
    }
  }
  window.location.reload()
}

export function MadeItButton({ outId, inId, decisionId }: { outId: number; inId: number; decisionId?: number }) {
  const [state, setState] = useState<'idle' | 'saving' | 'replanning' | 'error'>('idle')
  const [reason, setReason] = useState('')
  if (state === 'replanning') return <span className="text-[12.5px] font-semibold text-broadcast-gold">Recorded · re-planning around it…</span>
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        disabled={state === 'saving'}
        onClick={async () => {
          setState('saving')
          const r = await recordMadeTransfers([{ outId, inId }])
          if (r.status !== 'recorded') {
            setReason(r.reason ?? 'refused')
            setState('error')
            return
          }
          setState('replanning')
          void waitForNewPlan(decisionId)
        }}
        className="rounded-md border border-divider px-2 py-0.5 text-[12px] font-semibold text-text-muted hover:border-pitch-green/50 hover:text-pitch-green disabled:opacity-50"
        title="Tell the app you made this transfer in FPL. FPL only publishes it after the deadline."
      >
        {state === 'saving' ? 'Recording…' : 'Made it in FPL'}
      </button>
      {state === 'error' && <span className="text-[12px] text-alert-red">{reason}</span>}
    </span>
  )
}

export function RecordedStrip({ plan }: { plan: WeekPlanPayload }) {
  const [busy, setBusy] = useState(false)
  const rows = plan.recorded_transfers ?? []
  if (rows.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-divider bg-pitch-green/5 px-6 py-2.5 text-[13px] text-text-muted">
      <span className="font-semibold text-pitch-green">Made in FPL, by your word:</span>
      {rows.map((t) => (
        <span key={`${t.element_out}-${t.element_in}`} className="tabular">
          {t.out_name} ({money(t.element_out_cost)}) &rarr; <span className="font-semibold text-text">{t.in_name}</span> ({money(t.element_in_cost)})
        </span>
      ))}
      <span className="text-text-faint">FPL publishes it after the GW{rows[0].event} deadline and its own record replaces this one.</span>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          await undoMadeTransfers()
          void waitForNewPlan(plan.decision_id)
        }}
        className="ml-auto text-[12.5px] font-semibold text-text-faint hover:text-alert-red disabled:opacity-50"
      >
        {busy ? 'Undoing, re-planning…' : 'Undo'}
      </button>
    </div>
  )
}

export function MadeTheseButton({ pairs }: { pairs: { outId: number; inId: number }[] }) {
  const [state, setState] = useState<'idle' | 'saving' | 'replanning' | 'error'>('idle')
  const [reason, setReason] = useState('')
  if (state === 'replanning') return <p className="mt-3 text-[13px] font-semibold text-broadcast-gold">Recorded · the plan is re-solving around your squad…</p>
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <button
        type="button"
        disabled={state === 'saving'}
        onClick={async () => {
          setState('saving')
          const before = await fetchWeekPlanPayload().catch(() => null)
          const r = await recordMadeTransfers(pairs)
          if (r.status !== 'recorded') {
            setReason(r.reason ?? 'refused')
            setState('error')
            return
          }
          setState('replanning')
          void waitForNewPlan(before?.decision_id)
        }}
        className="rounded-md border border-pitch-green/50 bg-pitch-green/10 px-3 py-1.5 text-[13px] font-semibold text-pitch-green hover:bg-pitch-green/20 disabled:opacity-50"
      >
        {state === 'saving' ? 'Recording…' : `I've made ${pairs.length === 1 ? 'this' : 'these'} in FPL`}
      </button>
      <span className="text-[12px] text-text-faint">FPL only publishes transfers after the deadline; this tells the planner now.</span>
      {state === 'error' && <span className="text-[12px] text-alert-red">{reason}</span>}
    </div>
  )
}
