import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { useLiveMeta } from '@/lib/useLiveMeta'

/** A broadcast lower third on every screen when one of your fifteen scores, sets one up or is sent off: read from the
 * shared live snapshot (a new goal, assist or red card against the previous poll), with the points it brought and a
 * link to Matchday TV. Matchday TV runs its own full-screen version, so this stays off there. */
interface Flash { id: number; kind: 'GOAL' | 'ASSIST' | 'RED CARD'; name: string; points: number; captain: boolean; code: number | null; team: number | null }

export function GoalFlash() {
  const snap = useLiveMeta()
  const { pathname } = useLocation()
  const prev = useRef<{ pts: Map<number, number>; ev: Map<string, number> } | null>(null)
  const [queue, setQueue] = useState<Flash[]>([])
  const squad = useMemo(() => new Map((snap?.squad ?? []).map((s) => [s.player_id, s])), [snap])

  useEffect(() => {
    if (!snap) return
    const pts = new Map((snap.points?.by_player ?? []).map((b) => [b.player_id, b.points * Math.max(1, b.multiplier)]))
    const ev = new Map((snap.match_events ?? []).map((e) => [`${e.player_id}:${e.kind}`, e.count]))
    const before = prev.current
    prev.current = { pts, ev }
    if (!before) return
    const fresh: Flash[] = []
    for (const e of snap.match_events ?? []) {
      if (e.count <= (before.ev.get(`${e.player_id}:${e.kind}`) ?? 0) || !squad.has(e.player_id)) continue
      const s = squad.get(e.player_id)!
      fresh.push({
        id: Date.now() + fresh.length, kind: e.kind === 'goal' ? 'GOAL' : e.kind === 'assist' ? 'ASSIST' : 'RED CARD',
        name: e.web_name ?? s.web_name ?? '', points: (pts.get(e.player_id) ?? 0) - (before.pts.get(e.player_id) ?? 0),
        captain: s.is_captain, code: s.photo_code ?? null, team: s.team_code ?? null,
      })
    }
    if (fresh.length) setQueue((q) => [...q, ...fresh].slice(-4))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap])

  const head = queue[0]
  useEffect(() => {
    if (!head) return
    const t = window.setTimeout(() => setQueue((q) => q.slice(1)), 7000)
    return () => window.clearTimeout(t)
  }, [head])

  if (!head || pathname === '/tv') return null
  const red = head.kind === 'RED CARD'
  return (
    <Link key={head.id} to="/tv" className="goalflash fixed bottom-6 left-[calc(var(--sidebar-width,13rem)+1.5rem)] z-[65] flex items-stretch shadow-[8px_8px_0_var(--ink)]">
      <div className={`goalflash-kind flex items-center px-5 font-display text-[3.2rem] font-black uppercase leading-none ${red ? 'bg-alert-red text-paper' : 'bg-spot text-ink'}`}>{head.kind}</div>
      <div className="goalflash-body flex items-center gap-3 border-y-2 border-r-2 border-ink bg-ink py-2 pl-3 pr-6">
        <PlayerPhoto code={head.code} teamCode={head.team} className="h-14 w-11" />
        <div>
          <div className="font-display text-[2rem] font-black uppercase leading-none text-paper">{head.name}</div>
          <div className="mt-1 text-[12px] font-bold uppercase tracking-[0.14em] text-broadcast-gold">
            {head.points > 0 ? `+${head.points} points${head.captain ? ' · armband' : ''}` : head.points < 0 ? `${head.points} points` : 'your squad'} · Matchday TV →
          </div>
        </div>
      </div>
    </Link>
  )
}
