import { Face } from '@/components/ui/Face'
import { Panel, Pill } from '@/components/ui/kit'
import { fetchSquadNews } from '@/lib/api'
import { relativeTime } from '@/lib/time'
import { useFetch } from '@/lib/useFetch'
import type { SquadNewsItem } from '@/lib/types'
import { Link } from 'react-router-dom'

const SOURCE_TONE: Record<string, 'neutral' | 'green' | 'gold' | 'red' | 'blue'> = {
  'Team sheet': 'blue',
  'Last team sheet': 'blue',
  FPL: 'gold',
  FotMob: 'neutral',
  'Return forecast': 'green',
}

function headline(i: SquadNewsItem) {
  if (i.sheet_role === 'NOT_IN_SQUAD') return { tone: 'red' as const, text: 'Not in the squad' }
  if (i.sheet_role === 'BENCH') {
    const on = i.sheet_detail?.match(/came on (\d+)'/)
    return { tone: 'gold' as const, text: on ? `Came off the bench, ${on[1]}'` : 'On the bench' }
  }
  if (i.next_gw_probability !== null && i.next_gw_probability < 0.5) return { tone: 'red' as const, text: `${Math.round(i.next_gw_probability * 100)}% next week` }
  if (i.next_gw_probability !== null) return { tone: 'gold' as const, text: `${Math.round(i.next_gw_probability * 100)}% next week` }
  if (i.fpl_chance !== null && i.fpl_chance < 100 && i.fpl_status !== 'a') return { tone: 'gold' as const, text: `${i.fpl_chance}% to play` }
  return { tone: 'neutral' as const, text: 'In the news' }
}

/** SQUAD NEWS - what the team sheets, the clubs and the press say about the players you own or the plan buys. Each line names
 * where it came from; a headline is shown as published, never paraphrased. Renders nothing when nobody has anything to say. */
export function SquadNews() {
  const state = useFetch(fetchSquadNews, [], 120000)
  if (state.status !== 'ready' || state.data.status !== 'ready' || state.data.items.length === 0) return null
  const d = state.data
  return (
    <Panel
      title="Squad news"
      sub={`What the match-day sheets, FPL and the press say about the players you own or the plan buys, ahead of GW${d.next_event ?? ''}.`}
    >
      <div className="divide-y divide-divider">
        {d.items.map((i) => {
          const h = headline(i)
          return (
            <div key={i.player_id} className="grid grid-cols-[3.25rem_minmax(0,1fr)] gap-4 py-4 first:pt-0 last:pb-0">
              <Face code={i.photo_code} teamCode={i.team_code} isGkp={i.position === 'GKP'} size="sm" muted={i.severity >= 3} />
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <Link to={`/player/${i.player_id}`} className="font-display text-[17px] font-semibold text-text hover:text-pitch-green">
                    {i.name}
                  </Link>
                  <span className="text-[13px] text-text-faint">
                    {i.team} &middot; {i.owned ? 'yours' : 'plan target'}
                  </span>
                  <Pill tone={h.tone}>{h.text}</Pill>
                </div>
                <ul className="mt-1.5 space-y-1">
                  {i.facts.map((f, k) => (
                    <li key={k} className="flex gap-2 text-[14px] leading-snug text-text-muted">
                      <span className="mt-0.5 shrink-0"><Pill tone={SOURCE_TONE[f.source] ?? 'neutral'}>{f.source}</Pill></span>
                      <span>{f.text}</span>
                    </li>
                  ))}
                  {i.headlines.map((n) => (
                    <li key={n.link} className="flex gap-2 text-[14px] leading-snug">
                      <span className="mt-0.5 shrink-0"><Pill>{n.outlet}</Pill></span>
                      <a href={n.link} target="_blank" rel="noreferrer" className="text-text hover:text-pitch-green">
                        {n.title}
                        <span className="ml-2 text-[12px] text-text-faint">{relativeTime(n.published_at) ?? ''}</span>
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}
