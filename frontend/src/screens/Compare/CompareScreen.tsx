import { useMemo, useState } from 'react'
import { FootballReadInline } from '@/components/football/FootballRead'
import { Link, useSearchParams } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import { FixtureRun } from '@/components/football/FixtureRun'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { HeroPhoto } from '@/components/ui/HeroPhoto'
import { clubColors } from '@/lib/clubs'
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
  ['clean_sheet', 'Clean sheet'], ['conceded', 'Goals conceded'], ['cards', 'Cards'], ['defcon', 'Defensive actions'], ['saves', 'Saves'],
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
      <div className="mb-1.5 font-display text-[15px] font-black uppercase tracking-[0.04em] text-text">{label}</div>
      {selected && !open ? (
        <button type="button" onClick={() => { setOpen(true); setQ('') }} className="flex w-full items-center gap-2 border-2 border-ink bg-paper px-3 py-2 text-left shadow-[3px_3px_0_var(--ink)]">
          <span className="font-bold text-text">{selected.name}</span>
          <span className="text-xs text-text-muted">{selected.team_short} · {selected.position}</span>
          <span className="ml-auto text-[12px] text-text-faint">change</span>
        </button>
      ) : (
        <input
          autoFocus={open}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search a player or club code"
          className="w-full border-2 border-ink bg-paper px-3 py-2 text-sm text-text shadow-[3px_3px_0_var(--ink)] outline-none placeholder:text-text-faint focus:shadow-[3px_3px_0_var(--spot)]"
        />
      )}
      {hits.length > 0 && (
        <div className="absolute z-40 mt-1 max-h-[26rem] w-full overflow-y-auto border-2 border-ink bg-panel shadow-[5px_5px_0_var(--ink)]">
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
              {p.owned !== null && <span className="tabular ml-auto text-[12px] text-text-faint">{p.owned.toFixed(1)}%</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** One side of the face-off: the player's club colours as a printed plate, his cut-out, his name as a poster line. */
function Hero({ p, align }: { p: ComparePlayer; align: 'left' | 'right' }) {
  const crest = crestUrl(p.team_code)
  const right = align === 'right'
  const club = clubColors(p.team_code)
  const tag = 'border-2 border-ink px-1.5 font-display text-[13px] font-black uppercase leading-5 shadow-[2px_2px_0_var(--ink)]'
  return (
    <div
      className="relative min-h-[21rem] overflow-hidden"
      style={{ background: `linear-gradient(${right ? 240 : 120}deg, ${club.primary} 0%, color-mix(in srgb, ${club.primary} 70%, #17130e) 100%)` }}
    >
      <div className="absolute inset-0 opacity-35 [background-image:radial-gradient(rgba(23,19,14,0.6)_1px,transparent_1.5px)] [background-size:6px_6px]" />
      {crest && <img src={crest} alt="" className={`absolute -top-14 size-[20rem] opacity-[0.18] mix-blend-multiply ${right ? '-left-16' : '-right-16'}`} />}
      <HeroPhoto
        code={p.photo_code}
        teamCode={p.team_code}
        isGkp={p.position === 'GKP'}
        className={`absolute bottom-0 h-[19rem] w-[19rem] drop-shadow-[8px_8px_0_rgba(23,19,14,0.35)] ${right ? 'left-2' : 'right-2'}`}
      />
      <div className={`relative z-10 flex h-full min-h-[21rem] flex-col justify-end px-8 pb-7 pt-8 ${right ? 'items-end text-right' : ''}`}>
        <div className="voice text-lg text-paper/85">{p.team_name} · {p.position}{p.price !== null ? ` · £${p.price.toFixed(1)}m` : ''}</div>
        <Link
          to={`/player/${p.player_id}`}
          className="block max-w-[60%] font-display text-[4.2rem] font-black uppercase leading-[0.85] text-paper [text-shadow:5px_5px_0_var(--ink)] hover:text-broadcast-gold"
        >
          {p.name}
        </Link>
        <div className={`mt-3 flex max-w-[62%] flex-wrap gap-1.5 ${right ? 'justify-end' : ''}`}>
          {p.is_mine && <span className={`${tag} bg-pitch-green text-pitch-green-ink`}>in your squad</span>}
          {p.status !== 'a' && p.news && (
            <span className={`${tag} bg-broadcast-gold text-broadcast-gold-ink`} title={p.news}>
              {p.chance !== null ? `${p.chance}% to play` : 'flagged'}
            </span>
          )}
          {p.start_percent !== null && p.start_percent < 70 && (
            <span className={`${tag} bg-alert-red text-alert-red-ink`}>{p.start_percent}% to start</span>
          )}
          {p.price_trend === 'RISE_LIKELY' && <span className={`${tag} bg-broadcast-gold text-broadcast-gold-ink`}>price rising</span>}
          {p.price_trend === 'FALL_LIKELY' && <span className={`${tag} bg-alert-red text-alert-red-ink`}>price falling</span>}
          {p.duties.length > 0 && <span className={`${tag} bg-paper text-text`}>{p.duties.join(' · ')}</span>}
        </div>
        <div className={`mt-4 inline-flex items-baseline gap-2 border-2 border-ink bg-paper px-3 py-1 shadow-[4px_4px_0_var(--ink)] ${right ? "self-end" : "self-start"}`}>
          <span className="tabular font-display text-5xl font-black leading-none text-pitch-green">{p.xp_window.toFixed(1)}</span>
          <span className="text-[12px] font-bold text-text-muted">xP next {p.fixture_count || 5}</span>
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
      <div className="text-center text-[12px] text-text-faint">{r.label}</div>
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
    <section className="border-b border-divider px-10 py-7">
      <h2 className="font-display text-2xl font-bold text-text">Where the next gameweek's points come from</h2>
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
            <div className="text-center text-[12px] text-text-faint">{label}</div>
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
    <section className="border-b border-divider bg-panel px-10 py-6">
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
    <section className="border-b border-divider bg-void px-10 py-6">
      <div className="mb-3 flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <h2 className="font-display text-xl font-bold text-text">As a transfer</h2>
        <span className="text-sm text-text-muted">
          {out.name} out, {into.name} in:{' '}
          <span className="tabular font-bold text-pitch-green">{t.gain_window >= 0 ? '+' : ''}{t.gain_window.toFixed(1)}</span> xP over {d.window} fixtures,{' '}
          <span className="tabular font-bold text-text">{t.gain_next >= 0 ? '+' : ''}{t.gain_next.toFixed(1)}</span> next gameweek. You hold {t.free_transfers} free transfer{t.free_transfers === 1 ? '' : 's'}.
        </span>
      </div>
      <div className="flex flex-wrap gap-x-8 gap-y-1">
        {checks.map((c) => (
          <span key={c.text} className="flex items-center gap-2 text-xs text-text-muted">
            <span className={`px-1.5 text-[12px] font-bold leading-4 ${c.ok ? 'bg-pitch-green text-pitch-green-ink' : 'bg-alert-red text-alert-red-ink'}`}>{c.ok ? 'ok' : 'check'}</span>
            {c.text}
          </span>
        ))}
      </div>
      <p className="mt-2 text-[13px] text-text-faint">The xP gap is the two players on their own; the week plan prices the same move inside your whole squad, so its figure can differ. Sale price is today's price; FPL pays purchase price plus half the rise, so confirm the bank on the transfers page.</p>
    </section>
  )
}

function QuickPairs({ onPick }: { onPick: (a: number, b: number) => void }) {
  const plan = useFetch(fetchWeekPlanPayload, [])
  if (plan.status !== 'ready' || plan.data.status === 'none') return null
  const now = [...(plan.data.moves ?? []), ...(plan.data.declined ?? [])]
    .slice(0, 6)
    .map((m) => ({ out: m.out.player_id, into: m.into.player_id, label: [m.out.name, m.into.name], when: `GW${plan.data.event}` }))
  const later = (plan.data.road_ahead?.weeks ?? [])
    .flatMap((w) => w.moves.filter((m) => m.out_id && m.in_id).map((m) => ({ out: m.out_id!, into: m.in_id!, label: [m.out, m.into], when: `GW${w.event}` })))
    .slice(0, 8)
  const groups: [string, typeof now][] = [['This week, from your plan', now], ['Moves the plan has lined up for later weeks', later]]
  if (now.length + later.length === 0) return null
  return (
    <div className="mt-6 space-y-5">
      {groups.filter(([, list]) => list.length > 0).map(([title, list]) => (
        <div key={title}>
          <div className="mb-2 font-display text-[15px] font-black uppercase tracking-[0.04em] text-text">{title}</div>
          <div className="flex flex-wrap gap-3">
            {list.map((m) => (
              <button
                key={`${m.out}-${m.into}`}
                type="button"
                onClick={() => onPick(m.out, m.into)}
                className="flex items-baseline gap-2 border-2 border-ink bg-paper px-3 py-1.5 text-sm text-text shadow-[3px_3px_0_var(--ink)] transition-transform hover:-translate-y-0.5 hover:shadow-[3px_3px_0_var(--spot)]"
              >
                <span className="font-display text-[12px] font-black text-text-faint">{m.when}</span>
                <span className="font-semibold">{m.label[0]}</span>
                <span className="voice text-text-faint">vs</span>
                <span className="font-semibold">{m.label[1]}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/** HOW THEY PLAY, side by side: each player's profile and his percentile on every quality measure both are ranked on,
 * as mirrored bars, then the style lines. Percentiles are within each player's own position (stated). */
/** Both football reads side by side: the verdict and every line, each marked by whether it holds up match to match. */
function ReadCompare({ a, b }: { a: ComparePlayer; b: ComparePlayer }) {
  if (!a.football_read || !b.football_read) return null
  return (
    <section className="border-b border-divider px-10 py-7">
      <div className="mb-3 flex flex-wrap items-baseline gap-3">
        <h2 className="font-display text-2xl font-bold text-text">The football read</h2>
        <span className="text-[13px] text-text-faint">each line marked by whether that kind of evidence holds up from match to match</span>
      </div>
      <div className="grid grid-cols-2 gap-10">
        {[a.football_read, b.football_read].map((r) => (
          <div key={r.player_id} className="min-w-0">
            <div className="mb-1 font-display text-lg font-semibold text-text">{r.name}</div>
            <FootballReadInline r={r} open />
          </div>
        ))}
      </div>
    </section>
  )
}

function CraftCompare({ a, b }: { a: ComparePlayer; b: ComparePlayer }) {
  const sa = a.scouting
  const sb = b.scouting
  if (!sa || !sb) return null
  const byKey = new Map(sb.measures.map((m) => [m.key, m]))
  const shared = sa.measures.filter((m) => m.kind === 'quality' && byKey.has(m.key))
  const tone = (p: number | null) => (p === null ? 'bg-text-faint/40' : p >= 75 ? 'bg-pitch-green' : p <= 25 ? 'bg-alert-red' : 'bg-broadcast-blue')
  return (
    <section className="border-b border-divider px-10 py-7">
      <div className="mb-1 flex flex-wrap items-baseline gap-3">
        <h2 className="font-display text-2xl font-bold text-text">How they play</h2>
        <span className="text-[13px] text-text-faint">
          percentiles within each player's position this season ({sa.position} {sa.minutes} min · {sb.position} {sb.minutes} min)
        </span>
      </div>
      <div className="mb-4 mt-3 grid grid-cols-2 gap-10">
        {[sa, sb].map((s, i) => (
          <div key={i} className={`flex flex-wrap gap-1.5 ${i === 1 ? 'justify-end' : ''}`}>
            {s.profile.length ? (
              s.profile.map((t) => (
                <span key={t} className="rounded-full border border-pitch-green/35 bg-pitch-green/10 px-2.5 py-0.5 text-[12.5px] font-semibold text-pitch-green">
                  {t}
                </span>
              ))
            ) : (
              <span className="text-[13px] text-text-faint">no profile above the bar</span>
            )}
          </div>
        ))}
      </div>
      <div className="space-y-1">
        {shared.map((ma) => {
          const mb = byKey.get(ma.key)!
          const pa = ma.percentile ?? 0
          const pb = mb.percentile ?? 0
          return (
            <div key={ma.key} className="grid grid-cols-[3.5rem_minmax(0,1fr)_11rem_minmax(0,1fr)_3.5rem] items-center gap-3 py-1">
              <span className={`text-right font-display text-lg font-bold tabular-nums ${pa > pb ? 'text-text' : 'text-text-muted'}`}>{ma.display}</span>
              <div className="flex h-2.5 justify-end rounded-full bg-raised">
                <div className={`bar-draw h-full rounded-full ${tone(ma.percentile)}`} style={{ width: `${Math.max(3, pa)}%` }} />
              </div>
              <div className="text-center">
                <div className="text-[13px] font-semibold text-text">{ma.label}</div>
                <div className="text-[11px] text-text-faint">
                  {ma.percentile ?? '–'} · {ma.unit} · {mb.percentile ?? '–'}
                </div>
              </div>
              <div className="h-2.5 rounded-full bg-raised">
                <div className={`bar-draw h-full rounded-full ${tone(mb.percentile)}`} style={{ width: `${Math.max(3, pb)}%` }} />
              </div>
              <span className={`font-display text-lg font-bold tabular-nums ${pb > pa ? 'text-text' : 'text-text-muted'}`}>{mb.display}</span>
            </div>
          )
        })}
      </div>
      <div className="mt-5 grid grid-cols-2 gap-10 text-[13.5px] leading-snug text-text-muted">
        {[sa, sb].map((s, i) => (
          <ul key={i} className={`space-y-1 ${i === 1 ? 'text-right' : ''}`}>
            {s.style.map((m) => (
              <li key={m.key}>
                {m.label}: <span className="font-semibold text-text">{m.display}</span>
                {m.median_display && <span className="text-text-faint"> (median {m.median_display})</span>}
              </li>
            ))}
            {s.finishing && (
              <li>
                {s.finishing.np_goals} non-penalty goals from {s.finishing.npxg.toFixed(2)} xG{' '}
                <span className={s.finishing.difference >= 0 ? 'text-pitch-green' : 'text-alert-red'}>
                  ({s.finishing.difference >= 0 ? '+' : ''}
                  {s.finishing.difference.toFixed(2)})
                </span>
              </li>
            )}
          </ul>
        ))}
      </div>
    </section>
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
      <div className="allow-overflow relative z-30 grid grid-cols-2 gap-10 border-b border-divider px-10 py-5">
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
          <section className="relative grid grid-cols-2 gap-[2px] !bg-ink">
            <Hero p={compare.data.a} align="left" />
            <Hero p={compare.data.b} align="right" />
            <span className="absolute left-1/2 top-1/2 z-20 flex size-20 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-[3px] border-ink bg-spot font-display text-4xl font-black text-ink shadow-[4px_4px_0_var(--ink)]">
              VS
            </span>
          </section>
          <Verdict d={compare.data} />
          <AsTransfer d={compare.data} />
          <section className="border-b border-divider px-10 py-7">
            {compare.data.rows.map((r) => <Row key={r.key} r={r} />)}
          </section>
          <Components a={compare.data.a} b={compare.data.b} />
          <ReadCompare a={compare.data.a} b={compare.data.b} />
          <CraftCompare a={compare.data.a} b={compare.data.b} />
          <section className="grid grid-cols-2 gap-10 px-10 py-7">
            {[compare.data.a, compare.data.b].map((p) => (
              <div key={p.player_id}>
                <div className="mb-2 text-[12px] text-text-faint">{p.name} · next fixtures</div>
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
