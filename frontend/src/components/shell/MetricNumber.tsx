import { useEffect, useRef, useState } from 'react'

interface MetricNumberProps {
  value: number
  decimals?: number
  prefix?: string
  suffix?: string
  className?: string
}

/** Real number-transition primitive (Part 12's "Number Flow" reference,
 * adapted rather than installed - one field genuinely changing value across
 * a live poll doesn't justify a new dependency). Tweens the DISPLAYED digits
 * from the previous real value to the next one on change; renders the raw
 * value immediately on first mount (no animation from zero - that would be
 * fabricating a "climbing" number nothing in the data ever did). */
export function MetricNumber({ value, decimals = 1, prefix = '', suffix = '', className = '' }: MetricNumberProps) {
  const [display, setDisplay] = useState(value)
  const prev = useRef(value)
  const raf = useRef<number | null>(null)

  useEffect(() => {
    const from = prev.current
    const to = value
    if (from === to) return
    prev.current = to
    const start = performance.now()
    const duration = 420
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setDisplay(from + (to - from) * eased)
      if (t < 1) raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current)
    }
  }, [value])

  return (
    <span className={`tabular ${className}`}>
      {prefix}
      {display.toFixed(decimals)}
      {suffix}
    </span>
  )
}
