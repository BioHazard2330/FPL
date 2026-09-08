import { useEffect, useState } from 'react'
import { fetchLiveSnapshot } from './api'
import type { LiveSnapshot } from './types'

const POLL_MS = 15000

/** Shared, app-wide poll of the real live-state file (2026-09-08, full
 * redesign pass) - every screen's own nav rail / context header / live
 * ticker reads off the SAME real snapshot rather than each inventing its
 * own idea of "current GW"/"last updated". Never fabricates a value: a
 * fetch failure just leaves the previous real snapshot in place (or null
 * on first load) - callers degrade the ticker/rail gracefully. */
export function useLiveMeta(): LiveSnapshot | null {
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      fetchLiveSnapshot()
        .then((data) => {
          if (!cancelled) setSnapshot(data)
        })
        .catch(() => {
          /* keep the last real snapshot rather than blanking the UI */
        })
    }
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return snapshot
}
