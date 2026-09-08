import { useEffect, useRef, useState } from 'react'

export type FetchState<T> =
  | { status: 'loading' }
  | { status: 'error'; error: Error }
  | { status: 'ready'; data: T }

/** Minimal, dependency-free async-fetch hook (2026-09-08, Phase 8.2 Stage 2)
 * - re-runs `fn` whenever `deps` changes, tracks loading/error/ready
 * honestly (never a silent stale value on error). A real data-fetching
 * library (TanStack Query) is a reasonable future upgrade once more than
 * one screen needs polling/caching/retry - not adopted speculatively for
 * a single endpoint.
 *
 * `pollMs` (2026-09-08, direct user finding: "I don't want that lag,
 * especially during live matches") - a REAL, confirmed gap this whole
 * React rebuild introduced and never caught: every screen fetched its
 * payload exactly once on mount and never again, unlike the old dashboard
 * (a full page regenerated every real sync cycle, with its own client-side
 * refresh). Optional real polling closes that gap - the FIRST fetch still
 * shows the real loading state, but a poll-triggered refetch updates data
 * in place (never flips back to a loading skeleton) and, on failure, keeps
 * the last real data on screen rather than blanking it (the same "keep the
 * last real snapshot" rule `useLiveMeta` already established) - a
 * transient network hiccup should never erase a real, still-valid view. */
export function useFetch<T>(fn: () => Promise<T>, deps: unknown[] = [], pollMs?: number): FetchState<T> {
  const [state, setState] = useState<FetchState<T>>({ status: 'loading' })
  const hasData = useRef(false)

  useEffect(() => {
    let cancelled = false
    hasData.current = false
    setState({ status: 'loading' })

    const run = () => {
      fn()
        .then((data) => {
          if (cancelled) return
          hasData.current = true
          setState({ status: 'ready', data })
        })
        .catch((error: unknown) => {
          if (cancelled) return
          // A poll-triggered failure keeps whatever real data is already on
          // screen - only the initial fetch's own failure surfaces the real
          // error state (nothing real to show instead yet).
          if (hasData.current) return
          setState({ status: 'error', error: error instanceof Error ? error : new Error(String(error)) })
        })
    }

    run()
    const id = pollMs ? setInterval(run, pollMs) : null
    return () => {
      cancelled = true
      if (id !== null) clearInterval(id)
    }
    // Deliberate: `deps` IS the real dependency list (caller-supplied), this
    // hook intentionally re-runs only when it changes, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}
