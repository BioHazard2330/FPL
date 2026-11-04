import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { crestUrl, getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** PLAY BY PLAY: the Live Pitch (FotMob's animated tracker, embedded from FotMob's own page while a covered match is on)
 * above FotMob's ticker (the Premier League's commentary where FotMob has none) as a timeline. Goals are slabs,
 * cards, substitutions and VAR carry a mark, your players and the plan's targets are picked out, new lines slide in.
 * Refreshes every 15 seconds while the match is on. */
interface Who { name: string; player_id?: number; web_name?: string; mine?: boolean; target?: boolean; captain?: boolean; photo_code?: number | null }
interface Row { id: string; kind: string; minute: number | null; stoppage: number | null; side: 'home' | 'away' | null; text: string; key: boolean; players: Who[]; score?: [number, number] }
interface Team { short: string; code: number | null }
export interface MatchHead { fotmob_id: string; fixture: number | null; status: string; score: [number | null, number | null]; minute: number | string | null; home: Team; away: Team; mine?: number; competition?: string }
interface Payload {
  status: string; source?: 'fotmob' | 'premier_league'; match?: MatchHead; live?: boolean; events?: Row[]; team_news?: string[]
  reports?: { half_time?: string; full_time?: string }; pitch_url?: string | null
}

const MARK: Record<string, { label: string; tone: string }> = {
  yellow: { label: 'YC', tone: 'bg-[#ffd400] text-ink' },
  red: { label: 'RED', tone: 'bg-alert-red text-alert-red-ink' },
  sub: { label: 'SUB', tone: 'bg-broadcast-blue text-paper' },
  var: { label: 'VAR', tone: 'bg-ink text-paper' },
  assist: { label: 'ASSIST', tone: 'bg-pitch-green text-paper' },
  chance: { label: 'CHANCE', tone: 'bg-raised text-text' },
  penalty_missed: { label: 'PEN MISS', tone: 'bg-alert-red text-alert-red-ink' },
  penalty_saved: { label: 'PEN SAVED', tone: 'bg-pitch-green text-paper' },
  injury: { label: 'INJURY', tone: 'bg-alert-red text-alert-red-ink' },
}
const clock = (r: Row) => (r.minute === null ? '' : `${r.minute}${r.stoppage ? `+${r.stoppage}` : ''}'`)
const isGoal = (r: Row) => r.kind === 'goal' || r.kind === 'own_goal'
const flagged = (r: Row) => r.players.some((p) => p.mine || p.target)

function Tag({ p }: { p: Who }) {
  const label = p.web_name ?? p.name
  const tone = p.mine ? 'bg-spot text-ink' : p.target ? 'bg-broadcast-gold text-ink' : 'bg-raised text-text-muted'
  const inner = <span className={`inline-block px-1.5 font-display text-[12px] font-black uppercase ${tone}`}>{label}{p.captain ? ' ©' : ''}</span>
  return p.player_id ? <Link to={`/player/${p.player_id}`}>{inner}</Link> : inner
}

function GoalRow({ r, head }: { r: Row; head: MatchHead }) {
  const scorer = r.players[0]
  const team = r.side === 'home' ? head.home : r.side === 'away' ? head.away : null
  return (
    <li className="pbp-row pbp-goal relative my-2 grid grid-cols-[3.6rem_3.4rem_minmax(0,1fr)_auto] items-center gap-3 bg-ink px-4 py-3 text-paper shadow-[5px_5px_0_var(--spot)]">
      <span className="tabular font-display text-2xl font-black text-spot">{clock(r)}</span>
      <PlayerPhoto code={scorer?.photo_code ?? null} teamCode={team?.code ?? null} className="h-14 w-11" />
      <div className="min-w-0">
        <div className="font-display text-[1.5rem] font-black uppercase leading-none">
          {r.kind === 'own_goal' ? 'Own goal' : 'Goal'} · {scorer?.web_name ?? scorer?.name ?? ''}{scorer?.mine ? ' ★' : ''}
        </div>
        <p className="mt-1 text-[13px] leading-snug text-paper/75">{r.text}</p>
      </div>
      {r.score && <span className="tabular font-display text-[2.2rem] font-black leading-none">{r.score[0]}–{r.score[1]}</span>}
    </li>
  )
}

