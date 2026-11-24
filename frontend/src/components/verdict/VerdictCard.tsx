import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'

/** One player judged on every lens at once (`models/verdict.py`): the score and its label, a bar per lens, his last six
 * gameweeks as blocks, and the sentence where the lenses disagree. */
export interface Verdict {
  player_id: number; name: string; team: string; team_code?: number | null; position: string; price: number; photo_code?: number | null
  score: number | null; label: string; mine?: boolean
  lenses: Record<string, number | null>
  facts: { points: number; minutes: number; points_per_90: number | null; last6_points: number; last6: number[]; xp_horizon: number | null; track_miss: number | null; crowd_net: number | null }
  flags: { check: string; level: 'red' | 'amber'; text: string }[]
  notes: string[]
}

export const LENS_NAME: Record<string, string> = {
  expected: 'Model', returns: 'Returns', value: 'Value', track: 'Track', fixtures: 'Fixtures', security: 'Nailed',
}
const LENS_ORDER = ['expected', 'returns', 'value', 'track', 'fixtures', 'security']
export const LABEL_STYLE: Record<string, string> = {
  Strong: 'bg-pitch-green text-pitch-green-ink', Good: 'bg-broadcast-blue text-broadcast-blue-ink', Mixed: 'bg-broadcast-gold text-broadcast-gold-ink',
  Weak: 'bg-spot text-ink', Avoid: 'bg-alert-red text-alert-red-ink', Unknown: 'bg-raised text-text',
}

export function barTone(v: number) {
  return v >= 75 ? 'bg-pitch-green' : v >= 50 ? 'bg-broadcast-blue' : v >= 30 ? 'bg-broadcast-gold' : 'bg-alert-red'
}

export function LensBars({ lenses, compact = false }: { lenses: Record<string, number | null>; compact?: boolean }) {
  return (
    <div className={compact ? 'space-y-0.5' : 'space-y-1'}>
      {LENS_ORDER.map((k) => {
        const v = lenses[k]
        return (
          <div key={k} className={`grid items-center gap-1.5 ${compact ? 'grid-cols-[3.6rem_minmax(0,1fr)_1.6rem] text-[10px]' : 'grid-cols-[4.4rem_minmax(0,1fr)_2rem] text-[11.5px]'}`}>
            <span className="font-bold uppercase tracking-wide text-text-muted">{LENS_NAME[k]}</span>
            <span className={`relative ${compact ? 'h-2' : 'h-2.5'} overflow-hidden bg-raised`}>
              {v != null && <span className={`absolute inset-y-0 left-0 ${barTone(v)} transition-all duration-700`} style={{ width: `${Math.max(3, v)}%` }} />}
              <span className="absolute inset-y-0 left-1/2 w-px bg-text/20" />
            </span>
            <span className="tabular text-right font-black text-text">{v ?? '–'}</span>
          </div>
        )
      })}
    </div>
  )
}

export function Last6({ pts }: { pts: number[] }) {
  return (
    <div className="flex items-end gap-0.5" title="FPL points, last six gameweeks">
      {pts.map((p, i) => (
        <span key={i} className={`tabular flex w-7 items-end justify-center text-[10.5px] font-black ${p >= 6 ? 'bg-pitch-green text-pitch-green-ink' : p >= 3 ? 'bg-broadcast-blue/80 text-broadcast-blue-ink' : 'bg-raised text-text-muted'}`}
          style={{ height: `${Math.min(34, 12 + Math.max(0, p) * 2)}px` }}>{p}</span>
      ))}
    </div>
  )
}

export function VerdictCard({ v }: { v: Verdict }) {
  const red = v.flags.some((f) => f.level === 'red')
  return (
    <Link to={`/player/${v.player_id}`} className={`group flex flex-col border-2 bg-paper transition-transform hover:-translate-y-0.5 ${red ? 'border-alert-red' : 'border-ink'} shadow-[4px_4px_0_var(--ink)]`}>
      <div className={`flex items-center justify-between px-3 py-1 font-display text-[13px] font-black uppercase ${LABEL_STYLE[v.label] ?? ''}`}>
        <span>{v.label}</span>
        <span className="tabular text-xl leading-none">{v.score ?? '–'}</span>
      </div>
      <div className="flex items-center gap-3 px-3 pt-2.5">
        <PlayerPhoto code={v.photo_code ?? null} teamCode={v.team_code ?? null} isGkp={v.position === 'GKP'} className="h-14 w-12 shrink-0" />
        <div className="min-w-0">
          <div className="font-display text-xl font-black uppercase leading-none text-text">{v.name}</div>
          <div className="mt-0.5 text-[11.5px] text-text-muted">{v.team} · £{v.price.toFixed(1)} · {v.facts.points} pts</div>
        </div>
      </div>
      <div className="px-3 pt-2">
        <div className="mb-0.5 text-[10px] font-bold uppercase tracking-wide text-text-faint">Last six gameweeks</div>
        <Last6 pts={v.facts.last6} />
      </div>
      <div className="px-3 pb-3 pt-2"><LensBars lenses={v.lenses} compact /></div>
      {(v.notes.length > 0 || v.flags.length > 0) && (
        <div className="mt-auto space-y-0.5 border-t border-divider px-3 py-2 text-[11.5px] leading-snug">
          {v.flags.map((f) => <div key={f.text} className={f.level === 'red' ? 'font-bold text-alert-red' : 'text-broadcast-gold'}>{f.level === 'red' ? '■' : '▲'} {f.text}</div>)}
          {v.notes.map((n) => <div key={n} className="text-text-muted">{n}</div>)}
        </div>
      )}
    </Link>
  )
}
