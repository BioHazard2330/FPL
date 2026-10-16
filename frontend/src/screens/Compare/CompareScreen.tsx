import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import { FixtureRun } from '@/components/football/FixtureRun'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { crestUrl, fetchComparePayload, fetchPlayersIndex, fetchWeekPlanPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { ComparePayload, ComparePlayer, PlayerIndexRow } from '@/lib/types'

/** COMPARE - two players on the numbers that decide a transfer.
 *
 * Every figure is the model's own or the season line from the official feed.
 * The page says which side each measure favours and by how much, and puts the
 * model's measured error next to the gap that matters: a point of difference
 * over five gameweeks is not a reason to move, and the page does not pretend
 * otherwise. The projection components are drawn as they are in the model, so
 * "why is he rated higher" has a visible answer: goals, assists, bonus, clean
 * sheets, appearance points. */

const COMPONENT_LABELS: [keyof NonNullable<ComparePlayer['components']>, string][] = [
  ['appearance', 'Appearance'], ['goals', 'Goals'], ['assists', 'Assists'], ['bonus', 'Bonus'],
  ['clean_sheet', 'Clean sheet'], ['conceded', 'Goals conceded'], ['cards', 'Cards'], ['defcon', 'Defensive actions'],
]

function Picker({ label, selected, index, onPick, exclude }: {
  label: string
  selected: PlayerIndexRow | null
  index: PlayerIndexRow[]
  onPick: (id: number | null) => void
  exclude?: number | null
}) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const hits = useMemo(() => {
    const n = q.trim().toLowerCase()
    if (!n) return []
    return index
      .filter((p) => p.player_id !== exclude && (p.name.toLowerCase().includes(n) || p.full_name.toLowerCase().includes(n) || p.team_short.toLowerCase() === n))
      .slice(0, 8)
  }, [q, index, exclude])
  return (
    <div className="relative">
      <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">{label}</div>
      {selected && !open ? (
        <button type="button" onClick={() => { setOpen(true); setQ('') }} className="flex w-full items-center gap-2 bg-raised px-3 py-2 text-left">
          <span className="font-bold text-text">{selected.name}</span>
          <span className="text-xs text-text-muted">{selected.team_short} · {selected.position}</span>
          <span className="ml-auto text-[10px] uppercase tracking-wide text-text-faint">change</span>
        </button>
      ) : (
        <input
          autoFocus={open}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search a player or club code"
          className="w-full bg-raised px-3 py-2 text-sm text-text outline-none placeholder:text-text-faint"
        />
      )}
      {hits.length > 0 && (
        <div className="absolute z-20 mt-px w-full border border-divider bg-panel">
          {hits.map((p) => (
            <button
              key={p.player_id}
              type="button"
              onMouseDown={() => { onPick(p.player_id); setOpen(false); setQ('') }}
              className="flex w-full items-center gap-3 border-b border-divider px-2 py-1.5 text-left hover:bg-raised"
            >
              <PlayerPhoto code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} className="h-9 w-7" />
              <span className="text-sm font-semibold text-text">{p.name}</span>
              <span className="text-xs text-text-muted">{p.team_short} · {p.position}{p.price !== null ? ` · £${p.price.toFixed(1)}m` : ''}</span>
              {p.owned !== null && <span className="tabular ml-auto text-[10px] text-text-faint">{p.owned.toFixed(1)}%</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Hero({ p, align }: { p: ComparePlayer; align: 'left' | 'right' }) {
  const crest = crestUrl(p.team_code)
  const right = align === 'right'
  return (
    <div className={`flex items-end gap-6 ${right ? 'flex-row-reverse text-right' : ''}`}>
      <div className="relative">
        <PlayerPhoto code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} className="h-56 w-44" />
        {crest && <img src={crest} alt="" className="absolute -bottom-2 -right-2 h-10 w-10 rounded-full bg-void ring-4 ring-void" />}
      </div>
      <div className="min-w-0 pb-1">
        <Link to={`/player/${p.player_id}`} className="block font-display text-5xl font-bold uppercase leading-[0.95] text-text hover:text-pitch-green">{p.name}</Link>
        <div className="mt-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          {p.team_name} · {p.position}{p.price !== null ? ` · £${p.price.toFixed(1)}m` : ''}
        </div>
        <div className={`mt-2 flex flex-wrap gap-1.5 ${right ? 'justify-end' : ''}`}>
          {p.is_mine && <span className="bg-pitch-green px-1.5 text-[10px] font-bold uppercase leading-5 text-pitch-green-ink">in your squad</span>}
          {p.status !== 'a' && p.news && (
            <span className="bg-broadcast-gold px-1.5 text-[10px] font-bold uppercase leading-5 text-broadcast-gold-ink" title={p.news}>
              {p.chance !== null ? `${p.chance}% to play` : 'flagged'}
            </span>
          )}
          {p.start_percent !== null && p.start_percent < 70 && (
            <span className="bg-alert-red px-1.5 text-[10px] font-bold uppercase leading-5 text-alert-red-ink">{p.start_percent}% to start</span>
          )}
          {p.price_trend === 'RISE_LIKELY' && <span className="bg-broadcast-gold px-1.5 text-[10px] font-bold uppercase leading-5 text-broadcast-gold-ink">price rising</span>}
          {p.price_trend === 'FALL_LIKELY' && <span className="bg-alert-red px-1.5 text-[10px] font-bold uppercase leading-5 text-alert-red-ink">price falling</span>}
          {p.duties.length > 0 && <span className="bg-raised px-1.5 text-[10px] font-bold uppercase leading-5 text-text-muted">{p.duties.join(' · ')}</span>}
        </div>
        <div className={`mt-4 flex items-baseline gap-2 ${right ? 'justify-end' : ''}`}>
          <span className="tabular font-display text-6xl font-bold leading-none text-pitch-green">{p.xp_window.toFixed(1)}</span>
          <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-faint">xP next {p.fixture_count || 5} fixtures</span>
        </div>
      </div>
    </div>
  )
}

function Row({ r }: { r: ComparePayload['rows'][number] }) {
  if (r.a === null && r.b === null) return null
  const hi = Math.max(Math.abs(r.a ?? 0), Math.abs(r.b ?? 0), 0.0001)
  const w = (v: number | null) => `${(Math.abs(v ?? 0) / hi) * 100}%`
  const tone = (side: 'a' | 'b') => (r.winner === side ? 'bg-pitch-green' : r.winner ? 'bg-text-faint/60' : 'bg-broadcast-blue')
  const txt = (side: 'a' | 'b') => (r.winner === side ? 'text-pitch-green' : r.winner ? 'text-text-muted' : 'text-text')
  return (
    <div className="grid grid-cols-[1fr_13rem_1fr] items-center gap-4 border-b border-divider py-2">
      <div className="flex items-center justify-end gap-3">
        <span className={`tabular text-lg font-bold ${txt('a')}`}>{r.a_text ?? '—'}</span>
        <div className="flex h-3 w-48 justify-end bg-raised"><div className={`bar-draw-right h-full ${tone('a')}`} style={{ width: w(r.a) }} /></div>
      </div>
      <div className="text-center font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">{r.label}</div>
      <div className="flex items-center gap-3">
        <div className="flex h-3 w-48 bg-raised"><div className={`bar-draw h-full ${tone('b')}`} style={{ width: w(r.b) }} /></div>
        <span className={`tabular text-lg font-bold ${txt('b')}`}>{r.b_text ?? '—'}</span>
      </div>
    </div>
  )
}

function Components({ a, b }: { a: ComparePlayer; b: ComparePlayer }) {
  if (!a.components || !b.components) return null
  const ca = a.components, cb = b.components
  const hi = Math.max(...COMPONENT_LABELS.flatMap(([k]) => [Math.abs(ca[k]), Math.abs(cb[k])]), 0.5)
  return (
    <section className="border-b-2 border-divider px-10 py-7">
      <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-text">Where the next gameweek's points come from</h2>
      <p className="mb-4 mt-1 text-xs text-text-muted">The model's own breakdown of the one-gameweek projection. Negative parts are deductions.</p>
      {COMPONENT_LABELS.map(([k, label]) => {
        const va = ca[k], vb = cb[k]
        if (va === 0 && vb === 0) return null
        const bar = (v: number) => `${(Math.abs(v) / hi) * 100}%`
        return (
          <div key={k} className="grid grid-cols-[1fr_13rem_1fr] items-center gap-4 border-b border-divider py-1.5">
            <div className="flex items-center justify-end gap-3">
              <span className="tabular text-sm font-bold text-text">{va.toFixed(2)}</span>
              <div className="flex h-2.5 w-48 justify-end bg-raised"><div className={`h-full ${va >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`} style={{ width: bar(va) }} /></div>
            </div>
            <div className="text-center font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">{label}</div>
            <div className="flex items-center gap-3">
              <div className="flex h-2.5 w-48 bg-raised"><div className={`h-full ${vb >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`} style={{ width: bar(vb) }} /></div>
              <span className="tabular text-sm font-bold text-text">{vb.toFixed(2)}</span>
            </div>
          </div>
        )
      })}
    </section>
  )
}

function Verdict({ d }: { d: ComparePayload }) {
  const aWins = d.rows.filter((r) => r.winner === 'a').length
  const bWins = d.rows.filter((r) => r.winner === 'b').length
  const lead = d.gap_window >= 0 ? d.a : d.b
  const trail = d.gap_window >= 0 ? d.b : d.a
  const gap = Math.abs(d.gap_window)
  const dearer = d.price_gap === null || d.price_gap === 0 ? null : d.price_gap > 0 ? d.a : d.b
  return (
    <section className="border-b-2 border-divider bg-panel px-10 py-6">
      <div className="max-w-4xl text-base leading-relaxed text-text-muted">
        Over the next {d.window} gameweeks the model has <span className="font-bold text-text">{lead.name}</span> ahead of{' '}
        <span className="font-bold text-text">{trail.name}</span> by <span className="tabular font-bold text-pitch-green">{gap.toFixed(1)}</span> points
        {dearer ? <>, with {dearer.name} costing £{Math.abs(d.price_gap ?? 0).toFixed(1)}m more</> : null}. {d.a.name} leads on {aWins} of the measures
        below, {d.b.name} on {bWins}.
        {d.model_mae !== null && (
          <> The model's measured error is about {d.model_mae.toFixed(1)} points per player per gameweek, so a gap of {gap.toFixed(1)} over {d.window} gameweeks is
          {gap < d.model_mae ? ' inside one gameweek of noise: treat it as level.' : ' larger than one gameweek of noise but small against five: treat it as a lean, not a result.'}</>
        )}
      </div>
    </section>
  )
}

function AsTransfer({ d }: { d: ComparePayload }) {
  const t = d.as_transfer
  if (!t) return null
  const out = d.a.player_id === t.out_id ? d.a : d.b
  const into = d.a.player_id === t.in_id ? d.a : d.b
  const bank = t.bank_after_tenths / 10
  const checks: { ok: boolean; text: string }[] = [
    { ok: t.same_position, text: t.same_position ? `Same position (${out.position})` : `Different positions: ${out.name} is ${out.position}, ${into.name} is ${into.position}, so this is not a like-for-like swap` },
    { ok: t.club_ok, text: t.club_ok ? `${t.club_after} from ${into.team_short} after the swap` : `${t.club_after} from ${into.team_short} would break the three-per-club limit` },
    { ok: t.affordable, text: t.affordable ? `Bank after: £${bank.toFixed(1)}m at current sale prices` : `£${Math.abs(bank).toFixed(1)}m short at current sale prices` },
  ]
  return (
    <section className="border-b-2 border-divider bg-void px-10 py-6">
      <div className="mb-3 flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <span className="font-display text-xl font-bold uppercase tracking-wide text-text">As a transfer</span>
        <span className="text-sm text-text-muted">
          {out.name} out, {into.name} in:{' '}
          <span className="tabular font-bold text-pitch-green">{t.gain_window >= 0 ? '+' : ''}{t.gain_window.toFixed(1)}</span> xP over {d.window} fixtures,{' '}
          <span className="tabular font-bold text-text">{t.gain_next >= 0 ? '+' : ''}{t.gain_next.toFixed(1)}</span> next gameweek. You hold {t.free_transfers} free transfer{t.free_transfers === 1 ? '' : 's'}.
        </span>
      </div>
      <div className="flex flex-wrap gap-x-8 gap-y-1">
        {checks.map((c) => (
          <span key={c.text} className="flex items-center gap-2 text-xs text-text-muted">
            <span className={`px-1.5 text-[9px] font-bold uppercase leading-4 ${c.ok ? 'bg-pitch-green text-pitch-green-ink' : 'bg-alert-red text-alert-red-ink'}`}>{c.ok ? 'ok' : 'check'}</span>
            {c.text}
          </span>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-text-faint">The xP gap is the two players on their own; the week plan prices the same move inside your whole squad, so its figure can differ. Sale price is today's price; FPL pays purchase price plus half the rise, so confirm the bank on the transfers page.</p>
    </section>
  )
}

function QuickPairs({ onPick }: { onPick: (a: number, b: number) => void }) {
  const plan = useFetch(fetchWeekPlanPayload, [])
  if (plan.status !== 'ready' || plan.data.status === 'none') return null
  const pairs = [...(plan.data.moves ?? []), ...(plan.data.declined ?? [])].slice(0, 6)
  if (pairs.length === 0) return null
  return (
    <div className="mt-6">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">From your week plan</div>
      <div className="flex flex-wrap gap-2">
        {pairs.map((m) => (
          <button key={m.into.player_id} type="button" onClick={() => onPick(m.out.player_id, m.into.player_id)} className="bg-raised px-3 py-1.5 text-sm text-text hover:bg-divider">
            {m.out.name} <span className="text-text-faint">vs</span> {m.into.name}
          </button>
        ))}
      </div>
    </div>
  )
}

export function CompareScreen() {
  const [params, setParams] = useSearchParams()
  const a = Number(params.get('a')) || null
  const b = Number(params.get('b')) || null
  const index = useFetch(fetchPlayersIndex, [])
  const compare = useFetch(() => (a && b ? fetchComparePayload(a, b) : Promise.resolve(null)), [a, b])
  const rows = index.status === 'ready' ? index.data.players : []
  const find = (id: number | null) => (id ? rows.find((p) => p.player_id === id) ?? null : null)
  const set = (key: 'a' | 'b', id: number | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set(key, String(id))
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <div className="data-in pb-16">
      <Masthead edition="Compare" title="Two players, on the numbers that decide a transfer" />
      <div className="grid grid-cols-2 gap-10 border-b-2 border-divider px-10 py-5">
        <Picker label="Player A" selected={find(a)} index={rows} onPick={(id) => set('a', id)} exclude={b} />
        <Picker label="Player B" selected={find(b)} index={rows} onPick={(id) => set('b', id)} exclude={a} />
      </div>

      {(!a || !b) && (
        <div className="px-10 py-10">
          <p className="max-w-2xl text-sm text-text-muted">Pick two players. The page lines up what the model projects for each, where those points come from, the season line, and the next five fixtures.</p>
          <QuickPairs onPick={(x, y) => setParams(new URLSearchParams({ a: String(x), b: String(y) }), { replace: true })} />
        </div>
      )}

      {a && b && compare.status === 'loading' && (
        <div className="animate-pulse px-10 py-8">
          <SkelMasthead />
          <Skel className="mt-6 h-64 w-full" />
          <Skel className="mt-6 h-48 w-full" />
        </div>
      )}
      {a && b && compare.status === 'error' && (
        <ScreenError title="Comparison unavailable" description="One of the two players could not be projected, so nothing is shown for either." message={compare.error.message} />
      )}
      {a && b && compare.status === 'ready' && compare.data && (
        <>
          <section className="grid grid-cols-2 gap-10 border-b-2 border-divider px-10 py-8">
            <Hero p={compare.data.a} align="left" />
            <Hero p={compare.data.b} align="right" />
          </section>
          <Verdict d={compare.data} />
          <AsTransfer d={compare.data} />
          <section className="border-b-2 border-divider px-10 py-7">
            {compare.data.rows.map((r) => <Row key={r.key} r={r} />)}
          </section>
          <Components a={compare.data.a} b={compare.data.b} />
          <section className="grid grid-cols-2 gap-10 px-10 py-7">
            {[compare.data.a, compare.data.b].map((p) => (
              <div key={p.player_id}>
                <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">{p.name} · next fixtures</div>
                <FixtureRun fixtures={p.fixtures} max={5} showEvent />
                {p.news && <p className="mt-3 text-xs text-text-muted">Official note: {p.news}</p>}
                <p className="tabular mt-3 text-xs text-text-muted">
                  Season: {p.total_points ?? 0} pts · {p.goals ?? 0}G {p.assists ?? 0}A · {p.minutes} min{p.xg !== null ? ` · xG ${p.xg.toFixed(1)}` : ''}{p.xa !== null ? ` · xA ${p.xa.toFixed(1)}` : ''}
                </p>
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  )
}
