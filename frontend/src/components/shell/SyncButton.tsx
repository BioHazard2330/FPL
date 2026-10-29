import { useEffect, useRef, useState } from 'react'

interface RefreshStatus {
  running: boolean
  started_at: string | null
  finished_at: string | null
  returncode: number | null
}

type Phase = 'idle' | 'starting' | 'running' | 'failed'

/** SYNC NOW - runs the full scheduled cycle once, on demand.
 *
 * Outside the active window nothing runs on a schedule (that is what
 * power gating is for), so the data on screen can be most of a day old at the
 * very moment a manager sits down to decide. This is the same cycle the
 * scheduler would have run - sync, change detection, the week plan rebuild,
 * the dashboard and live snapshot - started from here. It reads public data
 * and writes this project's own files; it does not touch the FPL account.
 *
 * It says what it is doing in words rather than a spinner, because a sync
 * takes a minute or two and a bare animation tells nobody whether it is stuck. */
export function SyncButton() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [, tick] = useState(0)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const stop = () => {
    if (timer.current !== null) clearInterval(timer.current)
    timer.current = null
  }

  useEffect(() => stop, [])

  useEffect(() => {
    if (phase !== 'running') return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [phase])

  const poll = () => {
    timer.current = setInterval(async () => {
      try {
        const res = await fetch('/api/refresh-status')
        const s = (await res.json()) as RefreshStatus
        if (s.running) return
        stop()
        if (s.returncode === 0 || s.returncode === null) {
          window.location.reload()
        } else {
          setPhase('failed')
        }
      } catch {
        /* the server is busy or restarting; the next tick asks again */
      }
    }, 3000)
  }

  const start = async () => {
    setPhase('starting')
    try {
      const res = await fetch('/api/refresh', { method: 'POST', headers: { 'X-FPL-Refresh': '1' } })
      if (!res.ok) throw new Error(String(res.status))
      setStartedAt(Date.now())
      setPhase('running')
      poll()
    } catch {
      setPhase('failed')
    }
  }

  if (phase === 'running') {
    const secs = startedAt ? Math.floor((Date.now() - startedAt) / 1000) : 0
    return (
      <span className="text-[13px] text-broadcast-gold" title="Syncing FPL, news, lineups and odds, then rebuilding your plan">
        Syncing {secs}s
      </span>
    )
  }
  if (phase === 'failed') {
    return (
      <button type="button" onClick={start} className="text-alert-red hover:text-text" title="The sync did not finish. Click to try again.">
        Sync failed &middot; retry
      </button>
    )
  }
  return (
    <button
      type="button"
      onClick={start}
      disabled={phase === 'starting'}
      className="shrink-0 border-2 border-ink bg-ink px-3 py-1 font-display text-[15px] font-black uppercase text-paper shadow-[3px_3px_0_var(--spot)] hover:-translate-y-px"
      title="Run the full sync now: FPL data, news, lineups, odds, then rebuild the plan"
    >
      Sync now
    </button>
  )
}
