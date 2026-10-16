import { Link } from 'react-router-dom'
import { relativeTime } from '@/lib/time'
import type { DeskPayload } from '@/lib/types'

/** FROM THE DESK - the few stories that name your players or the plan's
 * targets, straight from the wire, with a link out to each. The full desk is
 * one click away; this is only here so a transfer decision is never made
 * without the news that touches it in view. Renders nothing when no story
 * does: an empty strip would only be filler. */
export function DeskStrip({ desk: d }: { desk: DeskPayload | null }) {
  if (!d) return null
  const items = [...(d.lead ? [d.lead] : []), ...d.wire].filter((a) => a.relevance > 0).slice(0, 4)
  const flagged = d.injuries.filter((i) => i.mine || i.target).slice(0, 4)
  if (items.length === 0 && flagged.length === 0) return null
  return (
    <section className="bg-void px-10 py-10">
      <div className="mb-4 flex items-baseline justify-between">
        <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">From the desk</span>
        <Link to="/desk" className="font-mono text-[10px] uppercase tracking-[0.12em] text-text-faint hover:text-text">Open the desk &rarr;</Link>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_22rem] gap-10">
        <div>
          {items.map((a) => (
            <a key={a.id} href={a.link} target="_blank" rel="noreferrer" className="block border-b border-divider py-2.5 first:pt-0">
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">
                {a.source} · {relativeTime(a.published_at) ?? ''} · {a.players.filter((p) => p.mine || p.target).map((p) => `${p.name}${p.mine ? ' (yours)' : ' (plan)'}`).join(', ')}
              </div>
              <div className="text-[15px] font-semibold leading-snug text-text hover:text-pitch-green">{a.title}</div>
            </a>
          ))}
        </div>
        <div>
          {flagged.length > 0 && <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">Official injury notes</div>}
          {flagged.map((i) => (
            <div key={i.player_id} className="border-b border-divider py-1.5 text-sm">
              <Link to={`/player/${i.player_id}`} className="font-bold text-text hover:text-pitch-green">{i.name}</Link>{' '}
              <span className="tabular font-bold text-broadcast-gold">{i.chance !== null ? `${i.chance}%` : 'out'}</span>
              <div className="truncate text-xs text-text-muted" title={i.news}>{i.news}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
