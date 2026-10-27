import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDown, ArrowUp, ExternalLink, Minus } from 'lucide-react'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, ScreenError } from '@/components/shell/ScreenStates'
import { Face } from '@/components/ui/Face'
import { chipName, Panel, Pill } from '@/components/ui/kit'
import { fetchLeagues } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { LeaguePlayer, LeagueStanding, LeaguesPayload, MiniLeague } from '@/lib/types'

/** MINI-LEAGUES - the people you are actually playing against.
 *
 * Standings and rivals' teams come from FPL's public endpoints (`ingestion/leagues.py`). A rival's team is the one he locked
 * for the last gameweek, because FPL hides picks until the deadline, so every projection for him is "if he keeps last
 * week's eleven"; yours is the plan's eleven after its moves. Both use the same projections, the armband counted twice.
 * That makes the swing generous to you until his new team locks, which the page says where the number is shown. */

const ordinal = (n: number) => {
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`
}
const signed = (v: number, d = 0) => `${v > 0 ? '+' : ''}${v.toFixed(d)}`

function Movement({ rank, last }: { rank: number; last: number | null }) {
  if (!last || last === rank) return <Minus className="size-3.5 text-text-faint" aria-label="no change" />
  const up = rank < last
  return (
    <span className={`inline-flex items-center gap-0.5 text-[12px] font-semibold tabular-nums ${up ? 'text-pitch-green' : 'text-alert-red'}`}>
      {up ? <ArrowUp className="size-3.5" /> : <ArrowDown className="size-3.5" />}
      {Math.abs(last - rank)}
    </span>
  )
}

function LeagueSwitcher({ leagues, active, onPick }: { leagues: MiniLeague[]; active: number; onPick: (id: number) => void }) {
  return (
    <div className="flex flex-wrap gap-3">
      {leagues.map((l) => {
        const on = l.id === active
        return (
          <button
            key={l.id}
            type="button"
            onClick={() => onPick(l.id)}
            className={`min-w-[12rem] rounded-xl border px-4 py-3 text-left transition-colors ${
              on ? 'border-pitch-green/60 bg-pitch-green/10' : 'border-divider bg-panel hover:border-text-faint/40'
            }`}
          >
            <div className="truncate text-[13px] font-semibold text-text-muted">{l.name}</div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="font-display text-3xl font-bold leading-none text-text tabular-nums">{l.my_rank ? ordinal(l.my_rank) : '–'}</span>
              <span className="text-[13px] text-text-faint">of {l.size}</span>
              {l.my_rank && <Movement rank={l.my_rank} last={l.my_last_rank} />}
            </div>
          </button>
        )
      })}
    </div>
  )
}

function Hero({ league, me }: { league: MiniLeague; me: LeagueStanding }) {
  const rows = league.standings
  const above = rows.filter((r) => !r.me && r.rank < me.rank).sort((a, b) => b.rank - a.rank)[0]
  const below = rows.filter((r) => !r.me && r.rank > me.rank).sort((a, b) => a.rank - b.rank)[0]
  const leader = rows.find((r) => r.rank === 1 && !r.me)
  const followed = rows.filter((r) => !r.me && r.swing !== null)
  const wins = followed.filter((r) => (r.swing ?? 0) > 0).length
  return (
    <section className="grid gap-px overflow-hidden rounded-xl border border-divider bg-divider md:grid-cols-[1.2fr_1fr_1fr_1fr]">
      <div className="bg-panel px-6 py-5">
        <div className="text-[13px] font-semibold text-text-faint">{league.name}</div>
        <div className="mt-1 flex items-baseline gap-3">
          <span className="font-display text-7xl font-bold leading-none text-text tabular-nums">{ordinal(me.rank)}</span>
          <span className="text-lg text-text-muted">of {league.size}</span>
        </div>
        <div className="mt-2 text-[14px] text-text-muted">
          {me.total} points · {me.gw_points ?? '–'} last gameweek
        </div>
      </div>
      <HeroFig
        label={leader ? `Behind the leader` : 'You lead'}
        value={leader ? `${Math.abs(leader.total - me.total)}` : `${below ? me.total - below.total : 0}`}
        tone={leader ? 'text-alert-red' : 'text-pitch-green'}
        sub={leader ? `${leader.team} · ${leader.manager}` : below ? `ahead of ${below.team}` : ''}
      />
      <HeroFig
        label={above ? 'To the place above' : 'Cushion below'}
        value={above ? `${above.total - me.total}` : below ? `${me.total - below.total}` : '–'}
        tone="text-text"
        sub={above ? `${above.team}${below ? ` · ${me.total - below.total} clear of ${below.team}` : ''}` : below ? below.team : ''}
      />
      <HeroFig
        label="Next gameweek, projected"
        value={`${wins}/${followed.length}`}
        tone={wins >= followed.length / 2 ? 'text-pitch-green' : 'text-broadcast-gold'}
        sub="rivals you outscore if they keep last week's eleven"
      />
    </section>
  )
}

function HeroFig({ label, value, sub, tone }: { label: string; value: string; sub: string; tone: string }) {
  return (
    <div className="bg-panel px-6 py-5">
      <div className="text-[13px] font-semibold text-text-faint">{label}</div>
      <div className={`mt-2 font-display text-5xl font-bold leading-none tabular-nums ${tone}`}>{value}</div>
      <div className="mt-2 truncate text-[13px] text-text-muted">{sub}</div>
    </div>
  )
}

function SwingBar({ swing, max }: { swing: number | null; max: number }) {
  if (swing === null) return <span className="text-[12px] text-text-faint">not followed</span>
  const w = Math.min(Math.abs(swing) / max, 1) * 50
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 w-28 rounded-full bg-raised">
        <div className="absolute inset-y-0 left-1/2 w-px bg-text-faint/50" />
        <div
          className={`bar-draw absolute inset-y-0 rounded-full ${swing >= 0 ? 'bg-pitch-green' : 'bg-alert-red'}`}
          style={swing >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }}
        />
      </div>
      <span className={`w-10 text-right text-[13px] font-semibold tabular-nums ${swing >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(swing, 1)}</span>
    </div>
  )
}

