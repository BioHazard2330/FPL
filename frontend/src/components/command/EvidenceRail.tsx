import type { CommandPayload } from '@/lib/types'

const DIRECTION_COLOR: Record<string, string> = {
  POSITIVE: 'text-pitch-green', NEGATIVE: 'text-alert-red', WATCH: 'text-broadcast-gold', NEUTRAL: 'text-text-muted',
}
const DIRECTION_ACCENT: Record<string, string> = {
  POSITIVE: 'border-pitch-green', NEGATIVE: 'border-alert-red', WATCH: 'border-broadcast-gold', NEUTRAL: 'border-text-faint',
}

type FootballContextRow = CommandPayload['football_context'][number]

/** FOOTBALL EVIDENCE as a match-analysis graphic, not a notification list -
 * the lead item runs large/editorial, the rest compress into a dense rail,
 * every item's real `direction` field driving both its accent colour and
 * its fpl_effect emphasis (never a card border for its own sake - the
 * accent rule IS the direction signal). On its own flat panel field,
 * colour-separated from Strategy Rail above (no rule needed). */
export function EvidenceRail({ rows }: { rows: FootballContextRow[] }) {
  if (rows.length === 0) return null
  const [lead, ...rest] = rows

  return (
    <section className="bg-panel py-10">
      <div className="mb-6 px-10 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Football evidence</div>
      <div className="flex gap-px overflow-x-auto bg-divider px-px">
        <div className={`min-w-[340px] border-l-4 bg-panel px-8 py-8 ${DIRECTION_ACCENT[lead.direction] ?? 'border-text-faint'}`}>
          <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">{lead.category.replace(/_/g, ' ')}</div>
          <div className="mt-1 font-display text-4xl font-bold leading-[0.95] text-text">{lead.entity_name}</div>
          <p className="mt-3 max-w-sm text-sm leading-relaxed text-text-muted">{lead.evidence}</p>
          {lead.fpl_effect && <div className={`mt-4 text-base font-bold ${DIRECTION_COLOR[lead.direction] ?? 'text-text'}`}>{lead.fpl_effect}</div>}
        </div>
        {rest.map((f, i) => (
          <div key={i} className={`min-w-[200px] max-w-[240px] shrink-0 border-l-4 bg-panel px-6 py-6 ${DIRECTION_ACCENT[f.direction] ?? 'border-text-faint'}`}>
            <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">{f.category.replace(/_/g, ' ')}</div>
            <div className="mt-1 font-display text-lg font-bold text-text">{f.entity_name}</div>
            <p className="mt-1.5 text-xs leading-relaxed text-text-muted">{f.evidence}</p>
            {f.fpl_effect && <div className={`mt-2 text-xs font-bold ${DIRECTION_COLOR[f.direction] ?? 'text-text'}`}>{f.fpl_effect}</div>}
          </div>
        ))}
      </div>
    </section>
  )
}
