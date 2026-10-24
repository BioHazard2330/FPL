interface MastheadProps {
  /** Kept so existing call sites compile; the page title already sits in the header bar. */
  edition?: string
  title?: string
  right?: React.ReactNode
}

/** A screen's one line of context (what the data covers, how fresh it is). The page name and an "edition" label used to
 * be repeated here under the header bar saying the same thing; only the part that carries information is left. */
export function Masthead({ right }: MastheadProps) {
  if (!right) return null
  return <div className="bare tabular -mb-2 px-1 text-right text-[13px] text-text-faint">{right}</div>
}