function OverlapRing({ value }: { value: number | null }) {
  if (value === null) return <span className="text-text-faint">–</span>
  const r = 9
  const c = 2 * Math.PI * r
  return (
    <span className="inline-flex items-center gap-1.5" title={`${Math.round(value * 11)} of your eleven also start for him`}>
      <svg viewBox="0 0 24 24" className="size-6 -rotate-90">
        <circle cx="12" cy="12" r={r} fill="none" stroke="var(--raised)" strokeWidth="4" />
        <circle cx="12" cy="12" r={r} fill="none" stroke="var(--broadcast-blue)" strokeWidth="4" strokeDasharray={`${c * value} ${c}`} strokeLinecap="round" />
      </svg>
      <span className="text-[13px] tabular-nums text-text-muted">{Math.round(value * 11)}/11</span>
    </span>
  )
}

function Standings({ league, picked, onPick }: { league: MiniLeague; picked: number | null; onPick: (id: number) => void }) {
  const max = Math.max(4, ...league.standings.map((r) => Math.abs(r.swing ?? 0)))
  const maxGw = Math.max(1, ...league.standings.map((r) => r.gw_points ?? 0))
  return (
    <Panel
      title="The table"
      sub={league.partial ? `Top of the league and the managers around you; ${league.size} in all.` : 'Click a rival for the head-to-head.'}
      right={
        <a href={league.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-text-muted hover:text-text">
          Open in FPL <ExternalLink className="size-3.5" />
        </a>
      }
      flush
    >
      <div className="grid grid-cols-[3.5rem_minmax(0,1.6fr)_4rem_4rem_6rem_minmax(0,1fr)_4.5rem_10rem_4.5rem] gap-3 border-y border-divider px-6 py-2 text-[12px] text-text-faint">
        <span>Rank</span>
        <span>Team</span>
        <span className="text-right">Total</span>
        <span className="text-right">Gap</span>
        <span>Last GW</span>
        <span>Armband</span>
        <span className="text-right">Next GW</span>
        <span>Against you</span>
        <span>Shared</span>
      </div>
      {league.standings.map((r) => {
        const cap = r.captain ? league.players[String(r.captain)] : undefined
        const active = picked === r.entry_id
        return (
          <button
            key={r.entry_id}
            type="button"
            disabled={r.me || !r.followed}
            onClick={() => onPick(r.entry_id)}
            className={`grid w-full grid-cols-[3.5rem_minmax(0,1.6fr)_4rem_4rem_6rem_minmax(0,1fr)_4.5rem_10rem_4.5rem] items-center gap-3 border-b border-divider px-6 py-2.5 text-left text-sm transition-colors ${
              r.me ? 'bg-pitch-green/10 shadow-[inset_3px_0_0_var(--pitch-green)]' : active ? 'bg-raised' : r.followed ? 'hover:bg-raised/60' : 'opacity-70'
            }`}
          >
            <span className="flex items-center gap-1.5">
              <span className="w-6 font-display text-lg font-bold tabular-nums text-text">{r.rank}</span>
              <Movement rank={r.rank} last={r.last_rank} />
            </span>
            <span className="min-w-0">
              <span className="block truncate font-semibold text-text">{r.team}</span>
              <span className="block truncate text-[12px] text-text-faint">{r.manager}</span>
            </span>
            <span className="text-right font-semibold tabular-nums text-text">{r.total}</span>
            <span className={`text-right tabular-nums ${r.me ? 'text-text-faint' : (r.gap ?? 0) > 0 ? 'text-alert-red' : 'text-pitch-green'}`}>
              {r.me ? '–' : signed(r.gap ?? 0)}
            </span>
            <span className="flex items-center gap-2">
              <span className="h-1.5 w-12 rounded-full bg-raised">
                <span className="bar-draw block h-full rounded-full bg-text-faint/70" style={{ width: `${((r.gw_points ?? 0) / maxGw) * 100}%` }} />
              </span>
              <span className="tabular-nums text-text-muted">{r.gw_points ?? '–'}</span>
              {r.chip && <Pill tone="gold">{chipName(r.chip)}</Pill>}
              {!!r.hits && <span className="text-[12px] text-alert-red">−{r.hits}</span>}
            </span>
            <span className="flex min-w-0 items-center gap-2">
              {cap ? (
                <>
                  <Face code={cap.photo_code} teamCode={cap.team_code} size="sm" isGkp={cap.position === 'GKP'} />
                  <span className="truncate text-[13px] text-text-muted">{cap.name}</span>
                </>
              ) : (
                <span className="text-text-faint">{r.captain_name ?? '–'}</span>
              )}
            </span>
            <span className="text-right font-semibold tabular-nums text-text">{r.projected?.toFixed(1) ?? '–'}</span>
            <span>{r.me ? <span className="text-[12px] text-pitch-green">you, after the plan</span> : <SwingBar swing={r.swing} max={max} />}</span>
            <span>{r.me ? null : <OverlapRing value={r.overlap} />}</span>
          </button>
        )
      })}
    </Panel>
  )
}

function FaceTile({ p, note }: { p: LeaguePlayer; note?: React.ReactNode }) {
  return (
    <Link to={`/player/${p.player_id}`} className="group flex w-[6.5rem] flex-col items-center gap-2 text-center">
      <Face code={p.photo_code} teamCode={p.team_code} size="lg" isGkp={p.position === 'GKP'} />
      <div className="min-w-0">
        <div className="truncate text-[13px] font-semibold text-text group-hover:underline">{p.name}</div>
        <div className="text-[12px] tabular-nums text-text-faint">
          {p.team} · {p.xp.toFixed(1)} xP
        </div>
        {note && <div className="mt-0.5 text-[12px] text-text-muted">{note}</div>}
      </div>
    </Link>
  )
}

function HeadToHead({ league, rival, myXi, locked }: { league: MiniLeague; rival: LeagueStanding; myXi: number[]; locked: number | null | undefined }) {
  const theirs = new Set(rival.xi)
  const mine = new Set(myXi)
  const only = (ids: number[], other: Set<number>) =>
    ids.filter((p) => !other.has(p)).map((p) => league.players[String(p)]).filter(Boolean).sort((a, b) => b.xp - a.xp)
  const onlyThem = only(rival.xi, mine)
  const onlyMe = only(myXi, theirs)
  const both = rival.xi.filter((p) => mine.has(p)).map((p) => league.players[String(p)]).filter(Boolean)
  const sum = (ps: LeaguePlayer[]) => ps.reduce((s, p) => s + p.xp, 0)
  const cap = rival.captain ? league.players[String(rival.captain)] : undefined
  return (
    <Panel
      title={`You against ${rival.team}`}
      sub={`${rival.manager}. His GW${locked ?? ''} eleven against your plan's: where the next gameweek is decided is the players only one of you starts.`}
      right={
        <a href={rival.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-text-muted hover:text-text">
          His team in FPL <ExternalLink className="size-3.5" />
        </a>
      }
    >
      <div className="grid gap-6 lg:grid-cols-[1fr_auto_1fr]">
        <div>
          <div className="mb-3 flex items-baseline justify-between">
            <span className="text-[13px] font-semibold text-text-muted">Only you start</span>
            <span className="font-display text-2xl font-bold tabular-nums text-pitch-green">{sum(onlyMe).toFixed(1)}</span>
          </div>
          <div className="flex flex-wrap gap-3">{onlyMe.map((p) => <FaceTile key={p.player_id} p={p} />)}</div>
        </div>
        <div className="flex flex-col items-center justify-center gap-2 border-y border-divider px-6 py-4 lg:border-x lg:border-y-0">
          <span className="text-[12px] text-text-faint">Both start</span>
          <span className="font-display text-5xl font-bold tabular-nums text-text">{both.length}</span>
          <div className="flex max-w-[9rem] flex-wrap justify-center gap-1">
            {both.map((p) => (
              <span key={p.player_id} className="rounded bg-raised px-1.5 py-0.5 text-[11px] text-text-muted">{p.name}</span>
            ))}
          </div>
          {cap && (
            <div className="mt-2 text-center text-[12px] text-text-muted">
              His armband: <span className="font-semibold text-text">{cap.name}</span>
            </div>
          )}
        </div>
        <div>
          <div className="mb-3 flex items-baseline justify-between">
            <span className="text-[13px] font-semibold text-text-muted">Only he starts</span>
            <span className="font-display text-2xl font-bold tabular-nums text-alert-red">{sum(onlyThem).toFixed(1)}</span>
          </div>
          <div className="flex flex-wrap gap-3">{onlyThem.map((p) => <FaceTile key={p.player_id} p={p} />)}</div>
        </div>
      </div>
    </Panel>
  )
}

function Board({ title, sub, players, followed, kind }: { title: string; sub: string; players: LeaguePlayer[]; followed: number; kind: 'threat' | 'diff' }) {
  if (!players.length) return null
  return (
    <Panel title={title} sub={sub}>
      <div className="flex flex-wrap gap-5">
        {players.map((p) => (
          <FaceTile
            key={p.player_id}
            p={p}
            note={
              <span className="flex flex-col items-center gap-1">
                <span className="h-1 w-16 rounded-full bg-raised">
                  <span className={`block h-full rounded-full ${kind === 'threat' ? 'bg-alert-red' : 'bg-pitch-green'}`} style={{ width: `${(p.starts / Math.max(followed, 1)) * 100}%` }} />
                </span>
                <span>
                  {p.starts}/{followed} start{p.captains ? ` · ${p.captains} captain` : ''}
                </span>
              </span>
            }
          />
        ))}
      </div>
    </Panel>
  )
}

function Body({ d }: { d: LeaguesPayload }) {
  const [active, setActive] = useState<number>(() => d.leagues.find((l) => l.size <= 60 && l.my_rank)?.id ?? d.leagues[0]?.id)
  const league = d.leagues.find((l) => l.id === active) ?? d.leagues[0]
  const me = league?.standings.find((r) => r.me)
  const defaultRival = useMemo(() => {
    if (!league || !me) return null
    const rivals = league.standings.filter((r) => !r.me && r.followed)
    return (rivals.find((r) => r.rank === me.rank - 1) ?? rivals[0])?.entry_id ?? null
  }, [league, me])
  const [picked, setPicked] = useState<number | null>(defaultRival)
  useEffect(() => setPicked(defaultRival), [defaultRival])
  if (!league) return null
  const rival = league.standings.find((r) => r.entry_id === picked)

  return (
    <div className="space-y-6 px-10 pt-6">
      <LeagueSwitcher leagues={d.leagues} active={league.id} onPick={setActive} />
      {me && <Hero league={league} me={me} />}
      <Standings league={league} picked={picked} onPick={setPicked} />
      <p className="-mt-3 text-[13px] text-text-faint">
        Rivals' next gameweek is their GW{d.locked_event} eleven and armband unchanged (FPL hides their picks until the deadline); yours is the plan
        after its moves. The swing reads in your favour until their GW{d.next_event} teams lock.
      </p>
      {rival && me && <HeadToHead league={league} rival={rival} myXi={d.my_xi ?? []} locked={d.locked_event} />}
      <div className="grid gap-6 xl:grid-cols-2">
        <Board
          title="What could beat you"
          sub={`Players the ${league.followed} rivals followed here start and you will not own, ranked by how many start them times their next-gameweek points.`}
          players={league.threats}
          followed={league.followed}
          kind="threat"
        />
        <Board
          title="Where you can pull away"
          sub="Players in your eleven that at most a third of them start: their points are points the league does not get."
          players={league.differentials}
          followed={league.followed}
          kind="diff"
        />
      </div>
    </div>
  )
}

export function LeaguesScreen() {
  const state = useFetch(fetchLeagues, [], 120_000)
  return (
    <div className="data-in pb-16">
      <Masthead right={state.status === 'ready' && state.data.locked_event ? <span>Rivals' teams as locked for GW{state.data.locked_event}</span> : undefined} />
      {state.status === 'loading' && (
        <div className="animate-pulse space-y-6 px-10 py-6">
          <Skel className="h-20 w-full" />
          <Skel className="h-36 w-full" />
          <Skel className="h-96 w-full" />
        </div>
      )}
      {state.status === 'error' && <ScreenError title="Mini-leagues are unavailable" description="The stored league rows could not be read." message={state.error.message} />}
      {state.status === 'ready' && state.data.status === 'none' && (
        <p className="px-10 py-8 text-sm text-text-muted">
          No private leagues stored yet. Run <span className="font-mono">fpl sync-leagues</span>.
        </p>
      )}
      {state.status === 'ready' && state.data.status === 'ready' && <Body d={state.data} />}
    </div>
  )
}