function LineRow({ r, head }: { r: Row; head: MatchHead }) {
  const m = MARK[r.kind]
  const team = r.side === 'home' ? head.home : r.side === 'away' ? head.away : null
  const crest = team?.code ? crestUrl(team.code) : null
  return (
    <li className={`pbp-row grid grid-cols-[3.6rem_1.5rem_minmax(0,1fr)] items-start gap-3 border-b border-divider/60 px-4 py-2 ${flagged(r) ? 'bg-spot/10' : ''}`}>
      <span className="tabular pt-0.5 font-display text-[15px] font-black text-text">{clock(r)}</span>
      <span className="pt-0.5">{crest && <img src={crest} alt={team?.short} className="h-5 w-5" />}</span>
      <div className="min-w-0">
        {(m || r.players.length > 0) && (
          <div className="mb-0.5 flex flex-wrap items-center gap-1.5">
            {m && <span className={`px-1.5 font-display text-[11px] font-black ${m.tone}`}>{m.label}</span>}
            {r.kind === 'sub' && r.players[0] ? (
              <><span className="font-black text-pitch-green">▲</span><Tag p={r.players[0]} />{r.players[1] && <><span className="font-black text-alert-red">▼</span><Tag p={r.players[1]} /></>}</>
            ) : r.players.map((p) => <Tag key={p.name} p={p} />)}
          </div>
        )}
        <p className={`text-[14px] leading-snug ${r.key ? 'text-text' : 'text-text-muted'}`}>{r.text}</p>
      </div>
    </li>
  )
}

/** FotMob's own animated pitch, embedded as it stands: ball, attack state and clock are drawn by their page. */
export function LivePitch({ url, className = '' }: { url: string; className?: string }) {
  return (
    <div className={`livepitch relative mb-4 overflow-hidden border-[3px] border-ink bg-ink shadow-[6px_6px_0_var(--spot)] ${className}`}>
      <iframe src={url} title="Live pitch" loading="lazy" referrerPolicy="no-referrer" sandbox="allow-scripts allow-same-origin" className="block aspect-[16/9] w-full border-0" />
    </div>
  )
}

function Report({ title, text }: { title: string; text: string }) {
  return (
    <details className="border-b border-divider px-4 py-2">
      <summary className="cursor-pointer font-display text-[13px] font-black uppercase tracking-[0.06em] text-text">{title}</summary>
      <p className="mt-1.5 text-[14px] leading-snug text-text-muted">{text}</p>
    </details>
  )
}

