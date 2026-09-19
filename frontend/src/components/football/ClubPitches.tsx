import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ShotAtlas, type Hover } from '@/components/football/ShotAtlas'
import type { AtlasShot } from '@/lib/types'

/** WHERE THEY SHOOT / WHERE THEY CONCEDE - two pitches, one club.
 *
 * Left, every shot this club has taken this season; right, every shot it
 * has faced, drawn on the same attacking half from the opponent's point
 * of view. Dot area is xG, filled only for a goal, your own players gold
 * on the left. Read side by side they say whether a club's goals come
 * from the six-yard box or from range, and whether its defence keeps
 * shots to the edge of the area or lets them in close - the two things a
 * clean-sheet punt or an attacker pick actually hinge on. */

const OUTCOME_ONE: Record<string, string> = { Goal: 'Goal', AttemptSaved: 'Saved', Miss: 'Missed', Post: 'Hit the woodwork' }

function Rail({ shots, title }: { shots: AtlasShot[]; title: string }) {
  const goals = shots.filter((s) => s.outcome === 'Goal').length
  const xg = shots.reduce((a, s) => a + (s.xg ?? 0), 0)
  const inBox = shots.filter((s) => s.x >= 105 - 16.5 && Math.abs(s.y - 34) <= 20.16).length
  const top = useMemo(() => {
    const by = new Map<number, { player: string; team: string | null; n: number; xg: number; goals: number }>()
    for (const s of shots) {
      if (s.player_id === null) continue
      const p = by.get(s.player_id) ?? { player: s.player, team: s.team, n: 0, xg: 0, goals: 0 }
      p.n += 1; p.xg += s.xg ?? 0; p.goals += s.outcome === 'Goal' ? 1 : 0
      by.set(s.player_id, p)
    }
    return [...by.entries()].map(([id, p]) => ({ id, ...p })).sort((a, b) => b.xg - a.xg).slice(0, 5)
  }, [shots])
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-x-2">
        <div><div className="tabular font-display text-2xl font-bold text-text">{shots.length}</div><div className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">shots</div></div>
        <div><div className="tabular font-display text-2xl font-bold text-pitch-green">{xg.toFixed(1)}</div><div className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">xG</div></div>
        <div><div className="tabular font-display text-2xl font-bold text-text">{goals}</div><div className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">goals</div></div>
        <div><div className="tabular font-display text-2xl font-bold text-text">{shots.length ? Math.round((inBox / shots.length) * 100) : 0}%</div><div className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">in the box</div></div>
      </div>
      <div className={`tabular text-xs font-semibold ${goals - xg >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
        {goals - xg >= 0 ? '+' : ''}{(goals - xg).toFixed(1)} <span className="font-normal text-text-faint">goals minus xG · {shots.length ? (xg / shots.length).toFixed(2) : '—'} per shot</span>
      </div>
      <div className="border-t border-divider pt-3">
        <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">{title}</div>
        {top.map((p) => (
          <Link key={p.id} to={`/player/${p.id}`} className="grid grid-cols-[1fr_auto_auto_auto] items-baseline gap-2 border-b border-divider py-1.5 text-xs hover:bg-raised/60">
            <span className="truncate text-text">{p.player} <span className="text-text-faint">{p.team}</span></span>
            <span className="tabular text-text-muted">{p.n} sh</span>
            <span className="tabular text-pitch-green">{p.xg.toFixed(2)}</span>
            <span className="tabular font-semibold text-text">{p.goals} G</span>
          </Link>
        ))}
      </div>
    </div>
  )
}

export function ClubPitches({ shotsFor, shotsAgainst }: { shotsFor: AtlasShot[]; shotsAgainst: AtlasShot[] }) {
  const [hover, setHover] = useState<Hover>(null)
  const all = useMemo(() => () => true, [])
  const against = useMemo(() => shotsAgainst.map((s) => ({ ...s, mine: false })), [shotsAgainst])

  if (!shotsFor.length && !shotsAgainst.length) return null

  return (
    <div className="relative grid grid-cols-2 gap-px bg-divider">
      <div className="bg-void px-8 py-6">
        <div className="mb-3 flex items-baseline gap-3">
          <span className="font-display text-2xl font-bold uppercase text-text">Where they shoot</span>
          <span className="text-[11px] text-text-faint">every shot this season</span>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_200px] gap-5">
          <div className="h-[380px]"><ShotAtlas shots={shotsFor} visible={all} heroId={null} showHeat={false} onHover={setHover} /></div>
          <Rail shots={shotsFor} title="Their shooters" />
        </div>
      </div>
      <div className="bg-void px-8 py-6">
        <div className="mb-3 flex items-baseline gap-3">
          <span className="font-display text-2xl font-bold uppercase text-text">Where they concede</span>
          <span className="text-[11px] text-text-faint">every shot faced, from the opponent's end</span>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_200px] gap-5">
          <div className="h-[380px]"><ShotAtlas shots={against} visible={all} heroId={null} showHeat={false} onHover={setHover} /></div>
          <Rail shots={against} title="Who shot at them" />
        </div>
      </div>
      {hover && (
        <div className="pointer-events-none fixed z-50 border-l-2 bg-raised px-3 py-2 text-xs"
             style={{ left: hover.px + 14, top: hover.py + 14, borderColor: hover.shot.mine ? 'var(--broadcast-gold)' : 'var(--broadcast-blue)' }}>
          <div className="font-display text-base font-bold uppercase text-text">{hover.shot.player} <span className="text-text-faint">{hover.shot.team}</span></div>
          <div className="tabular mt-0.5 text-text-muted">
            {hover.shot.minute !== null ? `${hover.shot.minute}' · ` : ''}
            <span className={hover.shot.outcome === 'Goal' ? 'font-bold text-pitch-green' : ''}>{OUTCOME_ONE[hover.shot.outcome] ?? hover.shot.outcome}</span>
            {' · '}{hover.shot.xg !== null ? `${hover.shot.xg.toFixed(2)} xG` : 'no xG'}
          </div>
        </div>
      )}
    </div>
  )
}
