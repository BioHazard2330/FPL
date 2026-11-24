import { LABEL_STYLE, LensBars, Last6, type Verdict } from '@/components/verdict/VerdictCard'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** The verdict at the top of a player page: score, label, every lens, his last six weeks and where the lenses disagree. */
export function PlayerVerdict({ playerId }: { playerId: number }) {
  const state = useFetch(() => getJson<{ player: Verdict | null }>(`/api/verdicts?player=${playerId}`), [playerId])
  if (state.status !== 'ready' || !state.data.player) return null
  const v = state.data.player
  return (
    <section className="border-b border-divider px-10 py-8">
      <div className="grid gap-6 lg:grid-cols-[14rem_minmax(0,1fr)_minmax(0,1fr)]">
        <div className={`flex flex-col justify-between p-4 ${LABEL_STYLE[v.label] ?? ''}`}>
          <div className="text-[12px] font-black uppercase tracking-widest opacity-80">The verdict</div>
          <div className="tabular font-display text-7xl font-black leading-none">{v.score ?? '–'}</div>
          <div className="font-display text-2xl font-black uppercase">{v.label}</div>
        </div>
        <div>
          <div className="mb-2 text-[12px] font-bold uppercase tracking-wide text-text-faint">Every lens, against his position</div>
          <LensBars lenses={v.lenses} />
        </div>
        <div className="space-y-3">
          <div>
            <div className="mb-1 text-[12px] font-bold uppercase tracking-wide text-text-faint">Last six gameweeks · {v.facts.points} points this season</div>
            <Last6 pts={v.facts.last6} />
          </div>
          {[...v.flags.map((f) => ({ t: f.text, red: f.level === 'red', flag: true })), ...v.notes.map((n) => ({ t: n, red: false, flag: false }))].map((x) => (
            <div key={x.t} className={`text-[14px] leading-snug ${x.red ? 'font-bold text-alert-red' : x.flag ? 'text-broadcast-gold' : 'text-text'}`}>{x.red ? '■ ' : x.flag ? '▲ ' : '— '}{x.t}</div>
          ))}
        </div>
      </div>
    </section>
  )
}
