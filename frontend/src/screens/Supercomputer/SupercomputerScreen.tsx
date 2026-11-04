import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Info } from '@/components/ui/Info'
import { Masthead } from '@/components/shell/Masthead'
import { ScreenError, Skel } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { crestUrl, getJson } from '@/lib/api'
import { clubColors } from '@/lib/clubs'
import { useFetch } from '@/lib/useFetch'

/** THE SUPERCOMPUTER: the rest of the season played 20,000 times (`models/supercomputer.py`). Who wins it, who goes down,
 * where every club finishes, the Golden Boot, and which clubs have the goals and clean sheets still to come for FPL. */
interface Row {
  team_id: number; name: string; short: string; code: number; played: number; points: number; gd: number; expected_points: number; p10: number; p90: number
  title: number; top4: number; top5: number; down: number; positions: number[]; goals_left: number; sheets_left: number; goals_next: number; sheets_next: number
}
interface Scorer { player_id: number; name: string; photo_code: number | null; team_code: number; team_short: string; goals: number; expected_final: number; chance: number }
interface River { event: number; title: Record<string, number>; down: Record<string, number> }
interface Payload {
  status: string; simulations: number; fixtures_left: number; last_gameweek: number; next_gameweek: number | null; table: Row[]; golden_boot: Scorer[]; river: River[]
}

const pct = (v: number) => (v >= 0.995 ? '>99%' : v > 0 && v < 0.005 ? '<1%' : `${Math.round(v * 100)}%`)

function Crest({ code, className = 'size-7' }: { code: number; className?: string }) {
  const url = crestUrl(code)
  return url ? <img src={url} alt="" className={className} /> : null
}

