import type { ReactNode } from 'react'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'

/** The ⓘ that holds what a panel used to print as a paragraph: method, assumptions, evidence. Hover (or focus) to read;
 * the panel itself stays a number and a picture. */
export function Info({ children, label = 'How this is worked out', className = '' }: { children: ReactNode; label?: string; className?: string }) {
  return (
    <HoverCard>
      <HoverCardTrigger
        render={
          <button
            type="button"
            aria-label={label}
            className={`inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border-[1.5px] border-current font-display text-[11px] font-black leading-none opacity-55 transition-opacity hover:opacity-100 focus-visible:opacity-100 ${className}`}
          >
            i
          </button>
        }
      />
      <HoverCardContent className="w-80 rounded-none border-2 border-ink bg-paper p-3 text-[12.5px] leading-snug text-text shadow-[4px_4px_0_var(--ink)] ring-0">
        <div className="mb-1 text-[10.5px] font-bold uppercase tracking-[0.12em] text-text-faint">{label}</div>
        <div className="space-y-1.5">{children}</div>
      </HoverCardContent>
    </HoverCard>
  )
}

/** A paragraph of method or caveat, folded to one small "how to read this" link that opens it on hover. */
export function Note({ children, label = 'how to read this', className = '' }: { children: ReactNode; label?: string; className?: string }) {
  return (
    <div className={`my-1.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint ${className}`}>
      <Info label={label}>{children}</Info>
      <span>{label}</span>
    </div>
  )
}
