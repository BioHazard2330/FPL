import { useMemo, useState } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Masthead } from '@/components/shell/Masthead'
import { crestUrl, fetchScoutPayload, shirtUrl } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { OpportunityRow, ScoutPlayerRow } from '@/lib/types'

const POSITIONS = ['ALL', 'GKP', 'DEF', 'MID', 'FWD'] as const
type SortKey = 'total_points' | 'price_m' | 'owned_pct' | 'form' | 'xgi'
const SORT_LABEL: Record<SortKey, string> = { total_points: 'Pts', price_m: 'Price', owned_pct: 'Owned', form: 'Form', xgi: 'xGI' }

const PRICE_FLOOR = 3.5
const PRICE_CEIL = 16.0

const CONFIDENCE_COLOR: Record<string, string> = {
  HIGH: 'text-pitch-green', VERY_HIGH: 'text-pitch-green', MEDIUM: 'text-broadcast-gold', LOW: 'text-alert-red', VERY_LOW: 'text-alert-red',
}

function OpportunityRowView({ r }: { r: OpportunityRow }) {
  const crest = crestUrl(r.team_code)
  return (
    <div className="flex flex-wrap items-baseline gap-3 border-b-2 border-divider py-2.5 text-sm last:border-b-0">
      {crest && <img src={crest} alt="" className="h-4 w-4 shrink-0 rounded-full" />}
      <span className="font-bold text-text">{r.name}</span>
      <span className="bg-raised px-1.5 py-0.5 text-[10px] font-bold text-text-muted">{r.position}</span>
      {r.price_m !== null && <span className="tabular text-text-muted">£{r.price_m.toFixed(1)}m</span>}
      {r.xp !== null && <span className="tabular font-semibold text-pitch-green">{r.xp.toFixed(1)} xP</span>}
      <span className="text-text-muted">{r.why_now}</span>
      {r.risk && <span className="italic text-broadcast-gold">{r.risk}</span>}
      <span className={`ml-auto shrink-0 text-[10px] font-bold uppercase tracking-wide ${CONFIDENCE_COLOR[r.confidence] ?? 'text-text-faint'}`}>{r.confidence}</span>
    </div>
  )
}

