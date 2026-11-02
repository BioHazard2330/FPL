import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { ScreenError } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** VERSUS THE 10K - the season set against fifty managers ranked around 10,000 overall (`models/cohort_compare`). The
 * gap splits exactly by player (points times your multiplier minus theirs), the armband, hits and automatic
 * substitutions; then the weeks, the players who made the gap, the armband calls, chips and the template now. */

interface Swing { player_id: number; name: string; photo_code: number | null; team_code: number | null; swing: number; weeks: [number, number][]; share?: number }
interface Week {
  event: number; you: number; rank: number | null; cohort_mean: number | null; cohort_p25: number | null; cohort_p75: number | null; n: number
  captain: { you: { player_id: number | null; name: string; points: number; extra: number }; cohort_top: { player_id: number | null; name: string; share: number | null; points: number }; cohort_extra: number | null }
  bench_you: number | null; bench_cohort: number | null; hits_you: number; hits_cohort: number | null; transfers_you: number | null; transfers_cohort: number | null
  chip_you: string | null; chips_cohort: Record<string, number>
}
interface CohortPayload {
  status: string; managers: number; events: number[]; weeks: Week[]
  totals: { you: number; cohort: number; gap: number; captain: number; hits: number; players: number; subs: number; bench_you: number; bench_cohort: number; transfers_you: number; transfers_cohort: number }
  losses: Swing[]; gains: Swing[]; template: { event: number; missing: Swing[]; yours: Swing[] }
}

const signed = (v: number, d = 0) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`
const CHIP: Record<string, string> = { wildcard: 'WC', freehit: 'FH', bboost: 'BB', '3xc': 'TC' }

function Waterfall({ t }: { t: CohortPayload['totals'] }) {
  const parts = [
    { label: 'Players', sub: 'who you owned and started, against them', v: t.players },
    { label: 'Armband', sub: 'your captain’s extra points against theirs', v: t.captain },
    { label: 'Hits', sub: 'points paid for transfers', v: t.hits },
    { label: 'Auto-subs', sub: 'substitutions FPL made', v: t.subs },
  ]
  let run = 0
  const steps = parts.map((p) => { const from = run; run += p.v; return { ...p, from, to: run } })
  const lo = Math.min(0, ...steps.map((s) => Math.min(s.from, s.to))) - 4
  const hi = Math.max(0, ...steps.map((s) => Math.max(s.from, s.to))) + 4
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100
  return (
    <div className="mt-6 space-y-2.5">
      {steps.map((s) => (
        <div key={s.label} className="grid grid-cols-[9rem_minmax(0,1fr)_5rem] items-center gap-4">
          <div>
            <div className="font-display text-[17px] font-black uppercase leading-none text-text">{s.label}</div>
            <div className="mt-0.5 text-[11.5px] leading-tight text-text-faint">{s.sub}</div>
          </div>
          <div className="relative h-9 border-y-2 border-ink/15">
            <div className="absolute inset-y-0 w-[2px] bg-ink" style={{ left: `${x(0)}%` }} />
            <div
              className={`absolute inset-y-1.5 border-2 border-ink shadow-[3px_3px_0_var(--ink)] ${s.v >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`}
              style={{ left: `${x(Math.min(s.from, s.to))}%`, width: `${Math.max(0.6, Math.abs(x(s.to) - x(s.from)))}%` }}
            />
          </div>
          <div className={`tabular text-right font-display text-2xl font-black ${s.v >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(s.v)}</div>
        </div>
      ))}
      <div className="grid grid-cols-[9rem_minmax(0,1fr)_5rem] items-center gap-4 border-t-[3px] border-ink pt-2.5">
        <div className="font-display text-[17px] font-black uppercase text-text">The gap</div>
        <div className="relative h-9">
          <div className="absolute inset-y-0 w-[2px] bg-ink" style={{ left: `${x(0)}%` }} />
          <div className={`absolute inset-y-1 border-[3px] border-ink ${t.gap >= 0 ? 'bg-pitch-green' : 'bg-spot'}`}
            style={{ left: `${x(Math.min(0, t.gap))}%`, width: `${Math.abs(x(t.gap) - x(0))}%` }} />
        </div>
        <div className="tabular text-right font-display text-3xl font-black text-text">{signed(t.gap)}</div>
      </div>
    </div>
  )
}

