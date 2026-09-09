interface MastheadProps {
  edition: string
  title: string
  right?: React.ReactNode
}

/** The shared "Bulletin Terminal" masthead bar (2026-09-08, Phase 9 design-
 * lab winner, `docs/history/50-design-lab-decision.md`) - real, consistent
 * cross-screen identity per Part 14's own "one coherent design system"
 * rule, each screen's own real bulletin edition label distinguishing it
 * (e.g. "DECISION WIRE" for Command, "SQUAD REPORT" for My Team). */
export function Masthead({ edition, title, right }: MastheadProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-divider px-10 py-3 font-mono text-[11px] uppercase tracking-[0.08em] text-text-faint">
      <span>
        {edition} &middot; <strong className="text-text">{title}</strong>
      </span>
      {right && <span className="tabular normal-case">{right}</span>}
    </div>
  )
}
