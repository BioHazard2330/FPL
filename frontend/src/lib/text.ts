const ONES: [RegExp, string][] = [
  [/\b1 shots\b/g, '1 shot'],
  [/\b1 goals\b/g, '1 goal'],
  [/\b1 assists\b/g, '1 assist'],
  [/\b1 key passes\b/g, '1 key pass'],
  [/\b1 big chances\b/g, '1 big chance'],
  [/\b1 minutes\b/g, '1 minute'],
  [/\b1 yellow cards\b/g, '1 yellow card'],
]

/** Evidence lines are built from counts, and stored rows from earlier matches still say "1 shots". Fixed where it is shown, so
 * the history does not need rewriting. */
export const plain = (text: string | null | undefined): string => ONES.reduce((t, [re, w]) => t.replace(re, w), text ?? '')

const ORDER = ['first choice', 'second choice', 'third choice', 'fourth choice', 'fifth choice']
const duty = (v: unknown) => (typeof v === 'number' ? (ORDER[v - 1] ?? `choice ${v}`) : 'not listed')

/** A stored change event as a sentence. Set-piece changes are stored as a pair of six-value lists (penalty, corner and direct
 * free kick orders, each followed by its note) and used to be printed raw. */
export function describeChange(eventType: string | null, oldValue: string | null, newValue: string | null): string {
  if (eventType === 'setpiece_change') {
    try {
      const o = JSON.parse(oldValue ?? '[]') as unknown[]
      const n = JSON.parse(newValue ?? '[]') as unknown[]
      const parts = (['penalties', 'corners', 'direct free kicks'] as const)
        .map((label, i) => (o[i * 2] !== n[i * 2] ? `${label}: ${duty(o[i * 2])} to ${duty(n[i * 2])}` : null))
        .filter((x): x is string => x !== null)
      if (parts.length > 0) return parts.join('; ')
    } catch {
      /* fall through to the raw values */
    }
  }
  if (eventType === 'qualitative_analysis') return `the analyst's note on the match reads ${(newValue ?? '').toLowerCase()}`
  if (eventType === 'start_percent_change') return `chance of starting ${oldValue ?? '—'}% to ${newValue ?? '—'}%`
  return `${oldValue ?? '—'} to ${newValue ?? '—'}`
}

const EVENT_LABELS: Record<string, string> = {
  qualitative_analysis: 'match note',
  setpiece_change: 'set pieces',
  price_change: 'price',
  status_change: 'availability',
  lineup_confirmed: 'lineup',
  early_withdrawal: 'taken off early',
  start_percent_change: 'start chance',
  predicted_lineup_change: 'predicted lineup',
  new_player: 'new player',
  club_change: 'club',
  removed_player: 'removed',
}

export const eventLabel = (eventType: string | null): string => (eventType ? (EVENT_LABELS[eventType] ?? eventType.replace(/_/g, ' ')) : '')
