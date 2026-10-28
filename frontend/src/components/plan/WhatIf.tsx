import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchPlayersIndex, fetchWhatIf } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { PlayerIndexRow, WhatIfBrief } from '@/lib/types'
import { MadeTheseButton } from '@/components/command/MadeTransfer'

/** TRY YOUR OWN MOVES - up to three transfers typed in, priced the way the week
 * plan prices its own: best eleven, doubled captain, discounted bench, over the
 * next five gameweeks, less four points a move beyond the free transfers. The
 * squad is checked against the real rules (shape, three per club, the bank at
 * strict sale prices) before any number is shown. The plan's own gain sits beside
 * the result for direction, not size: it is over a longer horizon with free
 * re-planning each week. */

const MAX_MOVES = 3

function InPicker({ index, exclude, value, onPick }: {
  index: PlayerIndexRow[]
  exclude: Set<number>
  value: PlayerIndexRow | null
  onPick: (p: PlayerIndexRow | null) => void
}) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const hits = useMemo(() => {
    const n = q.trim().toLowerCase()
    if (!n) return []
    return index
      .filter((p) => !exclude.has(p.player_id) && (p.name.toLowerCase().includes(n) || p.full_name.toLowerCase().includes(n) || p.team_short.toLowerCase() === n))
      .slice(0, 7)
  }, [q, index, exclude])
  return (
    <div className="relative">
      {value && !open ? (
        <button type="button" onClick={() => { setOpen(true); setQ('') }} className="flex w-full items-center gap-2 rounded-md bg-raised px-3 py-2 text-left text-sm">
          <span className="font-bold text-text">{value.name}</span>
          <span className="text-xs text-text-muted">{value.team_short} · {value.position}{value.price !== null ? ` · £${value.price.toFixed(1)}m` : ''}</span>
          <span className="ml-auto text-[12px] text-text-faint">change</span>
        </button>
      ) : (
        <input
          autoFocus={open}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search the player coming in"
          className="w-full rounded-md bg-raised px-3 py-2 text-sm text-text outline-none placeholder:text-text-faint"
        />
      )}
      {hits.length > 0 && (
        <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-lg border border-divider bg-panel shadow-lg shadow-black/40">
          {hits.map((p) => (
            <button
              key={p.player_id}
              type="button"
              onMouseDown={() => { onPick(p); setOpen(false); setQ('') }}
              className="flex w-full items-center gap-3 border-b border-divider px-2 py-1.5 text-left last:border-b-0 hover:bg-raised"
            >
              <PlayerPhoto code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} className="h-8 w-6" />
              <span className="text-sm font-semibold text-text">{p.name}</span>
              <span className="text-xs text-text-muted">{p.team_short} · {p.position}{p.price !== null ? ` · £${p.price.toFixed(1)}m` : ''}</span>
              {p.owned !== null && <span className="tabular ml-auto text-[12px] text-text-faint">{p.owned.toFixed(1)}%</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Brief({ b }: { b: WhatIfBrief }) {
  return (
    <span className="inline-flex items-center gap-2">
      <PlayerPhoto code={b.photo_code} teamCode={b.team_code} isGkp={b.position === 'GKP'} className="h-8 w-6" />
      <Link to={`/player/${b.player_id}`} className="font-bold text-text hover:text-pitch-green">{b.name}</Link>
      <span className="text-xs text-text-muted">{b.team_short} · {b.position}{b.price !== null ? ` · £${b.price.toFixed(1)}m` : ''}</span>
      {b.status !== 'a' && b.news && (
        <span className="rounded bg-broadcast-gold/15 px-1.5 text-[12px] font-semibold text-broadcast-gold" title={b.news}>
          {b.status === 'd' ? 'doubt' : b.status === 'i' ? 'injured' : b.status === 's' ? 'suspended' : 'out'}
        </span>
      )}
    </span>
  )
}

export function WhatIf() {
  const base = useFetch(() => fetchWhatIf([]), [])
  const index = useFetch(fetchPlayersIndex, [])
  const [outs, setOuts] = useState<(number | null)[]>([null])
  const [ins, setIns] = useState<(PlayerIndexRow | null)[]>([null])
  const pairs = outs
    .map((o, i) => (o && ins[i] ? ([o, ins[i]!.player_id] as [number, number]) : null))
    .filter((p): p is [number, number] => p !== null)
  const key = pairs.map((p) => p.join(':')).join(',')
  const result = useFetch(() => (pairs.length ? fetchWhatIf(pairs) : Promise.resolve(null)), [key])
  const rows = index.status === 'ready' ? index.data.players : []

  if (base.status !== 'ready' || base.data.status !== 'ok') return null
  const squad = base.data.squad ?? []
  const used = new Set(outs.filter((o): o is number => o !== null))
  const taken = new Set([...squad.map((s) => s.player_id), ...ins.filter((p): p is PlayerIndexRow => p !== null).map((p) => p.player_id)])
  const r = result.status === 'ready' ? result.data : null

  const setOut = (i: number, v: number | null) => setOuts((o) => o.map((x, k) => (k === i ? v : x)))
  const setIn = (i: number, v: PlayerIndexRow | null) => setIns((o) => o.map((x, k) => (k === i ? v : x)))
  const addRow = () => { setOuts((o) => [...o, null]); setIns((o) => [...o, null]) }
  const clear = () => { setOuts([null]); setIns([null]) }

  return (
    <section className="allow-overflow px-6 pb-6 pt-5">
      <div className="mb-1 flex flex-wrap items-baseline gap-x-5">
        <h2 className="font-display text-xl font-semibold text-text">Try your own moves</h2>
        <span className="text-[13px] text-text-faint">
          {base.data.free_transfers} free transfer{base.data.free_transfers === 1 ? '' : 's'} · bank £{((base.data.bank_tenths ?? 0) / 10).toFixed(1)}m · priced over the next {base.data.horizon} gameweeks
        </span>
      </div>
      <p className="mb-5 max-w-3xl text-[14px] leading-snug text-text-muted">
        Pick who goes out and who comes in. It checks the squad is legal and affordable, then compares the best eleven you could field after the moves with the one you have now, for each of the next five gameweeks.
      </p>

      <div className="space-y-3">
        {outs.map((o, i) => (
          <div key={i} className="grid grid-cols-[minmax(0,1fr)_2rem_minmax(0,1fr)] items-center gap-3">
            <select
              value={o ?? ''}
              onChange={(e) => setOut(i, e.target.value ? Number(e.target.value) : null)}
              className="w-full rounded-md bg-raised px-3 py-2 text-sm text-text outline-none"
            >
              <option value="">Player going out</option>
              {squad.map((s) => (
                <option key={s.player_id} value={s.player_id} disabled={used.has(s.player_id) && s.player_id !== o}>
                  {s.name} · {s.team_short} · {s.position}{s.price !== null ? ` · £${s.price.toFixed(1)}m` : ''}
                </option>
              ))}
            </select>
            <span className="text-center font-display text-lg text-text-faint">→</span>
            <InPicker index={rows} exclude={taken} value={ins[i]} onPick={(p) => setIn(i, p)} />
          </div>
        ))}
      </div>
      <div className="mt-3 flex gap-3">
        {outs.length < MAX_MOVES && (
          <button type="button" onClick={addRow} className="rounded-md bg-raised px-3 py-1.5 text-[13px] font-semibold text-text-muted hover:text-text">Add a move</button>
        )}
        {(outs.length > 1 || outs[0] !== null || ins[0] !== null) && (
          <button type="button" onClick={clear} className="rounded-md px-3 py-1.5 text-[13px] font-semibold text-text-faint hover:text-text">Clear</button>
        )}
      </div>

      {pairs.length > 0 && result.status === 'loading' && <p className="mt-6 text-sm text-text-muted">Pricing the moves...</p>}
      {result.status === 'error' && <p className="mt-6 text-sm text-alert-red">{result.error.message}</p>}
      {r && r.problems && r.problems.length > 0 && (
        <ul className="mt-6 space-y-1 rounded-lg border border-alert-red/30 bg-alert-red/10 px-4 py-3 text-sm text-alert-red">
          {r.problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
      {r && r.totals && r.moves && (
        <div className="mt-6 grid grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] gap-10">
          <div>
            <div className="mb-2 text-[12px] text-text-faint">The moves</div>
            {r.moves.map((m) => (
              <div key={m.into.player_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-divider py-2">
                <Brief b={m.out} />
                <span className="text-text-faint">→</span>
                <Brief b={m.into} />
              </div>
            ))}
            <p className="mt-3 text-[13px] text-text-muted">
              {r.hits ? <><span className="font-bold text-alert-red">{r.hits} hit{r.hits === 1 ? '' : 's'} (−{r.hit_cost})</span>. </> : 'Within your free transfers. '}
              Bank after: <span className="tabular font-bold text-text">£{((r.bank_after_tenths ?? 0) / 10).toFixed(1)}m</span> at strict sale prices.
            </p>
            {(r.problems ?? []).length === 0 && (
              <MadeTheseButton pairs={r.moves.map((m) => ({ outId: m.out.player_id, inId: m.into.player_id }))} />
            )}
          </div>
          <div>
            <div className="flex items-end gap-6">
              <div>
                <div className="text-[12px] text-text-faint">Net over {r.horizon} gameweeks, against keeping your fifteen</div>
                <div className={`tabular font-display text-6xl font-bold leading-none ${r.totals.gain_net >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
                  {r.totals.gain_net >= 0 ? '+' : ''}{r.totals.gain_net.toFixed(1)}
                </div>
              </div>
              <div className="pb-1 text-[13px] text-text-muted">
                <div>before <span className="tabular font-bold text-text">{r.totals.before.toFixed(1)}</span></div>
                <div>after <span className="tabular font-bold text-text">{r.totals.after.toFixed(1)}</span></div>
              </div>
            </div>
            <div className="mt-4 space-y-1">
              {(r.per_gw ?? []).map((g) => {
                const d = g.after - g.before
                const w = Math.min(Math.abs(d) * 10, 50)
                return (
                  <div key={g.event} className="grid grid-cols-[3rem_minmax(0,1fr)_3.5rem] items-center gap-3 text-[13px]">
                    <span className="font-mono text-text-faint">GW{g.event}</span>
                    <div className="relative h-2.5 w-full rounded bg-raised">
                      <div
                        className={`absolute inset-y-0 rounded ${d >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`}
                        style={{ left: d >= 0 ? '50%' : `${50 - w}%`, width: `${w}%` }}
                      />
                      <div className="absolute inset-y-[-2px] left-1/2 w-px bg-divider" />
                    </div>
                    <span className={`tabular text-right font-semibold ${d >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{d >= 0 ? '+' : ''}{d.toFixed(1)}</span>
                  </div>
                )
              })}
            </div>
            {r.plan && r.plan.gain !== null && (
              <p className="mt-4 text-[13px] leading-relaxed text-text-faint">
                The week plan&apos;s own moves ({r.plan.moves.join(', ') || 'roll'}) are worth {r.plan.gain >= 0 ? '+' : ''}{r.plan.gain.toFixed(1)}, but against rolling the transfer to next week, which would make the same move a week later. That gap is about one gameweek of the difference, so it is smaller than the figure here by design.
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
