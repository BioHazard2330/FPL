/** Shared loading/error primitives.
 *
 * Two rules this file exists to enforce, both from real failures on this
 * app: (1) a skeleton must be shaped like the screen it precedes, so the
 * page doesn't visibly re-flow into a completely different layout the
 * moment data lands - a generic stack of grey rounded rectangles promises a
 * card grid none of these screens render; (2) an error state must say what
 * is unknown, never imply a healthy empty state. Nothing here ever renders
 * a fallback value in place of missing data.
 *
 * These are primitives, not a layout: each screen composes its own shape
 * from them, because each screen's real shape genuinely differs. */

/** One flat skeleton block. Deliberately square-cornered and flat - the
 * design system has no rounded cards, so a rounded skeleton would be
 * previewing a page that never arrives. */
export function Skel({ className = '' }: { className?: string }) {
  return <div className={`bg-raised ${className}`} />
}

/** The masthead rule every screen opens with. */
export function SkelMasthead() {
  return (
    <div className="border-b border-divider px-10 py-3">
      <Skel className="h-3 w-64" />
    </div>
  )
}

/** A rule-separated console band of N cells - the shape Live's status strip
 * and any similar readout row take. */
export function SkelConsole({ cells = 4 }: { cells?: number }) {
  return (
    <div className="flex border-b-2 border-divider">
      {Array.from({ length: cells }, (_, i) => (
        <div key={i} className="border-l-2 border-divider px-6 py-4 first:border-l-0 first:pl-10">
          <Skel className="h-2 w-20" />
          <Skel className="mt-2 h-5 w-16" />
        </div>
      ))}
    </div>
  )
}

/** A dense list rail of N rows. */
export function SkelRail({ rows = 6, className = '' }: { rows?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: rows }, (_, i) => (
        <Skel key={i} className="h-5 w-full" />
      ))}
    </div>
  )
}

/** A table's header rule plus N rows - never a single tall grey block, so
 * the column rhythm is already visible before the data lands. */
export function SkelTable({ rows = 10, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div>
      <div className="flex gap-6 border-b-2 border-divider pb-2">
        {Array.from({ length: cols }, (_, i) => (
          <Skel key={i} className="h-2 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex gap-6 border-b border-divider py-2.5">
          {Array.from({ length: cols }, (_, j) => (
            <Skel key={j} className="h-3.5 flex-1" />
          ))}
        </div>
      ))}
    </div>
  )
}

interface ScreenErrorProps {
  title: string
  /** What is genuinely unknown right now, in the reader's terms. Must not
   * imply the underlying state is fine, and must not offer a fallback. */
  description: React.ReactNode
  message: string
}

/** One error composition for every screen. Left rule, not a filled red
 * banner: a fetch failure is information, not an alarm, and a full-bleed
 * red block reads as "your team is in trouble" rather than "this panel
 * could not load." */
export function ScreenError({ title, description, message }: ScreenErrorProps) {
  return (
    <div className="px-10 py-10">
      <div className="border-l-4 border-alert-red bg-panel px-6 py-5" role="alert">
        <div className="font-display text-xl font-bold text-alert-red">{title}</div>
        <div className="mt-2 max-w-xl text-sm text-text-muted">{description}</div>
        <p className="mt-2 font-mono text-[11px] text-text-faint">{message}</p>
      </div>
    </div>
  )
}
