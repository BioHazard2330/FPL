import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Disclosure } from '@/components/ui/kit'
import { crestUrl, fetchScoutPayload, shirtUrl } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { Skel, SkelMasthead, SkelTable, ScreenError } from '@/components/shell/ScreenStates'
import { FixtureRun, RunPressure } from '@/components/football/FixtureRun'
import type { ExpectedDataRow, FixtureContext, OpportunityRow, ScoutPlayerRow, TemplateTeamBlock } from '@/lib/types'

const POSITIONS = ['ALL', 'GKP', 'DEF', 'MID', 'FWD'] as const
type SortKey = 'total_points' | 'price_m' | 'owned_pct' | 'form' | 'xgi'
const SORT_LABEL: Record<SortKey, string> = { total_points: 'Pts', price_m: 'Price', owned_pct: 'Owned', form: 'Form', xgi: 'xGI' }

const PRICE_FLOOR = 3.5
const PRICE_CEIL = 16.0

const POSITION_ROW_LABEL: Record<string, string> = { GKP: 'GK', DEF: 'DEF', MID: 'MID', FWD: 'FWD' }

const OPP_KIND: Record<string, { ink: string; bar: string; blurb: string }> = {
  Breakout: { ink: 'text-pitch-green', bar: 'bg-pitch-green', blurb: 'cheap, owned by few, projecting well' },
  Value: { ink: 'text-[#8fb0ff]', bar: 'bg-broadcast-blue', blurb: 'points per pound' },
  Trap: { ink: 'text-alert-red', bar: 'bg-alert-red', blurb: 'owned widely, likely to disappoint' },
  'Role change': { ink: 'text-broadcast-gold', bar: 'bg-broadcast-gold', blurb: 'a new job on the pitch' },
}

const CONFIDENCE_WORD: Record<string, string> = { HIGH: 'strong evidence', MEDIUM: 'some evidence', LOW: 'thin evidence' }

/** One market board row: who, what he costs, what he projects, and the one reason he is on the board. Trap rows carry
 * a red wash because the risk is the point; the evidence strength is a word, not a shouted label. */
function OpportunityRowView({ r, kind }: { r: OpportunityRow; kind: string }) {
  const crest = crestUrl(r.team_code)
  const isTrap = kind === 'Trap'
  const reason = isTrap ? r.risk ?? r.why_now : r.why_now
  return (
    <div className={`grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-center gap-x-3 rounded-md px-3 py-2.5 ${isTrap ? 'bg-alert-red/[0.07]' : 'hover:bg-raised/50'}`}>
      {crest ? <img src={crest} alt="" className="size-5" /> : <span />}
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-[15px] font-semibold text-text">{r.name}</span>
          <span className="text-[12px] text-text-faint">
            {r.position}
            {r.price_m !== null && <> · £{r.price_m.toFixed(1)}m</>}
          </span>
        </div>
        <div className="truncate text-[12.5px] text-text-muted" title={[reason, !isTrap ? r.risk : null].filter(Boolean).join(' · ')}>
          {reason}
          {!isTrap && r.risk && <span className="text-text-faint"> · {r.risk}</span>}
          <span className="text-text-faint"> · {CONFIDENCE_WORD[r.confidence] ?? r.confidence.toLowerCase()}</span>
        </div>
      </div>
      {r.xp !== null && (
        <div className="text-right">
          <div className={`font-display text-2xl font-bold leading-none tabular ${isTrap ? 'text-alert-red' : 'text-text'}`}>{r.xp.toFixed(1)}</div>
          <div className="text-[10.5px] uppercase tracking-wider text-text-faint">xP</div>
        </div>
      )}
    </div>
  )
}

/** THE SCOUTING WORKSTATION DETAIL PANEL - a real persistent pane, not a
 * slide-out drawer that covers the table it came from. The classic
 * workstation pattern (list left, detail always visible right) - clicking
 * a row updates this panel in place, the table never gets obscured.
 * Same real fields as before, just never hidden behind an open/close
 * interaction. */
