import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { LABEL_STYLE, LENS_NAME, barTone, type Verdict } from '@/components/verdict/VerdictCard'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** The squad at a glance on Command: each of the fifteen with his verdict, a strip per lens and his last six weeks,
 * weakest first, so who to sell and who to keep is visible before any table (`/verdict` for the full board). */
export function SquadVerdict() {
  const state = useFetch(() => getJson<{ squad: Verdict[] }>('/api/verdicts'), [])
  if (state.status !== 'ready') return null
  const squad = [...state.data.squad].sort((a, b) => (a.score ?? 0) - (b.score ?? 0))
  const lensKeys = ['expected', 'returns', 'value', 'track', 'fixtures', 'security']
  return (
    <section className="bare">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-text">Your squad, judged</h2>
        <div className="flex flex-wrap items-center gap-3 text-[11px] font-bold uppercase text-text-muted">
          {lensKeys.map((k, i) => <span key={k}>{i + 1} {LENS_NAME[k]}</span>)}
          <Link to="/verdict" className="border-2 border-ink bg-ink px-2 py-0.5 text-paper hover:bg-spot hover:text-ink">Full verdict board →</Link>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 md:grid-cols-5 xl:grid-cols-[repeat(15,minmax(0,1fr))]">
        {squad.map((v) => {
          const red = v.flags.some((f) => f.level === 'red')
          return (
            <Link key={v.player_id} to={`/player/${v.player_id}`} title={[...v.notes, ...v.flags.map((f) => f.text)].join(' · ')}
              className={`group flex flex-col border-2 bg-paper transition-transform hover:-translate-y-0.5 ${red ? 'border-alert-red' : 'border-ink'}`}>
              <div className={`flex items-center justify-between px-1.5 py-0.5 text-[10px] font-black uppercase ${LABEL_STYLE[v.label]}`}>
                <span>{v.label}</span><span className="tabular">{v.score}</span>
              </div>
              <div className="flex justify-center pt-1"><PlayerPhoto code={v.photo_code ?? null} teamCode={v.team_code ?? null} isGkp={v.position === 'GKP'} className="h-11 w-10" bare /></div>
              <div className="truncate px-1 text-center font-display text-[13px] font-black uppercase leading-tight text-text">{v.name}</div>
              <div className="flex h-6 items-end gap-px px-1.5 pb-1">
                {lensKeys.map((k) => {
                  const x = v.lenses[k]
                  return <span key={k} className={`flex-1 ${x == null ? 'bg-raised' : barTone(x)}`} style={{ height: `${Math.max(12, x ?? 12)}%` }} title={`${LENS_NAME[k]} ${x ?? '–'}`} />
                })}
              </div>
              <div className="tabular border-t border-divider px-1 py-0.5 text-center text-[10.5px] font-bold text-text-muted">{v.facts.last6.join(' ')}</div>
            </Link>
          )
        })}
      </div>
    </section>
  )
}
