import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchPlayersIndex } from '@/lib/api'
import type { PlayerIndexRow } from '@/lib/types'

interface Item {
  label: string
  hint: string
  to: string
  player?: PlayerIndexRow
}

const ITEMS: Item[] = [
  { label: 'Command', hint: 'Current decision', to: '/' },
  { label: 'My Team', hint: 'Squad & pitch', to: '/my-team' },
  { label: 'Plan', hint: 'Strategic trajectory', to: '/plan' },
  { label: 'Football', hint: 'Match intelligence', to: '/football' },
  { label: 'Desk', hint: 'News, video, price board', to: '/desk' },
  { label: 'Previews', hint: 'Next gameweek, match by match', to: '/previews' },
  { label: 'Field', hint: 'This week against everyone else', to: '/field' },
  { label: 'Audit', hint: 'Luck, deserved points, match rebuilds', to: '/audit' },
  { label: 'Compare', hint: 'Two players, side by side', to: '/compare' },
  { label: 'Scout', hint: 'Player market', to: '/scout' },
  { label: 'Advanced', hint: 'System diagnostics', to: '/advanced' },
  { label: 'Live', hint: 'Live matches & events', to: '/live' },
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
    return [...found, ...screens]
  }, [query, players])

  function go(item: Item, compare = false) {
    navigate(compare && item.player ? `/compare?a=${item.player.player_id}` : item.to)
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
          className="w-full border-b-2 border-divider bg-transparent px-4 py-3 text-text placeholder:text-text-faint focus:outline-none"
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
          <div className="border-t border-divider px-4 py-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">Enter opens the file · Shift+Enter compares</div>
        )}
      </div>
    </div>
  )
}
