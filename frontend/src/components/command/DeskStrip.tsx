import { Link } from 'react-router-dom'
import { Panel } from '@/components/ui/kit'
import { relativeTime } from '@/lib/time'
import type { DeskPayload } from '@/lib/types'

/** IN THE NEWS - the few stories that name your players or the plan's targets, with a link out to each, and the official injury
 * notes on them. Renders nothing when no story does: an empty strip would only be filler. */
export function DeskStrip({ desk: d }: { desk: DeskPayload | null }) {
  if (!d) return null
  const items = [...(d.lead ? [d.lead] : []), ...d.wire].filter((a) => a.relevance > 0).slice(0, 4)
  const flagged = d.injuries.filter((i) => i.mine || i.target).slice(0, 4)
  if (items.length === 0 && flagged.length === 0) return null
  return (
    <Panel title="In the news" right={<Link to="/desk" className="font-medium hover:text-text">Open the desk &rarr;</Link>}>
      <div className="grid grid-cols-1 gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div>
          {items.map((a) => (
            <a key={a.id} href={a.link} target="_blank" rel="noreferrer" className="block border-b border-divider py-2.5 first:pt-0 last:border-0">
              <div className="text-[12px] text-text-faint">
                {a.source} &middot; {relativeTime(a.published_at) ?? ''} &middot; {a.players.filter((p) => p.mine || p.target).map((p) => `${p.name}${p.mine ? ' (yours)' : ' (plan target)'}`).join(', ')}
              </div>
              <div className="mt-0.5 text-[15px] font-semibold leading-snug text-text hover:text-pitch-green">{a.title}</div>
            </a>
          ))}
        </div>
        <div>
          {flagged.length > 0 && <div className="mb-1 text-[13px] font-medium text-text-faint">Official injury notes</div>}
          {flagged.map((i) => (
            <div key={i.player_id} className="border-b border-divider py-2 text-sm last:border-0">
              <Link to={`/player/${i.player_id}`} className="font-semibold text-text hover:text-pitch-green">{i.name}</Link>{' '}
              <span className="tabular font-semibold text-broadcast-gold">{i.chance !== null ? `${i.chance}% to play` : 'out'}</span>
              <div className="truncate text-[13px] text-text-muted" title={i.news}>{i.news}</div>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  )
}
