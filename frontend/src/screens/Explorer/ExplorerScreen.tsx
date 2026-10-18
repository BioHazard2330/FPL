import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchExplorerPayload } from '@/lib/api'
import { fdrFill } from '@/lib/fdr'
import { useFetch } from '@/lib/useFetch'
import type { ExplorerPlayer } from '@/lib/types'

/** EXPLORER - every player worth a look, in one table you can sort and filter.
 *
 * The figures are the model's own and the season line from the official feed;
 * nothing is folded into a score, so a column sorts on what it says it is.
 * Luck is the points a player is running above (gold) or below (blue) what his
 * chances imply, in standard errors, from the audit; it is a reading of the
 * past. Fixtures are the next three, coloured by FPL's own difficulty. */

type Key = 'xp_next' | 'xp_five' | 'xp_per_m' | 'price' | 'owned' | 'form' | 'minutes_share' | 'xgi_90' | 'luck_z' | 'points' | 'deserved_ppg'

const COLUMNS: { key: Key; label: string; title: string; fmt: (p: ExplorerPlayer) => string }[] = [
  { key: 'price', label: 'Price', title: 'Current price', fmt: (p) => (p.price === null ? '' : `£${p.price.toFixed(1)}`) },
  { key: 'owned', label: 'Own', title: 'Selected by, per cent', fmt: (p) => (p.owned === null ? '' : `${p.owned.toFixed(1)}%`) },
  { key: 'xp_next', label: 'xP', title: 'Expected points, next gameweek', fmt: (p) => p.xp_next.toFixed(1) },
  { key: 'xp_five', label: 'xP×5', title: 'Expected points over the next five gameweeks', fmt: (p) => p.xp_five.toFixed(1) },
  { key: 'xp_per_m', label: 'xP×5/£m', title: 'Five-gameweek expected points per million', fmt: (p) => (p.xp_per_m === null ? '' : p.xp_per_m.toFixed(2)) },
  { key: 'form', label: 'Form', title: 'FPL form', fmt: (p) => (p.form === null ? '' : p.form.toFixed(1)) },
  { key: 'points', label: 'Pts', title: 'Total points this season', fmt: (p) => (p.points === null ? '' : String(p.points)) },
  { key: 'minutes_share', label: 'Mins', title: 'Minutes played as a share of the minutes available', fmt: (p) => `${Math.round(p.minutes_share * 100)}%` },
  { key: 'xgi_90', label: 'xGI/90', title: 'Expected goals plus expected assists per 90 minutes', fmt: (p) => (p.xgi_90 === null ? '' : p.xgi_90.toFixed(2)) },
  { key: 'deserved_ppg', label: 'Und/GW', title: 'Points per appearance the chances behind them support: actual points less the luck from the audit', fmt: (p) => (p.deserved_ppg === null ? '' : p.deserved_ppg.toFixed(1)) },
  { key: 'luck_z', label: 'Luck', title: 'Points above (+) or below (−) what his chances imply, in standard errors', fmt: (p) => (p.luck_z === null ? '' : `${p.luck_z > 0 ? '+' : ''}${p.luck_z.toFixed(1)}`) },
]

const POSITIONS = ['ALL', 'GKP', 'DEF', 'MID', 'FWD'] as const
const PAGE = 80

function statusChip(p: ExplorerPlayer) {
  if (p.status === 'a') return null
  const label = p.status === 'd' ? (p.chance !== null ? `${p.chance}%` : 'doubt') : p.status === 'i' ? 'injured' : p.status === 's' ? 'suspended' : 'out'
  return <span title={p.news ?? ''} className="rounded bg-broadcast-gold/15 px-1.5 text-[11px] font-semibold text-broadcast-gold">{label}</span>
}

