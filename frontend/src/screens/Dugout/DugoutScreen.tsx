import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Info } from '@/components/ui/Info'
import { Masthead } from '@/components/shell/Masthead'
import { ScreenError, Skel } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { crestUrl, getJson } from '@/lib/api'
import { clubColors } from '@/lib/clubs'
import { useFetch } from '@/lib/useFetch'

/** THE DUGOUT: every club and its manager read from the season's matches (`models/dugout.py`) - style with and without the
 * ball, what the side does ahead and behind, when the manager changes it, how much he rotates, and whose minutes are safe. */
interface Label { text: string; tone: 'good' | 'bad' | 'neutral'; evidence: string }
interface State { minutes: number; for90: number | null; against90: number | null }
interface Club {
  team_id: number; name: string; short: string; code: number; manager: string | null; manager_change: { new: string; previous: string; matches: number } | null; played: number; points: number; gf: number; ga: number
  formation: string | null; formations: Record<string, number>; m: Record<string, number | null>; pct: Record<string, number | null>
  states: Record<string, State>; subs_per_match: number | null; labels: Label[]
}
interface Usage {
  player_id: number; name: string; team_id: number; position: string; photo_code?: number | null; starts: number; bench_apps: number; club_matches: number
  hooked_before_60: number; full_90: number; avg_start_minutes: number | null; typical_off: number | null; security: string
}
interface Payload { clubs: Club[]; usage?: Usage[]; squad_usage: Usage[]; min_state_minutes: number }

const TONE: Record<string, string> = { good: 'bg-pitch-green text-paper', bad: 'bg-alert-red text-paper', neutral: 'bg-paper text-ink' }
const SECURITY: Record<string, string> = { nailed: 'bg-pitch-green text-paper', regular: 'bg-spot text-ink', rotation: 'bg-alert-red text-paper', bench: 'bg-ink/20 text-ink', unused: 'bg-ink/10 text-ink/60' }

function Crest({ code, className = 'size-8' }: { code: number; className?: string }) {
  const url = crestUrl(code)
  return url ? <img src={url} alt="" className={className} /> : null
}

function StateBars({ states, color }: { states: Record<string, State>; color: string }) {
  const rows: [string, string][] = [['leading', 'Ahead'], ['level', 'Level'], ['trailing', 'Behind']]
  const max = 3
  return (
    <div className="space-y-1">
      {rows.map(([k, label]) => {
        const s = states[k]
        const f = s?.for90, a = s?.against90
        return (
          <div key={k} className="grid grid-cols-[3.4rem_minmax(0,1fr)_minmax(0,1fr)] items-center gap-1.5 text-[11.5px]" title={s ? `${s.minutes} minutes ${label.toLowerCase()}` : ''}>
            <span className="font-bold uppercase text-text/70">{label}</span>
            <span className="flex h-3.5 justify-end border border-ink/40 bg-paper">
              {f != null && <span className="h-full" style={{ width: `${Math.min(100, (f / max) * 100)}%`, background: color }} />}
            </span>
            <span className="flex h-3.5 border border-ink/40 bg-paper">
              {a != null && <span className="h-full bg-ink/55" style={{ width: `${Math.min(100, (a / max) * 100)}%` }} />}
            </span>
            {f == null && a == null ? null : null}
          </div>
        )
      })}
      <div className="grid grid-cols-[3.4rem_minmax(0,1fr)_minmax(0,1fr)] gap-1.5 text-[10.5px] uppercase text-text/55">
        <span />
        <span className="text-right">xG made /90</span>
        <span>xG given /90</span>
      </div>
    </div>
  )
}

