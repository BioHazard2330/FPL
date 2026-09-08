import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

interface CountUpProps {
  value: number
  decimals?: number
  prefix?: string
  suffix?: string
  className?: string
  durationMs?: number
}

// Hand-built equivalent of the researched 21st "Count Up" pattern
// (unlumen/count-up, docs/UI_21ST_RESEARCH.md Part B9) - re-created from its
// documented real API (`to`/`from`/direction/digitEffect props) rather than
// spending one of the 2 free daily `21st get` code retrievals on a component
// this simple to reproduce faithfully. Springs to a new `value` whenever it
// changes - a real data-arrival event (SSE push, fresh API payload), never a
// page-load timer (the exact anti-pattern this project's own Phase 8.0
// already removed once).
export function CountUp({ value, decimals = 1, prefix = '', suffix = '', className, durationMs = 600 }: CountUpProps) {
  const [display, setDisplay] = useState(value)
  const fromRef = useRef(value)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    const from = fromRef.current
    const to = value
    if (from === to) return
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs)
      const eased = 1 - (1 - t) * (1 - t) // ease-out
      setDisplay(from + (to - from) * eased)
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        fromRef.current = to
      }
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return (
    <span className={cn('tabular-nums', className)}>
      {prefix}
      {display.toFixed(decimals)}
      {suffix}
    </span>
  )
}