function Contenders({ rows, field, label }: { rows: Row[]; field: 'title' | 'down'; label: string }) {
  const top = [...rows].sort((a, b) => b[field] - a[field]).slice(0, field === 'title' ? 4 : 6)
  return (
    <div>
      <div className="font-display text-2xl font-black uppercase text-text">{label}</div>
      <div className="mt-3 space-y-2">
        {top.map((r) => (
          <div key={r.team_id} className="grid grid-cols-[2.25rem_3.25rem_minmax(0,1fr)_4.5rem] items-center gap-3">
            <Crest code={r.code} className="size-9" />
            <span className="font-display text-xl font-black uppercase text-text">{r.short}</span>
            <span className="h-7 border-2 border-ink bg-paper"><span className="block h-full transition-all duration-700" style={{ width: `${r[field] * 100}%`, background: clubColors(r.code).primary }} /></span>
            <span className="tabular text-right font-display text-3xl font-black text-text">{pct(r[field])}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function RiverChart({ river, rows, field }: { river: River[]; rows: Row[]; field: 'title' | 'down' }) {
  const clubs = useMemo(() => [...rows].sort((a, b) => b[field] - a[field]).slice(0, 4), [rows, field])
  if (river.length < 2) return null
  const W = 640, H = 220, L = 34, B = 22, T = 10, R = 54
  const x = (i: number) => L + (i * (W - L - R)) / (river.length - 1)
  const y = (v: number) => T + (1 - v) * (H - T - B)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${field === 'title' ? 'Title' : 'Relegation'} chances after each gameweek`}>
      {[0, 0.25, 0.5, 0.75, 1].map((v) => (
        <g key={v}>
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--ink)" strokeOpacity={0.14} />
          <text x={L - 6} y={y(v) + 4} textAnchor="end" className="fill-[var(--ink)] text-[11px]" opacity={0.6}>{v * 100}</text>
        </g>
      ))}
      {river.map((r, i) => <text key={r.event} x={x(i)} y={H - 6} textAnchor="middle" className="fill-[var(--ink)] text-[11px]" opacity={0.6}>{r.event}</text>)}
      {clubs.map((c) => {
        const pts = river.map((r, i) => `${x(i)},${y(r[field][c.team_id] ?? 0)}`).join(' ')
        const last = river[river.length - 1][field][c.team_id] ?? 0
        return (
          <g key={c.team_id}>
            <polyline points={pts} fill="none" stroke={clubColors(c.code).primary} strokeWidth={3.5} strokeLinejoin="round" />
            <text x={x(river.length - 1) + 6} y={y(last) + 4} className="fill-[var(--ink)] text-[12px] font-bold">{c.short}</text>
          </g>
        )
      })}
    </svg>
  )
}

function Grid({ rows }: { rows: Row[] }) {
  const n = rows.length
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[12px]">
        <thead>
          <tr className="text-text-faint">
            <th className="sticky left-0 bg-paper text-left font-bold uppercase">Club</th>
            {Array.from({ length: n }, (_, i) => <th key={i} className={`w-[3.4%] px-0 text-center font-bold ${i === 4 || i === 17 ? 'border-l-2 border-ink' : ''}`}>{i + 1}</th>)}
            <th className="pl-3 text-right font-bold uppercase">Points</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.team_id}>
              <td className="sticky left-0 bg-paper py-px pr-2"><span className="flex items-center gap-1.5 font-display text-[14px] font-black uppercase text-text"><Crest code={r.code} className="size-5" />{r.short}</span></td>
              {r.positions.map((p, i) => (
                <td key={i} title={`${r.name}: ${pct(p)} to finish ${i + 1}`} className={`h-7 text-center tabular text-[11px] font-bold ${i === 4 || i === 17 ? 'border-l-2 border-ink' : ''}`}
                  style={{ background: p >= 0.005 ? `color-mix(in srgb, var(--spot) ${Math.min(100, Math.round(p * 280))}%, transparent)` : undefined, color: p >= 0.25 ? 'var(--ink)' : undefined }}>
                  {p >= 0.05 ? Math.round(p * 100) : ''}
                </td>
              ))}
              <td className="whitespace-nowrap pl-3 text-right">
                <span className="tabular font-display text-[17px] font-black text-text">{Math.round(r.expected_points)}</span>
                <span className="tabular ml-1.5 text-[11px] text-text-faint">{r.p10}–{r.p90}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Boot({ rows }: { rows: Scorer[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {rows.slice(0, 4).map((s) => (
        <Link key={s.player_id} to={`/player/${s.player_id}`} className="flex items-center gap-3 border-2 border-ink bg-paper p-3 shadow-[4px_4px_0_var(--ink)] hover:-translate-y-px">
          <PlayerPhoto code={s.photo_code} teamCode={s.team_code} className="h-20 w-16" />
          <div className="min-w-0">
            <div className="truncate font-display text-lg font-black uppercase text-text">{s.name}</div>
            <div className="tabular font-display text-4xl font-black leading-none text-spot">{pct(s.chance)}</div>
            <div className="tabular mt-1 text-[12px] font-bold text-text-muted">{s.goals} now · {s.expected_final.toFixed(0)} expected</div>
          </div>
        </Link>
      ))}
    </div>
  )
}

function Runs({ rows, next }: { rows: Row[]; next: number | null }) {
  const [span, setSpan] = useState<'next' | 'left'>('next')
  const goals = span === 'next' ? 'goals_next' : 'goals_left'
  const sheets = span === 'next' ? 'sheets_next' : 'sheets_left'
  const list = (field: typeof goals | typeof sheets, label: string) => {
    const top = [...rows].sort((a, b) => b[field] - a[field]).slice(0, 6)
    const max = top[0]?.[field] || 1
    return (
      <div>
        <div className="mb-2 font-display text-[15px] font-black uppercase text-text">{label}</div>
        <div className="space-y-1.5">
          {top.map((r) => (
            <div key={r.team_id} className="grid grid-cols-[1.5rem_3rem_minmax(0,1fr)_3rem] items-center gap-2">
              <Crest code={r.code} className="size-6" />
              <span className="font-display text-[15px] font-black uppercase text-text">{r.short}</span>
              <span className="h-3 bg-raised"><span className="block h-full" style={{ width: `${(r[field] / max) * 100}%`, background: clubColors(r.code).primary }} /></span>
              <span className="tabular text-right font-display text-lg font-black text-text">{r[field].toFixed(1)}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }
  return (
    <div>
      <div className="mb-3 flex gap-1.5">
        {([['next', next ? `GW${next}-${next + 5}` : 'Next six'], ['left', 'Rest of season']] as const).map(([k, l]) => (
          <button key={k} type="button" onClick={() => setSpan(k)} className={`border-2 border-ink px-2.5 py-0.5 font-display text-[13px] font-black uppercase ${span === k ? 'bg-ink text-paper' : 'bg-paper text-text'}`}>{l}</button>
        ))}
      </div>
      <div className="grid gap-8 md:grid-cols-2">
        {list(goals, 'Most goals coming')}
        {list(sheets, 'Most clean sheets coming')}
      </div>
    </div>
  )
}

export function SupercomputerScreen() {
  const state = useFetch(() => getJson<Payload>('/api/supercomputer'), [])
  if (state.status === 'loading') return <div className="space-y-4 p-6"><div className="font-display text-3xl font-black uppercase text-text">Playing the season 20,000 times…</div><Skel className="h-64 w-full" /></div>
  if (state.status === 'error') return <ScreenError title="The Supercomputer is unavailable" description="The season could not be simulated." message={state.error.message} />
  const d = state.data
  return (
    <div className="space-y-6 pb-10">
      <Masthead right={<span>{d.simulations.toLocaleString()} seasons · {d.fixtures_left} matches left · after GW{d.last_gameweek}</span>} />
      <section className="px-10 py-8">
        <div className="flex items-center gap-2">
          <h2 className="font-display text-text">The season, played {d.simulations.toLocaleString()} times</h2>
          <Info label="How this is worked out">
            Every match left is drawn from the same team ratings the projections use, and each simulated season gives every club a lasting shock to its attack and defence, because ratings drift. Restarted after 90 matches in five past seasons, it missed final points by 7.9 a club. No injuries, new managers or January signings, apart from what that shock stands in for. Golden Boot shares come from each player&apos;s current projection and assume his role holds.
          </Info>
        </div>
        <div className="mt-5 grid gap-10 lg:grid-cols-2">
          <Contenders rows={d.table} field="title" label="Champions" />
          <Contenders rows={d.table} field="down" label="Relegated" />
        </div>
      </section>
      <section className="px-10 py-8">
        <h2 className="font-display text-text">Where every club finishes</h2>
        <div className="mt-4"><Grid rows={d.table} /></div>
      </section>
      <section className="px-10 py-8">
        <div className="grid gap-10 lg:grid-cols-2">
          <div><h2 className="font-display text-text">Title race, by gameweek</h2><RiverChart river={d.river} rows={d.table} field="title" /></div>
          <div><h2 className="font-display text-text">Relegation, by gameweek</h2><RiverChart river={d.river} rows={d.table} field="down" /></div>
        </div>
      </section>
      <section className="px-10 py-8">
        <h2 className="mb-4 font-display text-text">Golden Boot</h2>
        <Boot rows={d.golden_boot} />
      </section>
      <section className="px-10 py-8">
        <h2 className="mb-4 font-display text-text">Where the FPL points are</h2>
        <Runs rows={d.table} next={d.next_gameweek} />
      </section>
    </div>
  )
}
