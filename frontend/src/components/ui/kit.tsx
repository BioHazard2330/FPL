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
    <section className={`rounded-xl border border-divider bg-panel ${className}`}>
      {(title || right) && (
        <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-6 pb-1 pt-5">
          <div className="min-w-0">
            {title && <h2 className="font-display text-xl font-semibold leading-tight text-text">{title}</h2>}
            {sub && <p className="mt-1 max-w-3xl text-[14px] leading-snug text-text-muted">{sub}</p>}
          </div>
          {right && <div className="shrink-0 text-[13px] text-text-faint">{right}</div>}
        </header>
      )}
      {children ? <div className={flush ? bodyClassName : `px-6 pb-6 pt-4 ${bodyClassName}`}>{children}</div> : <div className="pb-4" />}
    </section>
  )
}

type Tone = 'neutral' | 'green' | 'gold' | 'red' | 'blue'

const PILL: Record<Tone, string> = {
  neutral: 'bg-raised text-text-muted',
  green: 'bg-pitch-green/15 text-pitch-green',
  gold: 'bg-broadcast-gold/15 text-broadcast-gold',
  red: 'bg-alert-red/15 text-alert-red',
  blue: 'bg-broadcast-blue/20 text-[#8fb0ff]',
}

export function Pill({ tone = 'neutral', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center rounded-full px-2 py-0.5 text-[12px] font-semibold leading-4 ${PILL[tone]}`}>
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
    <details open={defaultOpen} className="group rounded-xl border border-divider bg-panel">
      <summary className="flex cursor-pointer list-none items-baseline justify-between gap-6 px-6 py-4 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="font-display text-xl font-semibold text-text">{title}</span>
          {summary && <span className="ml-4 text-[14px] text-text-muted">{summary}</span>}
        </span>
        <span aria-hidden className="shrink-0 text-text-faint transition-transform group-open:rotate-90">
          &#9656;
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
