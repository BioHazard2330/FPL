import { useEffect, useRef, useState } from 'react'

/** SPLIT-FLAP - a character cell from a railway departure board. When the target changes, the cell rolls through the
 * drum (blank, A-Z, 0-9, punctuation) from what it shows to what it should show, one flap at a time, each flap a real
 * two-leaf fold: the top leaf of the old character falls, the bottom leaf of the new one lands. */

const DRUM = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:.-+·\'/%'
const STEP_MS = 55
const MAX_STEPS = 12

function FlapCell({ ch, delay }: { ch: string; delay: number }) {
  const target = DRUM.includes(ch) ? ch : ' '
  const [shown, setShown] = useState(target)
  const [prev, setPrev] = useState(target)
  const [tick, setTick] = useState(0)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    if (shown === target) return
    const from = DRUM.indexOf(shown)
    const to = DRUM.indexOf(target)
    const dist = (to - from + DRUM.length) % DRUM.length
    const path: string[] = []
    if (dist <= MAX_STEPS) for (let i = 1; i <= dist; i++) path.push(DRUM[(from + i) % DRUM.length])
    else {
      for (let i = 1; i < MAX_STEPS; i++) path.push(DRUM[(from + i) % DRUM.length])
      path.push(target)
    }
    let i = 0
    let cur = shown
    const run = () => {
      const next = path[i++]
      setPrev(cur)
      setShown(next)
      setTick((t) => t + 1)
      cur = next
      if (i < path.length) timer.current = window.setTimeout(run, STEP_MS)
    }
    timer.current = window.setTimeout(run, delay)
    return () => { if (timer.current) window.clearTimeout(timer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])

  return (
    <span className="flap" aria-hidden>
      <span className="flap-half flap-top"><span>{shown}</span></span>
      <span className="flap-half flap-bottom"><span>{shown}</span></span>
      {tick > 0 && (
        <span key={tick} className="flap-leaves">
          <span className="flap-half flap-top flap-fall"><span>{prev}</span></span>
          <span className="flap-half flap-bottom flap-land"><span>{shown}</span></span>
        </span>
      )}
    </span>
  )
}

export function Flap({ text, width, className = '', stagger = 18 }: { text: string; width?: number; className?: string; stagger?: number }) {
  const t = text.toUpperCase()
  const padded = width ? t.slice(0, width).padEnd(width, ' ') : t
  return (
    <span className={`flap-row ${className}`} role="text" aria-label={text}>
      {[...padded].map((c, i) => <FlapCell key={i} ch={c} delay={i * stagger} />)}
    </span>
  )
}