export function ExplorerScreen() {
  const state = useFetch(fetchExplorerPayload, [], 600000)
  const [position, setPosition] = useState<(typeof POSITIONS)[number]>('ALL')
  const [team, setTeam] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [q, setQ] = useState('')
  const [availableOnly, setAvailableOnly] = useState(false)
  const [mineOnly, setMineOnly] = useState(false)
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: 'xp_five', dir: -1 })
  const [shown, setShown] = useState(PAGE)

  const rows = useMemo(() => (state.status === 'ready' ? state.data.players : []), [state])
  const teams = useMemo(() => [...new Set(rows.map((p) => p.team_short))].sort(), [rows])
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const cap = maxPrice ? Number(maxPrice) : null
    const list = rows.filter((p) =>
      (position === 'ALL' || p.position === position)
      && (!team || p.team_short === team)
      && (cap === null || Number.isNaN(cap) || (p.price !== null && p.price <= cap))
      && (!availableOnly || p.status === 'a' || (p.status === 'd' && (p.chance ?? 0) >= 75))
      && (!mineOnly || p.mine)
      && (!needle || p.name.toLowerCase().includes(needle) || p.full_name.toLowerCase().includes(needle)),
    )
    return list.sort((a, b) => {
      const av = a[sort.key], bv = b[sort.key]
      if (av === null && bv === null) return 0
      if (av === null) return 1
      if (bv === null) return -1
      return ((av as number) - (bv as number)) * sort.dir
    })
  }, [rows, position, team, maxPrice, q, availableOnly, mineOnly, sort])

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="px-10 py-8"><Skel className="h-[520px] w-full" /></div>
      </div>
    )
  }
  if (state.status === 'error') {
    return <ScreenError title="Explorer unavailable" description="The player table could not be built, so none of it is shown." message={state.error.message} />
  }

  const header = (c: (typeof COLUMNS)[number]) => {
    const active = sort.key === c.key
    return (
      <button
        key={c.key}
        type="button"
        title={c.title}
        onClick={() => { setSort((s) => (s.key === c.key ? { key: c.key, dir: s.dir === 1 ? -1 : 1 } : { key: c.key, dir: -1 })); setShown(PAGE) }}
        className={`text-right font-mono text-[12px] uppercase tracking-[0.04em] ${active ? 'text-text' : 'text-text-faint hover:text-text-muted'}`}
      >
        {c.label}{active ? (sort.dir === -1 ? ' ↓' : ' ↑') : ''}
      </button>
    )
  }
  const grid = 'explorer-grid'

  return (
    <div className="data-in pb-16">
      <Masthead
        edition="Explorer"
        title="Every player, sortable"
        right={<span className="text-text-muted">{filtered.length} of {rows.length} players · GW{state.data.event} onward</span>}
      />

      <section className="allow-overflow px-10 py-5">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex gap-1">
            {POSITIONS.map((p) => (
              <button key={p} type="button" onClick={() => { setPosition(p); setShown(PAGE) }} className={`rounded-md px-3 py-1.5 text-[13px] font-semibold ${position === p ? 'bg-text text-void' : 'bg-raised text-text-muted hover:text-text'}`}>
                {p === 'ALL' ? 'All' : p}
              </button>
            ))}
          </div>
          <select value={team} onChange={(e) => { setTeam(e.target.value); setShown(PAGE) }} className="rounded-md bg-raised px-3 py-1.5 text-[13px] text-text outline-none">
            <option value="">Every club</option>
            {teams.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <label className="flex items-center gap-2 text-[13px] text-text-muted">
            Up to £
            <input value={maxPrice} onChange={(e) => { setMaxPrice(e.target.value); setShown(PAGE) }} inputMode="decimal" placeholder="any" className="w-16 rounded-md bg-raised px-2 py-1.5 text-[13px] text-text outline-none placeholder:text-text-faint" />m
          </label>
          <input value={q} onChange={(e) => { setQ(e.target.value); setShown(PAGE) }} placeholder="Search a name" className="w-44 rounded-md bg-raised px-3 py-1.5 text-[13px] text-text outline-none placeholder:text-text-faint" />
          <label className="flex items-center gap-2 text-[13px] text-text-muted">
            <input type="checkbox" checked={availableOnly} onChange={(e) => setAvailableOnly(e.target.checked)} /> Likely to play
          </label>
          <label className="flex items-center gap-2 text-[13px] text-text-muted">
            <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} /> My squad
          </label>
        </div>
      </section>

      <section className="px-10 py-4">
        <div className="overflow-x-auto">
        <div className="min-w-[66rem]">
        <div className={`${grid} border-b border-divider pb-2`}>
          <span className="font-mono text-[12px] uppercase tracking-[0.04em] text-text-faint">Player</span>
          {COLUMNS.map(header)}
          <span className="font-mono text-[12px] uppercase tracking-[0.04em] text-text-faint">Next three</span>
        </div>
        {filtered.slice(0, shown).map((p) => (
          <div key={p.player_id} className={`${grid} border-b border-divider py-1.5 text-sm`}>
            <div className="flex min-w-0 items-center gap-2.5">
              <PlayerPhoto code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} className="h-9 w-7 shrink-0" />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Link to={`/player/${p.player_id}`} className="truncate font-bold text-text hover:text-pitch-green">{p.name}</Link>
                  {p.mine && <span className="rounded bg-pitch-green px-1 text-[11px] font-bold uppercase leading-4 text-pitch-green-ink">yours</span>}
                  {statusChip(p)}
                </div>
                <div className="font-mono text-[12px] uppercase text-text-faint">{p.team_short} · {p.position}</div>
              </div>
            </div>
            {COLUMNS.map((c) => {
              const text = c.fmt(p)
              const tone =
                c.key === 'luck_z' && p.luck_z !== null
                  ? p.luck_z >= 1.5 ? 'text-broadcast-gold' : p.luck_z <= -1.5 ? 'text-broadcast-blue' : 'text-text-muted'
                  : c.key === 'xp_five' || c.key === 'xp_next' ? 'font-bold text-pitch-green' : 'text-text'
              return <span key={c.key} className={`tabular text-right ${tone}`}>{text || '–'}</span>
            })}
            <div className="flex gap-1">
              {p.fixtures.map((f, i) => (
                <span key={i} className={`rounded px-1 py-0.5 font-mono text-[11px] font-bold leading-4 ${fdrFill(f.difficulty)}`} title={`${f.home ? 'home' : 'away'} to ${f.opponent}`}>
                  {f.opponent}{f.home ? '' : '*'}
                </span>
              ))}
            </div>
          </div>
        ))}
        </div>
        </div>
        {filtered.length === 0 && <p className="py-8 text-sm text-text-muted">No player matches those filters.</p>}
        {filtered.length > shown && (
          <button type="button" onClick={() => setShown((n) => n + PAGE)} className="mt-4 rounded-md bg-raised px-4 py-2 text-[13px] font-semibold text-text-muted hover:text-text">
            Show {Math.min(PAGE, filtered.length - shown)} more
          </button>
        )}
        <p className="mt-6 max-w-3xl text-[13px] leading-relaxed text-text-faint">
          xP is the model&apos;s expected points; xP×5 is its total over the next five gameweeks, with the small rotation discount it applies to each extra fixture. Mins is minutes played over the minutes available to a club that has played every gameweek so far. A star after a fixture is an away match. Luck is not a forecast: a finisher who is really better than his chances stays above them.
        </p>
      </section>
    </div>
  )
}
