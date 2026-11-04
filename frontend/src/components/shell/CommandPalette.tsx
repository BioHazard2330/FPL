import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchPlayersIndex } from '@/lib/api'
import type { PlayerIndexRow } from '@/lib/types'
import { DESTINATIONS } from '@/lib/nav'

interface Item {
  label: string
  hint: string
  to: string
  player?: PlayerIndexRow
}

const HINTS: Record<string, string> = {
  '/': 'The call this week', '/my-team': 'Squad and pitch', '/decide': 'One call on each question, then lock it', '/plan': 'Transfers over the horizon', '/war-room': 'Drag in a transfer, priced at once',
  '/album': 'The fifteen as stickers', '/programme': 'This gameweek as a matchday programme cover', '/eye': 'Your read of each player', '/live': 'Matches in play, auto-subs, departures',
  '/matchweek': 'Every match of the week', '/map': 'The gameweek on a map: grounds, journeys, weather', '/table': 'How each side plays', '/previews': 'Next gameweek, match by match',
  '/football': 'Your clubs', '/atlas': 'Every shot of the season', '/scout': 'Player market', '/compare': 'Two players side by side',
  '/explorer': 'Filter every player', '/desk': 'News, video, community', '/review': 'Last gameweek read back',
  '/versus': 'Your season against the managers ranked around 10,000', '/story': 'Your season as a scroll-driven film', '/leagues': 'Rivals and odds', '/field': 'This week against everyone',
  '/audit': 'Luck and deserved points', '/receipts': 'How the model has done', '/advanced': 'System health',
}
const ITEMS: Item[] = [
  ...DESTINATIONS.map((d) => ({ label: d.label, hint: HINTS[d.to] ?? '', to: d.to })),
  { label: 'Matchday TV', hint: 'Full-screen broadcast for a second screen', to: '/tv' },
  { label: 'Screen wipes on / off', hint: 'The broadcast wipe between screens', to: '#stinger' },
]

const MAX_PLAYERS = 6

/** Global Cmd/Ctrl+K palette: jump to a screen, or type two letters of a
 * player's name to open his file (Enter) or start a comparison with him
 * (Shift+Enter). The player list is the same index the Compare screen uses,
 * fetched the first time the palette opens. */
export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [players, setPlayers] = useState<PlayerIndexRow[] | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      }
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  useEffect(() => {
    if (open && players === null) {
      fetchPlayersIndex()
        .then((r) => setPlayers(r.players))
        .catch(() => setPlayers([]))
    }
  }, [open, players])

  const filtered = useMemo<Item[]>(() => {
    const q = query.trim().toLowerCase()
    if (!q) return ITEMS
    const screens = ITEMS.filter((i) => i.label.toLowerCase().includes(q) || i.hint.toLowerCase().includes(q))
    const found =
      q.length >= 2 && players
        ? players
            .filter((p) => p.name.toLowerCase().includes(q) || p.full_name.toLowerCase().includes(q))
            .slice(0, MAX_PLAYERS)
            .map<Item>((p) => ({
              label: p.name,
              hint: `${p.team_short} · ${p.position}${p.price !== null ? ` · £${p.price.toFixed(1)}m` : ''}`,
              to: `/player/${p.player_id}`,
              player: p,
            }))
        : []
    const starts = (label: string) => label.toLowerCase().split(/\s+/).some((w) => w.startsWith(q))
    const lead = screens.filter((i) => starts(i.label))
    const rest = screens.filter((i) => !starts(i.label))
    const byStart = [...found].sort((a, b) => Number(starts(b.label)) - Number(starts(a.label)))
    return [...lead, ...byStart, ...rest]
  }, [query, players])

  function go(item: Item, compare = false) {
    if (item.to === '#stinger') {
      try {
        localStorage.setItem('fpl-stinger', localStorage.getItem('fpl-stinger') === 'off' ? 'on' : 'off')
      } catch {
        /* storage blocked: wipes stay as they are */
      }
      setOpen(false)
      return
    }
    navigate(compare && item.player ? `/compare?a=${item.player.player_id}` : item.to, { viewTransition: true })
    setOpen(false)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-void/80 pt-32" onClick={() => setOpen(false)}>
      <div className="w-full max-w-lg border-2 border-divider bg-panel" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setActive(0)
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setActive((a) => Math.min(a + 1, filtered.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setActive((a) => Math.max(a - 1, 0))
            } else if (e.key === 'Enter' && filtered[active]) {
              go(filtered[active], e.shiftKey)
            }
          }}
          placeholder="Jump to a screen or a player..."
          className="w-full border-b border-divider bg-transparent px-4 py-3 text-text placeholder:text-text-faint focus:outline-none"
        />
        <div className="max-h-96 overflow-y-auto">
          {filtered.map((item, i) => (
            <button
              key={item.to}
              onClick={(e) => go(item, e.shiftKey)}
              className={`flex w-full items-center gap-3 px-4 py-2 text-left text-sm ${i === active ? 'bg-pitch-green text-pitch-green-ink' : 'text-text hover:bg-raised'}`}
            >
              {item.player && <PlayerPhoto code={item.player.photo_code} teamCode={item.player.team_code} isGkp={item.player.position === 'GKP'} className="h-9 w-7" />}
              <span className="font-bold">{item.label}</span>
              <span className={`ml-auto ${i === active ? 'text-pitch-green-ink/70' : 'text-text-faint'}`}>{item.hint}</span>
            </button>
          ))}
          {filtered.length === 0 && <div className="px-4 py-3 text-sm text-text-faint">No match.</div>}
        </div>
        {filtered.some((i) => i.player) && (
          <div className="border-t border-divider px-4 py-1.5 text-[12px] text-text-faint">Enter opens the file · Shift+Enter compares</div>
        )}
      </div>
    </div>
  )
}
