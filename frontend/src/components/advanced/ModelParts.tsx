import { useState } from 'react'
import { Disclosure } from '@/components/ui/kit'
import { fetchComponentsPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { ComponentRow } from '@/lib/types'

const PARTS: [string, string][] = [
  ['appearance', 'Appearance'], ['goals', 'Goals'], ['assists', 'Assists'], ['bonus', 'Bonus'], ['clean_sheet', 'Clean sheet'],
  ['conceded', 'Conceded'], ['saves', 'Saves'], ['defcon', 'Def. actions'], ['cards', 'Cards'], ['total', 'Total'],
]
const POSITIONS = ['GKP', 'DEF', 'MID', 'FWD']

function Cell({ r }: { r: ComponentRow | undefined }) {
  if (!r || (Math.abs(r.predicted) < 0.005 && Math.abs(r.actual) < 0.005)) return <td className="px-2 py-2 text-center text-text-faint">·</td>
  const rel = Math.abs(r.gap) / Math.max(Math.abs(r.predicted), 0.25)
  const tone = rel < 0.1 ? 'text-text-muted' : r.gap > 0 ? 'text-broadcast-blue' : 'text-alert-red'
  return (
    <td className="px-2 py-2 text-center">
      <div className={`tabular font-display text-[17px] font-black leading-none ${tone}`}>{r.gap >= 0 ? '+' : ''}{r.gap.toFixed(2)}</div>
      <div className="tabular mt-0.5 text-[11px] text-text-faint">{r.predicted.toFixed(2)} → {r.actual.toFixed(2)}</div>
    </td>
  )
}

/** HOW THE MODEL DID, BY PART: for every player whose projection was frozen at a deadline, each part of it set against the
 * points FPL actually gave for that part, per position. Blue ran cold (players scored more than projected), red ran hot. */
export function ModelParts() {
  const state = useFetch(fetchComponentsPayload, [])
  const [who, setWho] = useState<'all' | 'contenders'>('contenders')
  const data = state.status === 'ready' ? state.data : null
  const rows = data ? data[who] : []
  const find = (pos: string, part: string) => rows.find((r) => r.position === pos && r.part === part)
  return (
    <Disclosure
      title="How the model did, by part"
      summary={data && data.events.length ? `GW${data.events.join(', GW')} · ${data.players} player-gameweeks` : 'first reading after GW9 settles'}
    >
      {!data || !data.events.length ? (
        <p className="max-w-3xl text-[14px] text-text-muted">
          From GW9 every projection is frozen at the deadline with its parts. Once a gameweek's points are in, each part is laid
          against what FPL gave for it, by position: where the model runs hot or cold shows here, gameweek by gameweek.
        </p>
      ) : (
        <>
          <div className="mb-3 flex items-center gap-2">
            {(['contenders', 'all'] as const).map((k) => (
              <button key={k} type="button" onClick={() => setWho(k)}
                className={`border-2 border-ink px-2.5 py-1 font-display text-[13px] font-black uppercase ${who === k ? 'bg-ink text-paper' : 'bg-paper text-text'}`}>
                {k === 'contenders' ? 'The 150 highest projections' : 'Everyone recorded'}
              </button>
            ))}
            <span className="ml-2 text-[12.5px] text-text-faint">actual minus predicted, points a player-gameweek; blue ran cold, red ran hot</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b-2 border-ink">
                  <th className="px-2 py-2 text-left text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint" />
                  {PARTS.map(([, label]) => (
                    <th key={label} className="px-2 py-2 text-center font-display text-[13px] font-black uppercase text-text">{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {POSITIONS.map((pos) => {
                  const n = find(pos, 'total')
                  return (
                    <tr key={pos} className="border-b border-divider">
                      <td className="px-2 py-2">
                        <div className="font-display text-lg font-black text-text">{pos}</div>
                        {n && <div className="text-[11px] text-text-faint">n {n.n} · {n.gameweeks} GW</div>}
                      </td>
                      {PARTS.map(([key]) => <Cell key={key} r={find(pos, key)} />)}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 max-w-4xl text-[12.5px] text-text-faint">
            Single-fixture gameweeks and the current model version only. One gameweek is one scoring level (a low-scoring week makes
            every attacking part look hot), so read a part across several gameweeks before acting on it. Own goals and penalty saves or
            misses are not projected and are left out of both sides.
          </p>
        </>
      )}
    </Disclosure>
  )
}