function PlayerDetailSheet({ player, onClose }: { player: ScoutPlayerRow | null; onClose: () => void }) {
  const shirt = player ? shirtUrl(player.team_code, player.position === 'GKP', 220) : null
  const crest = player ? crestUrl(player.team_code) : null
  const stats: { label: string; value: string | number | null }[] = player
    ? [
        { label: 'Total points', value: player.total_points },
        { label: 'Form', value: player.form },
        { label: 'xGI', value: player.xgi },
        { label: 'Goals', value: player.goals },
        { label: 'Assists', value: player.assists },
        { label: 'Minutes', value: player.minutes },
        { label: 'Bonus', value: player.bonus },
      ]
    : []
  return (
    <Sheet open={player !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="border-l-2 border-divider bg-void p-0 sm:max-w-md">
        {player && (
          <>
            <SheetHeader className="border-b border-divider p-6">
              <div className="flex items-center gap-4">
                {shirt && <img src={shirt} alt="" className="h-16 w-16 object-contain" />}
                <div>
                  <SheetTitle className="font-display text-2xl font-bold text-text">{player.name}</SheetTitle>
                  <div className="mt-1 flex items-center gap-1.5 text-sm text-text-muted">
                    {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
                    {player.team_short} &middot; {player.position} &middot; {player.price_m !== null ? `£${player.price_m.toFixed(1)}m` : '—'}
                  </div>
                </div>
              </div>
            </SheetHeader>
            <div className="space-y-2 p-6 text-sm">
              {player.owned_pct !== null && (
                <div className="flex justify-between border-b border-divider pb-2">
                  <span className="text-text-muted">Ownership</span>
                  <span className="tabular font-bold text-text">{player.owned_pct.toFixed(1)}%</span>
                </div>
              )}
              {stats.map((s) => (
                <div key={s.label} className="flex justify-between border-b border-divider pb-2">
                  <span className="text-text-muted">{s.label}</span>
                  <span className="tabular font-bold text-text">{s.value ?? '—'}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

export function ScoutScreen() {
  const state = useFetch(fetchScoutPayload, [])
  const [query, setQuery] = useState('')
  const [position, setPosition] = useState<(typeof POSITIONS)[number]>('ALL')
  const [sortKey, setSortKey] = useState<SortKey>('total_points')
  const [maxPrice, setMaxPrice] = useState(PRICE_CEIL)
  const [mineOnly, setMineOnly] = useState(false)
  const [selected, setSelected] = useState<ScoutPlayerRow | null>(null)

  const rows = state.status === 'ready' ? state.data.players : []
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows
      .filter((r) => position === 'ALL' || r.position === position)
      .filter((r) => r.price_m === null || r.price_m <= maxPrice)
      .filter((r) => !mineOnly || r.is_mine)
      .filter((r) => !q || r.name.toLowerCase().includes(q) || r.team_short.toLowerCase().includes(q))
      .sort((a, b) => (b[sortKey] ?? -Infinity) - (a[sortKey] ?? -Infinity))
  }, [rows, query, position, sortKey, maxPrice, mineOnly])

  if (state.status === 'loading') {
    return (
      <div className="space-y-3 p-10">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }
  if (state.status === 'error') {
    return <div className="bg-alert-red p-6 font-semibold text-alert-red-ink">Can't reach the backend ({state.error.message}).</div>
  }

  const opp = state.status === 'ready' ? state.data.opportunities : null
  const oppCategories: { label: string; rows: OpportunityRow[] }[] = opp
    ? [
        { label: 'Breakout', rows: opp.breakout },
        { label: 'Role change', rows: opp.role_change },
        { label: 'Value', rows: opp.value },
        { label: 'Trap', rows: opp.trap },
      ].filter((c) => c.rows.length > 0)
    : []

  return (
    <div className="pb-16">
      <Masthead edition="Market Desk" title="Player Market" right={<>{filtered.length} of {rows.length} players</>} />

      {/* MARKET OVERVIEW - real category counts as boards, not prose */}
      {opp && (
        <div className="atmosphere-blue relative flex flex-wrap divide-x-2 divide-divider overflow-hidden border-b-2 border-divider">
          <span className="ghost-watermark pointer-events-none absolute -top-8 right-2 select-none font-display text-[9rem] font-bold uppercase leading-none">
            MARKET
          </span>
          {[
            { label: 'Value', n: opp.value.length },
            { label: 'Breakout', n: opp.breakout.length },
            { label: 'Trap', n: opp.trap.length },
            { label: 'Role change', n: opp.role_change.length },
            { label: 'Fixture swing', n: opp.fixture_swing.length },
          ].map((m) => (
            <div key={m.label} className="min-w-[140px] flex-1 px-8 py-5">
              <div className="tabular font-display text-3xl font-bold text-text">{m.n}</div>
              <div className="text-[11px] font-bold uppercase tracking-wide text-text-faint">{m.label}</div>
            </div>
          ))}
        </div>
      )}

      {opp && (oppCategories.length > 0 || opp.fixture_swing.length > 0) && (
        <div className="mt-6 grid grid-cols-1 gap-8 border-b-2 border-divider px-10 pb-8 lg:grid-cols-2">
          {oppCategories.map((c) => (
            <div key={c.label}>
              <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">{c.label}</div>
              {c.rows.map((r, i) => <OpportunityRowView key={i} r={r} />)}
            </div>
          ))}
          {opp.fixture_swing.length > 0 && (
            <div>
              <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Fixture swing</div>
              {opp.fixture_swing.map((s, i) => {
                const crest = crestUrl(s.team_code)
                return (
                  <div key={i} className="flex items-center gap-3 border-b-2 border-divider py-2.5 text-sm last:border-b-0">
                    {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
                    <span className="font-bold text-text">{s.team_short}</span>
                    <span className="tabular text-text-muted">{s.avg_difficulty.toFixed(1)} avg difficulty</span>
                    <span className="ml-auto text-text-faint">{s.label}</span>
                  </div>
                )
              })}
            </div>
          )}
          {(opp.transfers_in.length > 0 || opp.transfers_out.length > 0) && (
            <div className="grid grid-cols-2 gap-6">
              {opp.transfers_in.length > 0 && (
                <div>
                  <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Transfers in</div>
                  {opp.transfers_in.map((t, i) => {
                    const crest = crestUrl(t.team_code)
                    return (
                      <div key={i} className="flex items-center gap-2 border-b-2 border-divider py-2 text-sm last:border-b-0">
                        {crest && <img src={crest} alt="" className="h-3.5 w-3.5 rounded-full" />}
                        <span className="font-bold text-text">{t.name}</span>
                        <span className="tabular ml-auto font-semibold text-pitch-green">+{t.count.toLocaleString()}</span>
                      </div>
                    )
                  })}
                </div>
              )}
              {opp.transfers_out.length > 0 && (
                <div>
                  <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Transfers out</div>
                  {opp.transfers_out.map((t, i) => {
                    const crest = crestUrl(t.team_code)
                    return (
                      <div key={i} className="flex items-center gap-2 border-b-2 border-divider py-2 text-sm last:border-b-0">
                        {crest && <img src={crest} alt="" className="h-3.5 w-3.5 rounded-full" />}
                        <span className="font-bold text-text">{t.name}</span>
                        <span className="tabular ml-auto font-semibold text-alert-red">-{t.count.toLocaleString()}</span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3 px-10">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search players or teams..."
          className="min-w-64 bg-raised px-3 py-2 text-sm text-text placeholder:text-text-faint focus:outline-none focus:ring-1 focus:ring-pitch-green"
        />
        <div className="flex gap-px bg-divider">
          {POSITIONS.map((pos) => (
            <button
              key={pos}
              onClick={() => setPosition(pos)}
              className={`px-3 py-2 text-xs font-bold uppercase ${pos === position ? 'bg-pitch-green text-pitch-green-ink' : 'bg-raised text-text-muted hover:text-text'}`}
            >
              {pos}
            </button>
          ))}
        </div>
        <div className="flex gap-px bg-divider">
          {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => (
            <button
              key={k}
              onClick={() => setSortKey(k)}
              className={`px-3 py-2 text-xs font-bold uppercase ${k === sortKey ? 'bg-broadcast-blue text-broadcast-blue-ink' : 'bg-raised text-text-muted hover:text-text'}`}
            >
              Sort: {SORT_LABEL[k]}
            </button>
          ))}
        </div>
        <button
          onClick={() => setMineOnly((v) => !v)}
          className={`px-3 py-2 text-xs font-bold uppercase ${mineOnly ? 'bg-pitch-green text-pitch-green-ink' : 'bg-raised text-text-muted hover:text-text'}`}
        >
          My Squad
        </button>
        <label className="flex items-center gap-2 bg-raised px-3 py-2 text-xs font-bold uppercase text-text-muted">
          Max price
          <input
            type="range"
            min={PRICE_FLOOR}
            max={PRICE_CEIL}
            step={0.1}
            value={maxPrice}
            onChange={(e) => setMaxPrice(Number(e.target.value))}
            className="accent-pitch-green"
          />
          <span className="tabular text-text">£{maxPrice.toFixed(1)}m</span>
        </label>
      </div>

      <div className="mt-6 px-10">
        <div className="max-h-[70vh] overflow-y-auto border-2 border-divider bg-panel px-4 shadow-[0_24px_48px_-24px_rgba(0,0,0,0.9)]">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-panel">
              <tr className="border-b-2 border-divider text-[11px] uppercase tracking-wide text-text-faint">
                <th className="py-2 pr-4">Player</th>
                <th className="py-2 pr-4">Pos</th>
                <th className="tabular py-2 pr-4">Price</th>
                <th className="tabular py-2 pr-4">Owned</th>
                <th className="tabular py-2 pr-4">Pts</th>
                <th className="tabular py-2 pr-4">Form</th>
                <th className="tabular py-2 pr-4">xGI</th>
                <th className="tabular py-2 pr-4">G</th>
                <th className="tabular py-2 pr-4">A</th>
                <th className="tabular py-2 pr-4">Min</th>
                <th className="tabular py-2 pr-4">Bonus</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r: ScoutPlayerRow) => {
                const crest = crestUrl(r.team_code)
                return (
                  <tr
                    key={r.player_id}
                    onClick={() => setSelected(r)}
                    className={`cursor-pointer border-b-2 border-divider hover:bg-panel ${r.is_mine ? 'bg-raised' : ''}`}
                  >
                    <td className="py-2 pr-4">
                      <span className="flex items-center gap-2 font-bold text-text">
                        {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
                        {r.name}
                        <span className="font-normal text-text-faint">{r.team_short}</span>
                        {r.is_mine && <span className="bg-broadcast-gold px-1 py-0.5 text-[9px] font-bold text-broadcast-gold-ink">MINE</span>}
                      </span>
                    </td>
                    <td className="py-2 pr-4">
                      <span className="bg-raised px-1.5 py-0.5 text-[10px] font-bold text-text-muted">{r.position}</span>
                    </td>
                    <td className="tabular py-2 pr-4 text-text-muted">{r.price_m !== null ? `£${r.price_m.toFixed(1)}m` : '—'}</td>
                    <td className="tabular py-2 pr-4 text-text-muted">{r.owned_pct !== null ? `${r.owned_pct.toFixed(1)}%` : '—'}</td>
                    <td className="tabular py-2 pr-4 font-semibold text-text">{r.total_points ?? '—'}</td>
                    <td className="tabular py-2 pr-4 text-text-muted">{r.form ?? '—'}</td>
                    <td className="tabular py-2 pr-4 text-text-muted">{r.xgi ?? '—'}</td>
                    <td className="tabular py-2 pr-4 text-text-muted">{r.goals ?? '—'}</td>
                    <td className="tabular py-2 pr-4 text-text-muted">{r.assists ?? '—'}</td>
                    <td className="tabular py-2 pr-4 text-text-muted">{r.minutes ?? '—'}</td>
                    <td className="tabular py-2 pr-4 text-text-muted">{r.bonus ?? '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* PRICE MOVES - real rise/fall forecast + confirmed change ledger */}
      {state.status === 'ready' && (state.data.price_moves.forecast.length > 0 || state.data.price_moves.ledger.length > 0) && (
        <div className="mt-10 border-t-2 border-divider px-10 pt-8">
          <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Price moves</div>
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
            {state.data.price_moves.forecast.length > 0 && (
              <div>
                <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-text-faint">Forecast (uncalibrated momentum heuristic)</div>
                <div className="divide-y divide-divider border-2 border-divider bg-panel px-4 shadow-[0_24px_48px_-24px_rgba(0,0,0,0.9)]">
                  {state.data.price_moves.forecast.slice(0, 12).map((r) => {
                    const crest = crestUrl(r.team_code)
                    const rising = r.direction === 'RISE_LIKELY'
                    return (
                      <div key={r.player_id} className="flex items-center gap-3 py-2.5 text-sm">
                        {crest && <img src={crest} alt="" className="h-4 w-4 shrink-0 rounded-full" />}
                        <span className="font-bold text-text">{r.name}</span>
                        <span className="text-xs text-text-faint">{r.team_short}</span>
                        {r.price_m !== null && <span className="tabular text-text-muted">£{r.price_m.toFixed(1)}m</span>}
                        <span className="relative ml-auto h-2 w-16 shrink-0 border border-divider bg-void">
                          <span className={`absolute inset-y-0 left-0 ${rising ? 'bg-pitch-green' : 'bg-alert-red'}`} style={{ width: `${r.progress_pct}%` }} />
                        </span>
                        <span className={`w-16 shrink-0 text-right text-xs font-bold uppercase ${rising ? 'text-pitch-green' : 'text-alert-red'}`}>
                          {rising ? '▲ rise' : '▼ fall'}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            {state.data.price_moves.ledger.length > 0 && (
              <div>
                <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-text-faint">Confirmed changes</div>
                <div className="divide-y divide-divider border-2 border-divider bg-panel px-4 shadow-[0_24px_48px_-24px_rgba(0,0,0,0.9)]">
                  {state.data.price_moves.ledger.map((r) => {
                    const crest = crestUrl(r.team_code)
                    const up = r.new_price_m > r.old_price_m
                    return (
                      <div key={`${r.player_id}-${r.valid_from}`} className="flex items-center gap-3 py-2.5 text-sm">
                        {crest && <img src={crest} alt="" className="h-4 w-4 shrink-0 rounded-full" />}
                        <span className="font-bold text-text">{r.name}</span>
                        <span className="text-xs text-text-faint">{r.team_short}</span>
                        <span className="tabular ml-auto text-text-muted">
                          £{r.old_price_m.toFixed(1)}m &rarr; £{r.new_price_m.toFixed(1)}m
                        </span>
                        <span className={`tabular w-14 shrink-0 text-right text-xs font-bold ${up ? 'text-pitch-green' : 'text-alert-red'}`}>
                          {up ? '+' : ''}{(r.new_price_m - r.old_price_m).toFixed(1)}m
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <PlayerDetailSheet player={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