export function PlayByPlay({ fixtureId, fotmobId, live, bare = false }: { fixtureId?: number | null; fotmobId?: string; live: boolean; bare?: boolean }) {
  const query = fotmobId ? `match=${fotmobId}` : `fixture=${fixtureId}`
  const state = useFetch(() => getJson<Payload>(`/api/playbyplay?${query}`), [query], live ? 15000 : undefined)
  const [mode, setMode] = useState<'key' | 'all' | 'mine'>('key')
  const data = state.status === 'ready' ? state.data : null
  const rows = useMemo(() => [...(data?.events ?? [])].reverse(), [data])
  if (!data || data.status !== 'ok' || !data.match) return null
  const shown = mode === 'all' ? rows : mode === 'mine' ? rows.filter(flagged) : rows.filter((r) => r.key)
  const mine = rows.filter(flagged).length
  const modes: ['key' | 'all' | 'mine', string][] = [['key', 'Key'], ['all', `All ${rows.length}`], ['mine', `Mine ${mine}`]]
  return (
    <div className={bare ? '' : 'border-b border-divider px-10 py-8'}>
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
        <h2 className="font-display text-[1.75rem] font-black uppercase leading-none text-text">Play by play{data.live && <span className="pbp-live ml-3 inline-block bg-alert-red px-1.5 align-middle font-display text-[12px] text-paper">LIVE</span>}</h2>
        <div className="flex gap-1.5">
          {modes.map(([k, label]) => (
            <button key={k} type="button" onClick={() => setMode(k)} className={`border-2 border-ink px-2.5 py-0.5 font-display text-[13px] font-black uppercase ${mode === k ? 'bg-ink text-paper' : 'bg-paper text-text hover:bg-raised'}`}>{label}</button>
          ))}
        </div>
      </div>
      <div className={data.pitch_url ? 'grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]' : ''}>
      {data.pitch_url && <LivePitch url={data.pitch_url} className="!mb-0" />}
      <div className="border-2 border-ink bg-paper">
        {data.reports?.full_time && <Report title="Full-time report" text={data.reports.full_time} />}
        {data.reports?.half_time && <Report title="Half-time report" text={data.reports.half_time} />}
        <ol className={`overflow-y-auto ${data.pitch_url ? 'max-h-[26rem]' : 'max-h-[38rem]'}`}>
          {shown.map((r) => (isGoal(r) ? <GoalRow key={r.id} r={r} head={data.match!} /> : <LineRow key={r.id} r={r} head={data.match!} />))}
          {shown.length === 0 && <li className="px-4 py-6 text-[14px] text-text-muted">Nothing here yet.</li>}
        </ol>
        {(data.team_news ?? []).length > 0 && <Report title="Team news" text={(data.team_news ?? []).join(' ')} />}
      </div>
      </div>
      <div className="mt-1 text-right text-[10.5px] uppercase tracking-[0.1em] text-text-faint">{data.source === 'fotmob' ? 'FotMob' : 'Premier League'}</div>
    </div>
  )
}

/** The match picker for Live: anything in play first, otherwise the latest finished matches, yours marked. */
export function LivePlayByPlay() {
  const list = useFetch(() => getJson<{ status: string; matches: MatchHead[] }>('/api/playbyplay'), [], 60000)
  const [picked, setPicked] = useState<string | null>(null)
  const matches = list.status === 'ready' ? list.data.matches ?? [] : []
  if (!matches.length) return null
  const first = matches.find((m) => m.status !== 'FULL_TIME') ?? matches.find((m) => (m.mine ?? 0) > 0) ?? matches[0]
  const current = matches.find((m) => m.fotmob_id === picked) ?? first
  return (
    <section className="px-10 py-6">
      <div className="mb-4 flex gap-2 overflow-x-auto pb-1">
        {matches.map((m) => {
          const on = m.fotmob_id === current.fotmob_id
          const live = m.status !== 'FULL_TIME'
          return (
            <button key={m.fotmob_id} type="button" onClick={() => setPicked(m.fotmob_id)}
              className={`shrink-0 border-2 border-ink px-2.5 py-1 text-left ${on ? 'bg-ink text-paper shadow-[3px_3px_0_var(--spot)]' : 'bg-paper text-text hover:bg-raised'}`}>
              <span className="tabular font-display text-[15px] font-black">{m.home.short} {m.score[0] ?? 0}–{m.score[1] ?? 0} {m.away.short}</span>
              <span className={`ml-2 text-[10.5px] font-bold uppercase ${live ? 'text-alert-red' : 'opacity-60'}`}>{live ? (m.minute ? `${m.minute}'` : 'live') : 'FT'}{m.competition ? ` · ${m.competition}` : ''}</span>
              {(m.mine ?? 0) > 0 && <span className="ml-1.5 bg-spot px-1 font-display text-[11px] font-black text-ink">{m.mine}</span>}
            </button>
          )
        })}
      </div>
      <PlayByPlay key={current.fotmob_id} fotmobId={current.fotmob_id} live={current.status !== 'FULL_TIME'} bare />
    </section>
  )
}

/** The Live Pitch alone, for Matchday TV. */
export function PitchFor({ fotmobId, className = '' }: { fotmobId: string; className?: string }) {
  const state = useFetch(() => getJson<Payload>(`/api/playbyplay?match=${fotmobId}`), [fotmobId], 30000)
  const url = state.status === 'ready' ? state.data.pitch_url : null
  return url ? <LivePitch key={url} url={url} className={className} /> : null
}
