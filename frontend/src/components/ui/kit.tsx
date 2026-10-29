import type { ReactNode } from 'react'

/** The small shared vocabulary every screen is built from, so a panel, a status pill and a figure look the same wherever they
 * appear. Sentence-case titles at one size, muted one-line subtitles, a single panel surface and a single pill shape. Anything
 * louder than these is a deliberate exception. */

export function Panel({
  title,
  sub,
  right,
  children,
  className = '',
  bodyClassName = '',
  flush = false,
}: {
  title?: ReactNode
  sub?: ReactNode
  right?: ReactNode
  children?: ReactNode
  className?: string
  bodyClassName?: string
  flush?: boolean
}) {
  return (
    <section className={`slab ${className}`}>
      {(title || right) && (
        <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-6 pb-1 pt-5">
          <div className="min-w-0">
            {title && <h2 className="font-display text-xl font-semibold leading-tight text-text">{title}</h2>}
            {sub && <p className="mt-1.5 max-w-3xl text-[13.5px] leading-snug text-text-faint">{sub}</p>}
          </div>
          {right && <div className="shrink-0 text-[13px] text-text-faint">{right}</div>}
        </header>
      )}
      {children ? <div className={flush ? bodyClassName : `px-6 pb-6 pt-4 ${bodyClassName}`}>{children}</div> : <div className="pb-4" />}
    </section>
  )
}

type Tone = 'neutral' | 'green' | 'gold' | 'red' | 'blue'

const PILL: Record<Tone, { ink: string; bar: string }> = {
  neutral: { ink: 'text-text-muted', bar: 'bg-text-faint' },
  green: { ink: 'text-pitch-green', bar: 'bg-pitch-green' },
  gold: { ink: 'text-broadcast-gold', bar: 'bg-broadcast-gold' },
  red: { ink: 'text-alert-red', bar: 'bg-alert-red' },
  blue: { ink: 'text-broadcast-blue', bar: 'bg-broadcast-blue' },
}

/** A label, not a capsule: small capitals behind a slanted colour tick, so a row of them reads as captions rather than
 * a scatter of buttons. */
export function Pill({ tone = 'neutral', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1.5 whitespace-nowrap text-[10.5px] font-bold uppercase leading-4 tracking-[0.12em] ${PILL[tone].ink}`}>
      <span className={`h-2.5 w-[4px] shrink-0 ${PILL[tone].bar} [clip-path:polygon(40%_0,100%_0,60%_100%,0_100%)]`} />
      {children}
    </span>
  )
}

export function Fig({ label, value, tone = 'text-text', sub }: { label: string; value: ReactNode; tone?: string; sub?: ReactNode }) {
  return (
    <div>
      <div className="text-[13px] text-text-faint">{label}</div>
      <div className={`tabular mt-0.5 font-display text-2xl font-semibold leading-none ${tone}`}>{value}</div>
      {sub && <div className="mt-1 text-[12px] text-text-faint">{sub}</div>}
    </div>
  )
}

/** A panel whose body stays out of the way until asked for. The title and a one-line summary are always visible, so the reader
 * knows what is inside before opening it. */
export function Disclosure({
  title,
  summary,
  children,
  defaultOpen = false,
}: {
  title: ReactNode
  summary?: ReactNode
  children: ReactNode
  defaultOpen?: boolean
}) {
  return (
    <details open={defaultOpen} className="group slab">
      <summary className="flex cursor-pointer list-none items-baseline justify-between gap-6 px-6 py-4 [&::-webkit-details-marker]:hidden">
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-1">
          <h2 className="font-display text-xl font-semibold text-text">{title}</h2>
          {summary && <span className="text-[13.5px] text-text-faint">{summary}</span>}
        </span>
        <span aria-hidden className="shrink-0 rounded-sm bg-raised px-2 py-0.5 text-[11px] font-bold uppercase tracking-[0.12em] text-text-muted group-hover:text-text">
          <span className="group-open:hidden">Open</span>
          <span className="hidden group-open:inline">Close</span>
        </span>
      </summary>
      <div className="border-t border-divider px-6 pb-6 pt-5">{children}</div>
    </details>
  )
}

export const money = (tenths: number) => `£${(tenths / 10).toFixed(1)}m`

export const CHIP_NAMES: Record<string, string> = {
  bboost: 'Bench Boost',
  '3xc': 'Triple Captain',
  freehit: 'Free Hit',
  wildcard: 'Wildcard',
}

export const chipName = (c: string) => CHIP_NAMES[c] ?? c