function Weeks({ weeks }: { weeks: Week[] }) {
  const W = 980, H = 300, pad = 34
  const vals = weeks.flatMap((w) => [w.you, w.cohort_p25 ?? w.you, w.cohort_p75 ?? w.you])
  const lo = Math.max(0, Math.min(...vals) - 10), hi = Math.max(...vals) + 10
  const y = (v: number) => H - pad - ((v - lo) / (hi - lo)) * (H - 2 * pad)
  const bx = (i: number) => pad + 30 + (i * (W - 2 * pad - 60)) / Math.max(1, weeks.length - 1)
  let cum = 0
  const cumPts = weeks.map((w, i) => { cum += w.you - (w.cohort_mean ?? w.you); return { i, cum } })
  const cmax = Math.max(10, ...cumPts.map((c) => Math.abs(c.cum)))
  const cy = (v: number) => 380 - (v / cmax) * 60
  return (
    <svg viewBox={`0 0 ${W} 460`} className="mt-4 w-full">
      {[lo, (lo + hi) / 2, hi].map((g) => (
        <g key={g}>
          <line x1={pad} x2={W - pad} y1={y(g)} y2={y(g)} stroke="var(--ink)" strokeOpacity={0.12} strokeDasharray="4 4" />
          <text x={pad - 6} y={y(g) + 4} textAnchor="end" fontSize={11} fill="var(--text-faint)">{Math.round(g)}</text>
        </g>
      ))}
      {weeks.map((w, i) => {
        const above = w.cohort_mean !== null && w.you >= w.cohort_mean
        return (
          <g key={w.event}>
            {w.cohort_p25 !== null && w.cohort_p75 !== null && (
              <rect x={bx(i) - 16} width={32} y={y(w.cohort_p75)} height={Math.max(2, y(w.cohort_p25) - y(w.cohort_p75))} fill="var(--broadcast-blue)" fillOpacity={0.16} stroke="var(--broadcast-blue)" strokeOpacity={0.5} />
            )}
            {w.cohort_mean !== null && <line x1={bx(i) - 20} x2={bx(i) + 20} y1={y(w.cohort_mean)} y2={y(w.cohort_mean)} stroke="var(--broadcast-blue)" strokeWidth={3} />}
            {w.cohort_mean !== null && <line x1={bx(i)} x2={bx(i)} y1={y(w.cohort_mean)} y2={y(w.you)} stroke={above ? 'var(--pitch-green)' : 'var(--alert-red)'} strokeWidth={3} />}
            <circle cx={bx(i)} cy={y(w.you)} r={9} fill={above ? 'var(--pitch-green)' : 'var(--alert-red)'} stroke="var(--ink)" strokeWidth={2.5} />
            <text x={bx(i) + 14} y={y(w.you) + 5} textAnchor="start" fontSize={15} fontWeight={900} fill="var(--text)" fontFamily="Big Shoulders Display, Impact, sans-serif">{w.you}</text>
            {w.chip_you && <text x={bx(i)} y={y(w.you) + 26} textAnchor="middle" fontSize={11} fontWeight={900} fill="var(--spot)" fontFamily="Big Shoulders Display, Impact, sans-serif">{CHIP[w.chip_you] ?? w.chip_you}</text>}
            <text x={bx(i)} y={H - 8} textAnchor="middle" fontSize={12} fontWeight={800} fill="var(--text-faint)">GW{w.event}</text>
          </g>
        )
      })}
      <text x={pad} y={322} fontSize={11} fontWeight={800} letterSpacing="0.12em" fill="var(--text-faint)">RUNNING GAP TO THE 10K AVERAGE</text>
      <line x1={pad} x2={W - pad} y1={cy(0)} y2={cy(0)} stroke="var(--ink)" strokeWidth={2} />
      <polyline fill="none" stroke="var(--spot)" strokeWidth={4} strokeLinejoin="round" points={cumPts.map((c) => `${bx(c.i)},${cy(c.cum)}`).join(' ')} />
      {cumPts.map((c) => (
        <g key={c.i}>
          <circle cx={bx(c.i)} cy={cy(c.cum)} r={5} fill="var(--paper)" stroke="var(--ink)" strokeWidth={2} />
          <text x={bx(c.i)} y={cy(c.cum) + (c.cum >= 0 ? -10 : 18)} textAnchor="middle" fontSize={11} fontWeight={800} fill="var(--text)">{signed(c.cum)}</text>
        </g>
      ))}
    </svg>
  )
}

