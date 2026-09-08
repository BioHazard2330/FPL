import { useEffect, useState } from 'react'

export type FetchState<T> =
  | { status: 'loading' }
  | { status: 'error'; error: Error }
  | { status: 'ready'; data: T }

/** Minimal, dependency-free async-fetch hook (2026-09-08, Phase 8.2 Stage 2)
 * - re-runs `fn` whenever `deps` changes, tracks loading/error/ready
 * honestly (never a silent stale value on error). A real data-fetching
 * library (TanStack Query) is a reasonable future upgrade once more than
 * one screen needs polling/caching/retry - not adopted speculatively for
 * a single endpoint. */
export function useFetch<T>(fn: () => Promise<T>, deps: unknown[] = []): FetchState<T> {
  const [state, setState] = useState<FetchState<T>>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading' })
    fn()
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: 'error', error: error instanceof Error ? error : new Error(String(error)) })
      })
    return () => {
      cancelled = true
    }
    // Deliberate: `deps` IS the real dependency list (caller-supplied), this
    // hook intentionally re-runs only when it changes, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}