function ClubCard({ c, open, onOpen }: { c: Club; open: boolean; onOpen: () => void }) {
  const col = clubColors(c.code).primary
  return (
    <button type="button" onClick={onOpen} className={`block w-full border-2 border-ink bg-paper p-4 text-left transition-transform hover:-translate-y-0.5 ${open ? 'shadow-[6px_6px_0_var(--spot)]' : 'shadow-[4px_4px_0_var(--ink)]'}`}>
      <div className="flex items-center gap-3">
        <Crest code={c.code} className="size-10" />
        <div className="min-w-0 flex-1">
          <div className="font-display text-2xl font-black uppercase leading-none text-text">{c.short}</div>
          <div className="truncate text-[13px] text-text/70">{c.manager ?? 'Manager unknown'} · {c.formation ?? '-'}</div>
        </div>
        <div className="text-right">
          <div className="tabular font-display text-2xl font-black text-text">{c.points}</div>
          <div className="tabular text-[11px] uppercase text-text/60">{c.gf}-{c.ga} in {c.played}</div>
        </div>
      </div>
      {c.manager_change && (
        <div className="mt-2 border-2 border-alert-red px-2 py-1 text-[12px] font-bold text-alert-red">
          New manager: {c.manager_change.new} after {c.manager_change.previous}, {c.manager_change.matches} league match{c.manager_change.matches === 1 ? '' : 'es'} in charge. These figures are mostly {c.manager_change.previous}&apos;s.
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-1">
        {c.labels.map((l) => (
          <span key={l.text} title={l.evidence} className={`border border-ink px-1.5 py-0.5 text-[11px] font-black uppercase ${TONE[l.tone]}`}>{l.text}</span>
        ))}
      </div>
      <div className="mt-3"><StateBars states={c.states} color={col} /></div>
      <div className="mt-3 grid grid-cols-3 gap-2 border-t border-ink/25 pt-2 text-center">
        <Stat label="First change" value={c.m.first_sub != null ? `${Math.round(c.m.first_sub)}'` : '-'} />
        <Stat label="XI changes" value={c.m.rotation != null ? c.m.rotation.toFixed(1) : '-'} />
        <Stat label="xG ± /match" value={c.m.xg_for != null && c.m.xg_against != null ? `${(c.m.xg_for - c.m.xg_against) >= 0 ? '+' : ''}${(c.m.xg_for - c.m.xg_against).toFixed(2)}` : '-'} />
      </div>
    </button>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="tabular font-display text-xl font-black text-text">{value}</div>
      <div className="text-[10.5px] font-bold uppercase tracking-wide text-text/60">{label}</div>
    </div>
  )
}

const MEASURES: [string, string, (v: number) => string][] = [
  ['possession', 'Possession', (v) => `${v.toFixed(0)}%`],
  ['xg_for', 'xG a match', (v) => v.toFixed(2)],
  ['xg_per_shot', 'xG a shot', (v) => v.toFixed(2)],
  ['big_chances', 'Big chances', (v) => v.toFixed(1)],
  ['box_touches', 'Box touches', (v) => v.toFixed(0)],
  ['corners', 'Corners', (v) => v.toFixed(1)],
  ['ball_winning', 'Tackles + interceptions', (v) => v.toFixed(0)],
  ['distance_km', 'Distance (km)', (v) => v.toFixed(1)],
  ['sprints', 'Sprints', (v) => v.toFixed(0)],
  ['xg_against', 'xG conceded', (v) => v.toFixed(2)],
  ['shots_against', 'Shots conceded', (v) => v.toFixed(1)],
  ['box_touches_against', 'Box touches conceded', (v) => v.toFixed(0)],
]

function Fingerprint({ c }: { c: Club }) {
  const col = clubColors(c.code).primary
  return (
    <div className="space-y-1.5">
      {MEASURES.map(([k, label, fmt]) => {
        const v = c.m[k], p = c.pct[k]
        if (v == null || p == null) return null
        const against = k.endsWith('against')
        return (
          <div key={k} className="grid grid-cols-[11rem_minmax(0,1fr)_4rem_2.6rem] items-center gap-2 text-[13px]">
            <span className="font-bold uppercase text-text/75">{label}</span>
            <span className="relative h-4 border-2 border-ink bg-paper">
              <span className="absolute inset-y-0 left-1/2 w-px bg-ink/40" />
              <span className="block h-full" style={{ width: `${p}%`, background: against ? 'var(--alert-red, #d33)' : col }} />
            </span>
            <span className="tabular text-right font-black text-text">{fmt(v)}</span>
            <span className="tabular text-right text-[11.5px] text-text/60">{p}</span>
          </div>
        )
      })}
      <div className="text-[11px] text-text/55">Bar and right figure: percentile among the 20 clubs, per match. For the conceded rows a long bar means more conceded.</div>
    </div>
  )
}

function UsageTable({ rows, clubs, showClub = false }: { rows: Usage[]; clubs: Record<number, Club>; showClub?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13.5px]">
        <thead>
          <tr className="border-b-2 border-ink text-left text-[11px] uppercase tracking-wide text-text/60">
            <th className="py-1.5">Player</th><th>Minutes</th><th className="text-right">Starts</th><th className="text-right">Off bench</th>
            <th className="text-right">Full 90</th><th className="text-right">Off before 60</th><th className="text-right">Usually off</th><th className="pl-3">Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.filter((u) => u.starts + u.bench_apps > 0).map((u) => (
            <tr key={u.player_id} className="border-b border-ink/15">
              <td className="py-1.5">
                <Link to={`/player/${u.player_id}`} className="flex items-center gap-2 hover:underline">
                  <PlayerPhoto code={u.photo_code ?? null} teamCode={clubs[u.team_id]?.code ?? null} isGkp={u.position === 'GKP'} className="h-8 w-7" bare />
                  <span className="font-display font-black uppercase text-text">{u.name}</span>
                  <span className="text-[11px] text-text/55">{u.position}{showClub && clubs[u.team_id] ? ` · ${clubs[u.team_id].short}` : ''}</span>
                </Link>
              </td>
              <td className="w-48">
                <span className="flex h-3 border border-ink/50 bg-paper" title={`${u.starts} of ${u.club_matches} started; ${u.avg_start_minutes ?? 0} minutes a start`}>
                  <span className="h-full bg-ink" style={{ width: `${(u.starts / Math.max(1, u.club_matches)) * ((u.avg_start_minutes ?? 0) / 90) * 100}%` }} />
                </span>
              </td>
              <td className="tabular text-right">{u.starts}/{u.club_matches}</td>
              <td className="tabular text-right">{u.bench_apps}</td>
              <td className="tabular text-right">{u.full_90}</td>
              <td className={`tabular text-right ${u.hooked_before_60 > 0 ? 'font-black text-alert-red' : ''}`}>{u.hooked_before_60}</td>
              <td className="tabular text-right">{u.typical_off != null ? `${u.typical_off}'` : '-'}</td>
              <td className="pl-3"><span className={`px-1.5 py-0.5 text-[11px] font-black uppercase ${SECURITY[u.security]}`}>{u.security}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function DugoutScreen() {
  const [team, setTeam] = useState<number | null>(null)
  const base = useFetch(() => getJson<Payload>('/api/dugout'), [])
  const detail = useFetch(() => (team ? getJson<Payload>(`/api/dugout?team=${team}`) : Promise.resolve(null)), [team])
  if (base.status === 'loading') return <div className="space-y-4 p-6"><div className="font-display text-3xl font-black uppercase text-text">Reading the dugouts…</div><Skel className="h-64 w-full" /></div>
  if (base.status === 'error') return <ScreenError title="The Dugout is unavailable" description="The season's matches could not be read." message={base.error.message} />
  const d = base.data
  const byId = Object.fromEntries(d.clubs.map((c) => [c.team_id, c]))
  const club = team ? byId[team] : null
  const usage = detail.status === 'ready' && detail.data ? detail.data.usage ?? [] : []
  const risky = d.squad_usage.filter((u) => u.security !== 'nailed')
  return (
    <div className="space-y-6 pb-10">
      <Masthead right={<span>{d.clubs.reduce((n, c) => n + c.played, 0) / 2} league matches read</span>} />
      <section className="px-10 pt-8">
        <div className="flex items-center gap-2">
          <h2 className="font-display text-text">The Dugout</h2>
          <Info label="How this is read">
            Every Premier League match at full time this season: FotMob&apos;s team figures for and against, the chances each side made and gave away while ahead, level and behind (a state needs {d.min_state_minutes}+ minutes before it is shown), every substitution and its minute, and who started. Labels mark the top or bottom quarter of the twenty clubs and show their number on hover. Ten matches is a small sample, so read styles as how a side has played, not what it will do. Display only: a club&apos;s rotation added nothing to a player&apos;s own minutes record when measured, so the projections read each player&apos;s own minutes.
          </Info>
        </div>
      </section>
      <section className="px-10">
        <div className="border-2 border-ink bg-ink p-5 text-paper shadow-[6px_6px_0_var(--spot)]">
          <div className="text-[12px] font-bold uppercase tracking-[0.14em] text-paper/60">Your fifteen under their managers</div>
          <div className="mt-1 font-display text-2xl font-black uppercase">
            {risky.length === 0 ? 'Every one nailed' : `${d.squad_usage.length - risky.length} nailed · ${risky.map((u) => `${u.name} (${u.security})`).join(' · ')}`}
          </div>
          <div className="mt-3 bg-paper p-3 text-ink"><UsageTable rows={d.squad_usage} clubs={byId} showClub /></div>
        </div>
      </section>
      <section className="px-10">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {d.clubs.map((c) => (
            <div key={c.team_id} className={team === c.team_id ? 'md:col-span-2 xl:col-span-4' : ''}>
              <ClubCard c={c} open={team === c.team_id} onOpen={() => setTeam(team === c.team_id ? null : c.team_id)} />
              {team === c.team_id && club && (
                <div className="mt-3 grid gap-6 border-2 border-ink bg-paper p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
                  <div>
                    <div className="mb-2 font-display text-xl font-black uppercase text-text">{club.name}&apos;s fingerprint</div>
                    <Fingerprint c={club} />
                    <div className="mt-3 text-[12.5px] text-text/75">
                      Shapes: {Object.entries(club.formations).map(([f, n]) => `${f} ×${n}`).join(', ') || '-'} · {club.subs_per_match ?? '-'} changes a match
                    </div>
                    <ul className="mt-2 space-y-0.5 text-[12.5px] text-text/80">
                      {club.labels.map((l) => <li key={l.text}><b className="uppercase">{l.text}:</b> {l.evidence}</li>)}
                    </ul>
                  </div>
                  <div>
                    <div className="mb-2 font-display text-xl font-black uppercase text-text">Whose minutes are safe under {club.manager ?? 'the manager'}</div>
                    {detail.status === 'loading' ? <Skel className="h-40 w-full" /> : <UsageTable rows={usage} clubs={byId} />}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
