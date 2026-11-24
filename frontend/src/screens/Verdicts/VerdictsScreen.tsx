import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Info } from '@/components/ui/Info'
import { ScreenError, Skel } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { LABEL_STYLE, LENS_NAME, Last6, VerdictCard, barTone, type Verdict } from '@/components/verdict/VerdictCard'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** THE VERDICT BOARD: every player judged on the model, his real returns, value, track record against the model,
 * fixtures and whether he is nailed - your squad first, then the league, sortable by any lens. */
interface Payload { weights: Record<string, number>; squad: Verdict[]; players: Verdict[] }

const POSITIONS = ['ALL', 'GKP', 'DEF', 'MID', 'FWD'] as const
const SORTS = ['score', 'expected', 'returns', 'value', 'track', 'fixtures'] as const

export function VerdictsScreen() {
  const state = useFetch(() => getJson<Payload>('/api/verdicts'), [])
  const [pos, setPos] = useState<(typeof POSITIONS)[number]>('ALL')
  const [sort, setSort] = useState<(typeof SORTS)[number]>('score')
  const [maxPrice, setMaxPrice] = useState(16)
  const rows = useMemo(() => {
    if (state.status !== 'ready') return []
    return state.data.players
      .filter((p) => (pos === 'ALL' || p.position === pos) && p.price <= maxPrice)
      .sort((a, b) => ((sort === 'score' ? b.score : b.lenses[sort]) ?? -1) - ((sort === 'score' ? a.score : a.lenses[sort]) ?? -1))
      .slice(0, 80)
  }, [state, pos, sort, maxPrice])
  if (state.status === 'loading') return <div className="space-y-4 p-10"><Skel className="h-12 w-80" /><Skel className="h-96 w-full" /></div>
  if (state.status === 'error') return <ScreenError title="The verdict board is unavailable" description="The verdicts could not be built." message={state.error.message} />
  const d = state.data
  const squadPos = (p: string) => d.squad.filter((v) => v.position === p)
  const weak = d.squad.filter((v) => v.label === 'Weak' || v.label === 'Avoid' || v.flags.some((f) => f.level === 'red'))
  return (
    <div className="space-y-8 px-10 pb-16 pt-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-5xl font-black uppercase leading-none text-text">The Verdict</h1>
            <Info label="How a verdict is made">
              Six lenses, each a percentile among players of the same position with 450+ minutes: the model&apos;s projection over the next five gameweeks, his real FPL points per 90 (season and last six), points per £m, how far his real points have run above or below the model&apos;s frozen projections, his club&apos;s next five fixtures, and whether he is nailed (benched last match, starts, flags, a regular coming back). Score = {Object.entries(d.weights).map(([k, w]) => `${Math.round(w * 100)}% ${LENS_NAME[k]?.toLowerCase() ?? k}`).join(', ')}. The model is the best single forecast, so it carries the most, but no lens decides alone: a player the model likes whose returns, value and track all say otherwise is not protected. Only a Strong verdict stops the plan selling him; Weak or Avoid stops it buying him.
            </Info>
          </div>
          <p className="mt-2 max-w-2xl text-[15px] text-text-muted">The model, the points and the eye in one picture. Green is good on that lens, red is bad; the middle line is the position&apos;s median.</p>
        </div>
        {weak.length > 0 && (
          <div className="border-2 border-alert-red bg-alert-red/10 px-4 py-2">
            <div className="text-[11px] font-black uppercase tracking-widest text-alert-red">In your squad, worth a look</div>
            <div className="font-display text-xl font-black uppercase text-text">{weak.map((v) => v.name).join(' · ')}</div>
          </div>
        )}
      </header>

      <section>
        <h2 className="mb-3 font-display text-text">Your fifteen</h2>
        <div className="space-y-4">
          {(['GKP', 'DEF', 'MID', 'FWD'] as const).map((p) => (
            <div key={p} className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
              {squadPos(p).map((v) => <VerdictCard key={v.player_id} v={v} />)}
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h2 className="font-display text-text">The league</h2>
          <div className="flex gap-1">
            {POSITIONS.map((p) => (
              <button key={p} type="button" onClick={() => setPos(p)} className={`border-2 border-ink px-2.5 py-0.5 font-display text-[13px] font-black uppercase ${pos === p ? 'bg-ink text-paper' : 'bg-paper text-text'}`}>{p}</button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-[12px] font-bold uppercase text-text-muted">
            Max £{maxPrice.toFixed(1)}
            <input type="range" min={4} max={16} step={0.5} value={maxPrice} onChange={(e) => setMaxPrice(Number(e.target.value))} className="accent-[var(--spot)]" />
          </label>
        </div>
        <div className="overflow-x-auto border-2 border-ink bg-paper">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b-2 border-ink bg-ink text-left text-[11px] uppercase tracking-wide text-paper">
                <th className="px-2 py-2">Player</th>
                <th className="cursor-pointer px-2" onClick={() => setSort('score')}>Verdict{sort === 'score' ? ' ▼' : ''}</th>
                {(['expected', 'returns', 'value', 'track', 'fixtures'] as const).map((k) => (
                  <th key={k} className="cursor-pointer px-2" onClick={() => setSort(k)}>{LENS_NAME[k]}{sort === k ? ' ▼' : ''}</th>
                ))}
                <th className="px-2">Last 6</th>
                <th className="px-2">Why</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((v) => (
                <tr key={v.player_id} className={`border-b border-divider ${v.mine ? 'bg-spot/10' : ''}`}>
                  <td className="px-2 py-1.5">
                    <Link to={`/player/${v.player_id}`} className="flex items-center gap-2 hover:underline">
                      <PlayerPhoto code={v.photo_code ?? null} teamCode={v.team_code ?? null} isGkp={v.position === 'GKP'} className="h-8 w-7" bare />
                      <span className="font-display font-black uppercase text-text">{v.name}</span>
                      <span className="text-[11px] text-text-faint">{v.team} {v.position} £{v.price.toFixed(1)}{v.mine ? ' · yours' : ''}</span>
                    </Link>
                  </td>
                  <td className="px-2"><span className="tabular mr-1.5 font-display text-lg font-black text-text">{v.score}</span><span className={`px-1 text-[10px] font-black uppercase ${LABEL_STYLE[v.label]}`}>{v.label}</span></td>
                  {(['expected', 'returns', 'value', 'track', 'fixtures'] as const).map((k) => {
                    const x = v.lenses[k]
                    return (
                      <td key={k} className="w-24 px-2">
                        <span className="relative block h-3 bg-raised">{x != null && <span className={`absolute inset-y-0 left-0 ${barTone(x)}`} style={{ width: `${Math.max(3, x)}%` }} />}</span>
                      </td>
                    )
                  })}
                  <td className="px-2"><Last6 pts={v.facts.last6} /></td>
                  <td className="max-w-xs px-2 text-[11.5px] text-text-muted">{v.notes[0] ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