function PlayerDetailPanel({ player, fixtures }: { player: ScoutPlayerRow | null; fixtures?: FixtureContext }) {
  const run = player?.team_code != null ? fixtures?.[String(player.team_code)] : undefined
  const shirt = player ? shirtUrl(player.team_code, player.position === 'GKP', 260) : null
  const crest = player ? crestUrl(player.team_code) : null
  const stats: { label: string; value: string | number | null }[] = player
    ? [
        { label: 'Total points', value: player.total_points },
        { label: 'Form', value: player.form },
        { label: 'xGI', value: player.xgi },
        { label: 'Minutes', value: player.minutes },
        { label: 'Goals', value: player.goals },
        { label: 'Assists', value: player.assists },
        { label: 'Bonus', value: player.bonus },
        { label: 'Ownership', value: player.owned_pct !== null ? `${player.owned_pct.toFixed(1)}%` : null },
      ]
    : []

  if (!player) {
    return (
      <div className="sticky top-4 flex h-[70vh] w-80 shrink-0 flex-col items-center justify-center border-2 border-dashed border-divider text-center">
        <div className="text-[13px] font-bold text-text-faint">Scouting bench</div>
        <p className="mt-2 max-w-[16rem] text-sm text-text-muted">Select a player from the table to pull up their real scouting profile here.</p>
      </div>
    )
  }

  return (
    <div className="sticky top-4 w-80 shrink-0 border-2 border-divider bg-void">
      <div className="relative overflow-hidden border-b border-divider px-6 pb-6 pt-8">
        {shirt && (
          <img src={shirt} alt="" className="pointer-events-none absolute -right-6 -top-4 h-40 w-40 object-contain opacity-90" />
        )}
        <div className="relative max-w-[65%] font-display text-3xl font-bold leading-[0.95] text-text">{player.name}</div>
        <div className="relative mt-2 flex items-center gap-1.5 text-sm text-text-muted">
          {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
          {player.team_short} &middot; {player.position} &middot; {player.price_m !== null ? `£${player.price_m.toFixed(1)}m` : '—'}
        </div>
      </div>
      {run && run.length > 0 && (
        <div className="border-b border-divider px-6 py-3">
          <div className="mb-1.5 text-[12px] font-bold text-text-faint">Next five</div>
          <div className="flex items-center justify-between gap-3">
            <FixtureRun fixtures={run} max={5} showEvent />
            <RunPressure fixtures={run} max={5} />
          </div>
        </div>
      )}
      <div className="grid grid-cols-3 gap-px bg-divider">
        {stats.map((s) => (
          <div key={s.label} className="bg-panel px-3 py-3">
            <div className="text-[12px] font-bold text-text-faint">{s.label}</div>
            <div className="tabular mt-0.5 text-lg font-bold text-text">{s.value ?? '—'}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Real TEMPLATE TEAM panel (art-direction pass v3, direct user follow-up:
 * "more football" - closes a real, previously-disclosed gap). A per-
 * position highest-owned pool as real shirts on a quiet turf strip, not a
 * formation-constrained "best XI" (this project has never computed one -
 * see the backend's own docstring for why presenting one would overstate
 * what this data supports). Overlap/differential facts read straight off
 * the real payload, never re-derived client-side. */
function TemplateTeamBoard({ block }: { block: TemplateTeamBlock }) {
  if (block.positions.length === 0) return null
  return (
    <div className="border-b border-divider px-10 py-8">
      <div className="mb-1 text-[13px] font-bold text-text-faint">Template team</div>
      <div className="mb-5 text-xs text-text-faint">Highest real-owned pool per position - not a formation, a market read.</div>
      <div className="pitch-surface flex flex-col gap-6 px-6 py-8">
        {block.positions.map((pos) => (
          <div key={pos.position} className="relative flex items-start gap-4">
            <span className="w-9 shrink-0 pt-4 text-right text-[12px] font-bold text-text-faint">
              {POSITION_ROW_LABEL[pos.position] ?? pos.position}
            </span>
            <div className="flex flex-1 flex-wrap items-start justify-center gap-6">
            {pos.players.map((tp) => {
              const shirt = shirtUrl(tp.team_code, pos.position === 'GKP')
              const crest = crestUrl(tp.team_code)
              return (
                <div key={tp.player_id} className="relative flex w-24 flex-col items-center text-center">
                  {tp.is_mine && (
                    <span className="absolute right-1 top-0 flex h-4 w-4 items-center justify-center bg-broadcast-gold text-[12px] font-bold text-broadcast-gold-ink">M</span>
                  )}
                  <div className="relative h-14 w-14">
                    {shirt ? <img src={shirt} alt="" className="h-14 w-14 object-contain" /> : <div className="h-14 w-14 bg-raised" />}
                    {crest && <img src={crest} alt="" className="absolute -bottom-0.5 -right-0.5 h-4 w-4 rounded-full bg-void ring-2 ring-void" />}
                  </div>
                  <div className="mt-1 w-full truncate text-xs font-bold text-text">{tp.name}</div>
                  <div className="tabular text-sm font-bold text-pitch-green">
                    {tp.eo_percent !== null ? `${tp.eo_percent.toFixed(1)}%` : `${tp.ownership_pct.toFixed(1)}%`}
                  </div>
                  {tp.margin_of_error_pp !== null && (
                    <div className="text-[12px] text-text-faint">&plusmn;{tp.margin_of_error_pp.toFixed(1)}pp</div>
                  )}
                </div>
              )
            })}
            </div>
          </div>
        ))}
      </div>
      {block.overlap && (
        <div className="mt-5 flex flex-wrap gap-x-8 gap-y-2 text-sm">
          <span className="text-text-muted">
            <span className="tabular font-bold text-text">{block.overlap.overlap_count}/{block.overlap.squad_size}</span> of your squad in this pool
          </span>
          {block.overlap.differential_name && (
            <span className="text-text-muted">
              Biggest differential: <span className="font-bold text-broadcast-gold">{block.overlap.differential_name}</span>{' '}
              <span className="tabular">({block.overlap.differential_pct?.toFixed(1)}% owned)</span>
            </span>
          )}
          {block.overlap.missing_top3.length > 0 && (
            <span className="text-text-muted">
              You don't have: <span className="text-text">{block.overlap.missing_top3.map((m) => m.name).join(', ')}</span>
            </span>
          )}
        </div>
      )}
    </div>
  )
}

/** Real xGI-per-90 leaderboard (art-direction pass v3, direct user follow-up:
 * "more football" - a genuinely non-redundant scouting signal the main
 * table can't show: a high-RATE player under-ranked by raw totals because
 * of fewer minutes played, real Understat data). */
function ExpectedDataLeaderboard({ rows }: { rows: ExpectedDataRow[] }) {
  if (rows.length === 0) return null
  return (
    <div className="border-b border-divider px-10 py-8">
      <div className="mb-1 text-[13px] font-bold text-text-faint">Expected data</div>
      <div className="mb-4 text-xs text-text-faint">Real current-season xG/xA, ranked by per-90 rate - not raw totals.</div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-divider text-[13px] text-text-faint">
              <th className="py-2 pr-4">Player</th>
              <th className="tabular py-2 pr-4">xG</th>
              <th className="tabular py-2 pr-4">xA</th>
              <th className="tabular py-2 pr-4">xGI</th>
              <th className="tabular py-2 pr-4 text-pitch-green">xG/90</th>
              <th className="tabular py-2 pr-4 text-pitch-green">xA/90</th>
              <th className="tabular py-2 pr-4 text-pitch-green">xGI/90</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const crest = crestUrl(r.team_code)
              return (
                <tr key={r.player_id} className={`border-b border-divider ${r.is_mine ? 'bg-raised' : ''}`}>
                  <td className="py-2 pr-4">
                    <span className="flex items-center gap-2 font-bold text-text">
                      {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
                      <Link to={`/player/${r.player_id}`} className="hover:text-pitch-green">{r.name}</Link>
                      <span className="font-normal text-text-faint">{r.team_short}</span>
                    </span>
                  </td>
                  <td className="tabular py-2 pr-4 text-text-muted">{r.xg.toFixed(1)}</td>
                  <td className="tabular py-2 pr-4 text-text-muted">{r.xa.toFixed(1)}</td>
                  <td className="tabular py-2 pr-4 font-semibold text-text">{r.xgi.toFixed(1)}</td>
                  <td className="tabular py-2 pr-4 font-bold text-pitch-green">{r.xg_per90.toFixed(2)}</td>
                  <td className="tabular py-2 pr-4 font-bold text-pitch-green">{r.xa_per90.toFixed(2)}</td>
                  <td className="tabular py-2 pr-4 font-bold text-pitch-green">{r.xgi_per90.toFixed(2)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function ScoutScreen() {
  const state = useFetch(fetchScoutPayload, [], 60000)
  const [query, setQuery] = useState('')
  const [position, setPosition] = useState<(typeof POSITIONS)[number]>('ALL')
  const [sortKey, setSortKey] = useState<SortKey>('total_points')
  const [maxPrice, setMaxPrice] = useState(PRICE_CEIL)
  const [mineOnly, setMineOnly] = useState(false)
  // Real id, not the fetched row object itself (2026-09-08, direct user
  // finding: "I don't want that lag" led to adding real polling to
  // `useFetch` - a stored object reference would freeze the detail panel
  // on stale data forever once a poll refresh replaces `rows` with new
  // objects). Re-looked-up from the current `rows` on every render, so the
  // panel always reflects whatever the last real poll actually returned.
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const rows = state.status === 'ready' ? state.data.players : []
  const selected = selectedId !== null ? (rows.find((r) => r.player_id === selectedId) ?? null) : null
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
    // Shaped like the workstation it precedes: header band, then the
    // table beside its persistent detail panel.
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="border-b border-divider px-10 py-8">
          <Skel className="h-2 w-32" />
          <Skel className="mt-3 h-10 w-72" />
        </div>
        <div className="flex gap-6 px-8 pb-6 pt-4">
          <div className="min-w-0 flex-1">
            <SkelTable rows={12} cols={8} />
          </div>
          <Skel className="h-[70vh] w-80 shrink-0" />
        </div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Scouting data unavailable"
        description="The scout payload could not be fetched. No ownership, expected-output or differential data is being shown, and none is being estimated in its place."
        message={state.error.message}
      />
    )
  }

  const opp = state.status === 'ready' ? state.data.opportunities : null
  const fixtures = state.status === 'ready' ? state.data.fixtures : undefined
  const oppCategories: { label: string; rows: OpportunityRow[] }[] = opp
    ? [
        { label: 'Breakout', rows: opp.breakout },
        { label: 'Role change', rows: opp.role_change },
        { label: 'Value', rows: opp.value },
        { label: 'Trap', rows: opp.trap },
      ].filter((c) => c.rows.length > 0)
    : []

  return (
    <div className="data-in pb-16">
      <Masthead right={<>{filtered.length} of {rows.length} players</>} />

      {opp && (oppCategories.length > 0 || opp.fixture_swing.length > 0) && (
        <div className="grid grid-cols-1 gap-x-10 gap-y-8 px-8 py-6 lg:grid-cols-2">
          {oppCategories.map((c) => (
            <div key={c.label}>
              <div className="mb-3 flex items-baseline gap-3">
                <span className={`h-4 w-[7px] self-center ${OPP_KIND[c.label]?.bar ?? 'bg-text-faint'} [clip-path:polygon(35%_0,100%_0,65%_100%,0_100%)]`} />
                <span className={`font-display text-lg font-semibold uppercase tracking-[0.05em] ${OPP_KIND[c.label]?.ink ?? 'text-text'}`}>{c.label}</span>
                <span className="text-[12.5px] text-text-faint">{OPP_KIND[c.label]?.blurb}</span>
              </div>
              <div className="space-y-1">
                {c.rows.map((r, i) => <OpportunityRowView key={i} r={r} kind={c.label} />)}
              </div>
            </div>
          ))}
          {opp.fixture_swing.length > 0 && (
            <div>
              <div className="mb-2 text-[13px] font-bold text-text-faint">Fixture swing</div>
              {opp.fixture_swing.map((s, i) => {
                const crest = crestUrl(s.team_code)
                return (
                  <div key={i} className="flex items-center gap-3 border-b border-divider py-2.5 text-sm last:border-b-0">
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
                  <div className="mb-2 text-[13px] font-bold text-text-faint">Transfers in</div>
                  {opp.transfers_in.map((t, i) => {
                    const crest = crestUrl(t.team_code)
                    return (
                      <div key={i} className="flex items-center gap-2 border-b border-divider py-2 text-sm last:border-b-0">
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
                  <div className="mb-2 text-[13px] font-bold text-text-faint">Transfers out</div>
                  {opp.transfers_out.map((t, i) => {
                    const crest = crestUrl(t.team_code)
                    return (
                      <div key={i} className="flex items-center gap-2 border-b border-divider py-2 text-sm last:border-b-0">
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

      {state.status === 'ready' && (
        <Disclosure title="The most-owned team" summary="The highest-owned player in each slot, and how much of your squad it covers">
          <TemplateTeamBoard block={state.data.template_team} />
        </Disclosure>
      )}
      {state.status === 'ready' && (
        <Disclosure title="Underlying numbers" summary="Season xG and xA per 90, the chances behind the points">
          <ExpectedDataLeaderboard rows={state.data.expected_data} />
        </Disclosure>
      )}

      <div className="flex flex-wrap items-center gap-3 px-8 pt-6">
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
              className={`px-3 py-2 text-xs font-bold ${pos === position ? 'bg-pitch-green text-pitch-green-ink' : 'bg-raised text-text-muted hover:text-text'}`}
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
              className={`px-3 py-2 text-xs font-bold ${k === sortKey ? 'bg-broadcast-blue text-broadcast-blue-ink' : 'bg-raised text-text-muted hover:text-text'}`}
            >
              Sort: {SORT_LABEL[k]}
            </button>
          ))}
        </div>
        <button
          onClick={() => setMineOnly((v) => !v)}
          className={`px-3 py-2 text-xs font-bold ${mineOnly ? 'bg-pitch-green text-pitch-green-ink' : 'bg-raised text-text-muted hover:text-text'}`}
        >
          Mine only
        </button>
        <label className="flex items-center gap-2 bg-raised px-3 py-2 text-xs font-bold text-text-muted">
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

      {/* THE WORKSTATION - table + a real persistent detail pane, not a
          drawer that slides over the table it came from. */}
      <div className="flex gap-6 px-8 pb-6 pt-4">
        <div className="min-w-0 flex-1 overflow-x-auto">
          <div className="max-h-[70vh] overflow-y-auto border-t border-divider">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-panel">
                <tr className="border-b border-divider text-[13px] text-text-faint">
                  <th className="py-2 pr-4">Player</th>
                  <th className="py-2 pr-4">Pos</th>
                  <th className="py-2 pr-4">Next 3</th>
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
                  const active = selected?.player_id === r.player_id
                  return (
                    <tr
                      key={r.player_id}
                      onClick={() => setSelectedId(r.player_id)}
                      className={`cursor-pointer border-b border-divider hover:bg-raised ${active ? 'bg-raised' : r.is_mine ? 'bg-panel' : ''}`}
                    >
                      <td className={`py-2 pr-4 ${active ? 'border-l border-pitch-green' : ''}`}>
                        <span className="flex items-center gap-2 font-bold text-text">
                          {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
                          <Link
                            to={`/player/${r.player_id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="hover:text-pitch-green"
                          >
                            {r.name}
                          </Link>
                          <span className="font-normal text-text-faint">{r.team_short}</span>
                          {r.is_mine && <span className="rounded bg-broadcast-gold/20 px-1.5 py-0.5 text-[12px] font-semibold text-broadcast-gold">yours</span>}
                        </span>
                      </td>
                      <td className="py-2 pr-4">
                        <span className="bg-raised px-1.5 py-0.5 text-[12px] font-bold text-text-muted">{r.position}</span>
                      </td>
                      <td className="py-2 pr-4">
                        <FixtureRun fixtures={r.team_code !== null ? fixtures?.[String(r.team_code)] : undefined} max={3} />
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
        {selected && <PlayerDetailPanel player={selected} fixtures={fixtures} />}
      </div>

      {/* PRICE MOVES - real rise/fall forecast + confirmed change ledger */}
      {state.status === 'ready' && (state.data.price_moves.forecast.length > 0 || state.data.price_moves.ledger.length > 0) && (
        <div className="px-8 py-6">
          <h2 className="mb-4 font-display text-xl font-semibold text-text">Price changes</h2>
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
            {state.data.price_moves.forecast.length > 0 && (
              <div>
                <div className="mb-2 text-[12px] font-bold text-text-faint">{state.data.price_moves.forecast.some((r) => r.calibrated) ? 'Likely tonight, from the fitted price model' : 'Likely tonight (rough momentum guess)'}</div>
                <div className="divide-y divide-divider border-t border-divider">
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
                        <span className={`w-20 shrink-0 text-right text-xs font-bold ${rising ? 'text-pitch-green' : 'text-alert-red'}`}>
                          {rising ? '▲ rise' : '▼ fall'}{r.probability != null ? ` ${Math.round(r.probability * 100)}%` : ''}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            {state.data.price_moves.ledger.length > 0 && (
              <div>
                <div className="mb-2 text-[12px] font-bold text-text-faint">Confirmed changes</div>
                <div className="divide-y divide-divider border-t border-divider">
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

    </div>
  )
}