function SwingCard({ s, events }: { s: Swing; events: number[] }) {
  const max = Math.max(4, ...s.weeks.map(([, d]) => Math.abs(d)))
  const byEv = new Map(s.weeks)
  return (
    <Link to={`/player/${s.player_id}`} className="grid grid-cols-[2.6rem_minmax(0,1fr)_auto] items-center gap-3 border-b border-divider py-2 hover:bg-raised/50">
      <PlayerPhoto code={s.photo_code} teamCode={s.team_code} className="h-12 w-10" />
      <div className="min-w-0">
        <div className="truncate text-[14.5px] font-bold text-text">{s.name}</div>
        <div className="mt-1 flex h-7 items-center gap-[3px]">
          {events.map((e) => {
            const d = byEv.get(e) ?? 0
            const h = Math.max(1, (Math.abs(d) / max) * 13)
            return (
              <div key={e} className="relative h-full w-2.5" title={`GW${e}: ${signed(d, 1)}`}>
                <div className="absolute inset-x-0 top-1/2 h-px bg-ink/25" />
                <div className={`absolute inset-x-0 ${d >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`} style={d >= 0 ? { bottom: '50%', height: h } : { top: '50%', height: h }} />
              </div>
            )
          })}
        </div>
      </div>
      <div className={`tabular font-display text-2xl font-black ${s.swing >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(s.swing)}</div>
    </Link>
  )
}

export function VersusScreen() {
  const state = useFetch(() => getJson<CohortPayload>('/api/cohort'), [])
  if (state.status === 'loading') return <div className="p-10 text-text-muted">Reading the cohort…</div>
  if (state.status === 'error') return <ScreenError title="Versus the 10k unavailable" description="The cohort comparison could not be read." message={state.error.message} />
  const d = state.data
  if (d.status !== 'ok') {
    return (
      <div>
        <Masthead />
        <section className="px-10 py-10 text-text-muted">The cohort has not been sampled yet: it is read once per finished gameweek by the scheduled sync.</section>
      </div>
    )
  }
  const t = d.totals
  const last = d.weeks[d.weeks.length - 1]
  const capWon = d.weeks.filter((w) => w.captain.you.extra > (w.captain.cohort_extra ?? 0)).length
  return (
    <div>
      <Masthead right={<span>{d.managers} managers ranked around 10,000 · GW{d.events[0]}–{d.events[d.events.length - 1]}</span>} />

      <section className="relative overflow-hidden !bg-ink px-10 py-9 text-paper">
        <div className="absolute -right-10 -top-16 select-none font-display text-[22rem] font-black leading-none text-paper/[0.04]">10K</div>
        <div className="relative grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div>
            <div className="voice text-xl text-paper/70">your season against the managers who are where you want to be</div>
            <h1 className="mt-1 font-display text-[3.6rem] font-black uppercase leading-[0.9] text-paper">Versus the 10k</h1>
            <div className="mt-7 flex items-end gap-8">
              <div>
                <div className={`tabular font-display text-[7rem] font-black leading-[0.8] ${t.gap >= 0 ? 'text-pitch-green' : 'text-spot'}`}>{signed(t.gap)}</div>
                <div className="mt-3 text-[13px] text-paper/60">points against their average, after hits, over {d.weeks.length} gameweeks</div>
              </div>
              <div className="space-y-1 pb-2 text-[13px] text-paper/70">
                <div><span className="tabular font-display text-2xl font-black text-paper">{t.you}</span> you</div>
                <div><span className="tabular font-display text-2xl font-black text-paper">{t.cohort.toFixed(0)}</span> them</div>
                {last.rank && <div>rank <span className="font-bold text-paper">{last.rank.toLocaleString()}</span></div>}
              </div>
            </div>
          </div>
          <div className="border-2 border-paper/20 bg-paper p-6 text-text shadow-[6px_6px_0_var(--spot)]">
            <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-text-faint">where the gap came from</div>
            <Waterfall t={t} />
          </div>
        </div>
      </section>

      <section className="px-10 py-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="voice text-lg text-text-muted">each gameweek, you against their middle half</div>
            <h2 className="font-display text-text">Week by week</h2>
          </div>
          <div className="flex gap-5 text-[12px] text-text-muted">
            <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-5 border border-broadcast-blue bg-broadcast-blue/20" />their middle half</span>
            <span className="flex items-center gap-1.5"><span className="inline-block h-[3px] w-5 bg-broadcast-blue" />their average</span>
            <span className="flex items-center gap-1.5"><span className="inline-block size-3 rounded-full border-2 border-ink bg-pitch-green" />you</span>
          </div>
        </div>
        <Weeks weeks={d.weeks} />
      </section>

      <section className="grid grid-cols-1 gap-px border-y-2 border-ink bg-ink xl:grid-cols-2">
        <div className="bg-void px-10 py-8">
          <div className="voice text-lg text-text-muted">owned less than they did, and he scored</div>
          <h2 className="font-display text-alert-red">Who cost you</h2>
          <div className="mt-4">{d.losses.map((s) => <SwingCard key={s.player_id} s={s} events={d.events} />)}</div>
        </div>
        <div className="bg-void px-10 py-8">
          <div className="voice text-lg text-text-muted">owned or captained more than they did, and it paid</div>
          <h2 className="font-display text-pitch-green">Who won you points</h2>
          <div className="mt-4">{d.gains.map((s) => <SwingCard key={s.player_id} s={s} events={d.events} />)}</div>
        </div>
      </section>

      <section className="px-10 py-8">
        <div className="voice text-lg text-text-muted">your captain against the cohort's favourite, and the extra points each brought</div>
        <h2 className="font-display text-text">The armband <span className="text-text-faint">· yours beat theirs {capWon} of {d.weeks.length}</span></h2>
        <div className="mt-5 grid gap-3" style={{ gridTemplateColumns: `repeat(${d.weeks.length}, minmax(0, 1fr))` }}>
          {d.weeks.map((w) => {
            const diff = w.captain.you.extra - (w.captain.cohort_extra ?? 0)
            return (
              <div key={w.event} className={`border-2 border-ink p-2.5 shadow-[3px_3px_0_var(--ink)] ${diff > 0 ? 'bg-[color-mix(in_srgb,var(--pitch-green)_14%,var(--paper))]' : diff < 0 ? 'bg-[color-mix(in_srgb,var(--alert-red)_10%,var(--paper))]' : 'bg-paper'}`}>
                <div className="font-display text-[12px] font-black uppercase text-text-faint">GW{w.event}</div>
                <div className="mt-1 truncate text-[13px] font-bold text-text">{w.captain.you.name}</div>
                <div className="tabular font-display text-2xl font-black text-text">+{w.captain.you.extra}</div>
                <div className="mt-1.5 border-t border-ink/20 pt-1.5 text-[11px] leading-snug text-text-muted">
                  theirs: <span className="font-semibold text-text">{w.captain.cohort_top.name}</span> {w.captain.cohort_top.share !== null ? `${Math.round(w.captain.cohort_top.share * 100)}%` : ''}
                  <br />avg extra <span className="tabular font-semibold">{w.captain.cohort_extra?.toFixed(1)}</span>
                </div>
                <div className={`tabular mt-1 font-display text-lg font-black ${diff >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(diff, 1)}</div>
              </div>
            )
          })}
        </div>
      </section>

      <section className="grid grid-cols-1 gap-px border-y-2 border-ink bg-ink xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="bg-void px-10 py-8">
          <div className="voice text-lg text-text-muted">how you managed it, against their averages</div>
          <h2 className="font-display text-text">Habits</h2>
          <div className="mt-5 grid grid-cols-3 gap-4">
            {[
              { k: 'Transfers made', you: t.transfers_you, them: t.transfers_cohort },
              { k: 'Bench points left', you: t.bench_you, them: t.bench_cohort },
              { k: 'Points paid in hits', you: -t.hits + 0, them: null as number | null, raw: d.weeks.reduce((n, w) => n + w.hits_you, 0), rawThem: d.weeks.reduce((n, w) => n + (w.hits_cohort ?? 0), 0) },
            ].map((h) => (
              <div key={h.k} className="border-2 border-ink bg-paper p-4 shadow-[4px_4px_0_var(--ink)]">
                <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">{h.k}</div>
                <div className="tabular mt-1 font-display text-4xl font-black text-text">{'raw' in h ? h.raw : h.you}</div>
                <div className="tabular text-[13px] text-text-muted">them {('rawThem' in h ? h.rawThem : h.them)?.toFixed(1)}</div>
              </div>
            ))}
          </div>
          <div className="mt-6 text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">chips, gameweek by gameweek (share of the cohort)</div>
          <div className="mt-2 grid gap-1.5" style={{ gridTemplateColumns: `repeat(${d.weeks.length}, minmax(0, 1fr))` }}>
            {d.weeks.map((w) => (
              <div key={w.event} className="text-center">
                <div className="flex h-24 flex-col-reverse border-2 border-ink bg-paper">
                  {Object.entries(w.chips_cohort).map(([c, share]) => (
                    <div key={c} className={`flex items-center justify-center text-[10px] font-black text-paper ${c === 'wildcard' ? 'bg-broadcast-blue' : c === 'freehit' ? 'bg-pitch-green' : c === 'bboost' ? 'bg-broadcast-gold' : 'bg-alert-red'}`} style={{ height: `${share * 100}%` }}>
                      {share >= 0.1 ? CHIP[c] ?? c : ''}
                    </div>
                  ))}
                </div>
                <div className="mt-1 font-display text-[11px] font-black text-text-faint">GW{w.event}</div>
                <div className="h-4 font-display text-[12px] font-black text-spot">{w.chip_you ? CHIP[w.chip_you] ?? w.chip_you : ''}</div>
              </div>
            ))}
          </div>
          <div className="mt-1 text-[11.5px] text-text-faint">Orange below a column: the chip you played that week.</div>
        </div>
        <div className="bg-void px-10 py-8">
          <div className="voice text-lg text-text-muted">their fifteen in GW{d.template.event}, against yours</div>
          <h2 className="font-display text-text">The template</h2>
          <div className="mt-4 text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">owned most by them, not by you</div>
          <div className="mt-2 space-y-1.5">
            {d.template.missing.map((s) => (
              <Link key={s.player_id} to={`/player/${s.player_id}`} className="grid grid-cols-[2rem_minmax(0,1fr)_10rem] items-center gap-3 hover:bg-raised/50">
                <PlayerPhoto code={s.photo_code} teamCode={s.team_code} className="h-9 w-7" />
                <span className="truncate text-[14px] font-bold text-text">{s.name}</span>
                <span className="relative h-5 border-2 border-ink bg-paper">
                  <span className="absolute inset-y-0 left-0 bg-alert-red" style={{ width: `${(s.share ?? 0) * 100}%` }} />
                  <span className="tabular absolute inset-0 flex items-center justify-end pr-1.5 text-[11px] font-black text-text">{Math.round((s.share ?? 0) * 100)}%</span>
                </span>
              </Link>
            ))}
          </div>
          <div className="mt-5 text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">your fifteen, and how many of them own each</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {d.template.yours.map((s) => (
              <Link key={s.player_id} to={`/player/${s.player_id}`} className={`border-2 px-2 py-0.5 text-[12.5px] font-bold ${(s.share ?? 0) < 0.15 ? 'border-spot bg-spot text-ink' : 'border-ink bg-paper text-text'}`}>
                {s.name} <span className="tabular font-display">{Math.round((s.share ?? 0) * 100)}%</span>
              </Link>
            ))}
          </div>
          <div className="mt-1.5 text-[11.5px] text-text-faint">Orange: a differential, owned by fewer than 15% of them.</div>
        </div>
      </section>
      <p className="px-10 py-5 text-[11.5px] text-text-faint">
        The cohort is the managers ranked around 10,000 now, chosen by how their season went, so their numbers include their luck. Multipliers are the picks as locked, before automatic substitutions, on both sides; FPL's substitutions are the separate line in the gap.
      </p>
    </div>
  )
}
