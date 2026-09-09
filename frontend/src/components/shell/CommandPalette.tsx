import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

interface Item {
  label: string
  hint: string
  to: string
}

const ITEMS: Item[] = [
  { label: 'Command', hint: 'Current decision', to: '/' },
  { label: 'My Team', hint: 'Squad & pitch', to: '/my-team' },
  { label: 'Plan', hint: 'Strategic trajectory', to: '/plan' },
  { label: 'Football', hint: 'Match intelligence', to: '/football' },
  { label: 'Scout', hint: 'Player market', to: '/scout' },
  { label: 'Advanced', hint: 'System diagnostics', to: '/advanced' },
  { label: 'Live', hint: 'Live matches & events', to: '/live' },
]

/** Real global Cmd/Ctrl+K navigation palette (Part 16 - "a real capability,
 * not decoration"). Modeled on the researched Action Search Bar pattern
 * (kokonutd, `docs/history/48-21st-visual-grammar.md`'s SEARCH section) - an input
 * that filters a real action list, arrow-key navigable. Screen-navigation
 * only in this v1 - player/action search (Part 16's fuller scope) needs a
 * real cross-screen player index, a disclosed, scoped follow-up. */
export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return ITEMS
    return ITEMS.filter((i) => i.label.toLowerCase().includes(q) || i.hint.toLowerCase().includes(q))
  }, [query])

  function go(item: Item) {
    navigate(item.to)
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
              go(filtered[active])
            }
          }}
          placeholder="Jump to a screen..."
          className="w-full border-b-2 border-divider bg-transparent px-4 py-3 text-text placeholder:text-text-faint focus:outline-none"
        />
        <div className="max-h-80 overflow-y-auto">
          {filtered.map((item, i) => (
            <button
              key={item.to}
              onClick={() => go(item)}
              className={`flex w-full items-center justify-between px-4 py-2.5 text-left text-sm ${i === active ? 'bg-pitch-green text-pitch-green-ink' : 'text-text hover:bg-raised'}`}
            >
              <span className="font-bold">{item.label}</span>
              <span className={i === active ? 'text-pitch-green-ink/70' : 'text-text-faint'}>{item.hint}</span>
            </button>
          ))}
          {filtered.length === 0 && <div className="px-4 py-3 text-sm text-text-faint">No match.</div>}
        </div>
      </div>
    </div>
  )
}
