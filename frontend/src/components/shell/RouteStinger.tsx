import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { currentDestination, NAV_SECTIONS } from '@/lib/nav'

/** The broadcast stinger: moving between screens sweeps three slanted bands across the page with the destination's name,
 * the way a channel wipes between segments. Under 600ms, never blocks a click, skipped for query-only changes, for
 * reduced motion and when switched off from the command palette (localStorage `fpl-stinger` = off). */
export function RouteStinger() {
  const { pathname } = useLocation()
  const segment = pathname.split('/')[1] ?? ''
  const first = useRef(true)
  const [wipe, setWipe] = useState<{ id: number; label: string; section: string } | null>(null)

  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    let off = false
    try {
      off = localStorage.getItem('fpl-stinger') === 'off'
    } catch {
      off = false
    }
    if (off || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const dest = currentDestination(pathname)
    const section = NAV_SECTIONS.find((s) => s.routes.includes(dest.to))?.label ?? ''
    const id = Date.now()
    setWipe({ id, label: dest.label, section })
    const t = window.setTimeout(() => setWipe((w) => (w?.id === id ? null : w)), 640)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segment])

  if (!wipe) return null
  return (
    <div key={wipe.id} className="stinger pointer-events-none fixed inset-0 z-[70] overflow-hidden" aria-hidden>
      <div className="stinger-band stinger-a bg-spot" />
      <div className="stinger-band stinger-b bg-broadcast-gold" />
      <div className="stinger-band stinger-c flex items-center justify-center bg-ink">
        <div className="stinger-title text-center">
          {wipe.section && <div className="font-display text-[1.4rem] font-black uppercase tracking-[0.3em] text-spot">{wipe.section}</div>}
          <div className="font-display text-[7.5rem] font-black uppercase leading-[0.85] text-paper">{wipe.label}</div>
        </div>
      </div>
    </div>
  )
}
