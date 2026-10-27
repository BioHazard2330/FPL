import { Link } from 'react-router-dom'
import { Face } from '@/components/ui/Face'
import { clubColors } from '@/lib/clubs'
import { FixtureRun } from '@/components/football/FixtureRun'
import { money } from '@/components/ui/kit'
import type { FixtureContext, MatchupBoardData, MatchupFixture, WeekPlanMove, WeekPlanPlayer } from '@/lib/types'
import { crestUrl } from '@/lib/api'
import { plain } from '@/lib/text'

type Note = { tone: 'red' | 'gold' | 'green' | 'plain'; text: string }

/** The few things worth knowing about one side of a transfer, each as a plain sentence with its number. Order is by how much
 * it should change the decision: availability first, then price, then what the recent matches say. */
function notes(p: WeekPlanPlayer, side: 'out' | 'into'): Note[] {
  const out: Note[] = []
  if (p.start_percent !== null && p.start_percent < 70) {
    out.push({ tone: p.start_percent < 40 ? 'red' : 'gold', text: `${p.start_percent}% to start, per the team-news feed` })
  }
  if (side === 'out' && p.price_trend === 'FALL_LIKELY') {
    out.push({ tone: 'red', text: `Price likely to fall tonight${p.price_p_fall != null ? ` (${Math.round(p.price_p_fall * 100)}%)` : ''}` })
  }
  if (side === 'into' && p.price_trend === 'RISE_LIKELY') {
    out.push({ tone: 'gold', text: `Price likely to rise tonight${p.price_p_rise != null ? ` (${Math.round(p.price_p_rise * 100)}%)` : ''}` })
  }
  if ((p.duties ?? []).length > 0) {
    out.push({ tone: side === 'out' ? 'gold' : 'green', text: `First choice on ${p.duties!.join(', ')}` })
  }
  if (p.form && p.form.label !== 'STEADY') {
    out.push({
      tone: p.form.label === 'HOT' ? 'green' : 'gold',
      text: `Last 3 matches ${p.form.recent_xgi90.toFixed(2)} xG+xA per 90, against ${p.form.before_xgi90.toFixed(2)} before`,
    })
  }
  if (p.luck && Math.abs(p.luck.z) >= 1.5) {
    out.push({
      tone: p.luck.z > 0 ? 'gold' : 'plain',
      text: p.luck.z > 0 ? `${p.luck.luck.toFixed(0)} points above what his chances were worth` : `${Math.abs(p.luck.luck).toFixed(0)} points below what his chances were worth`,
    })
  }
  if (side === 'into' && p.solio_next !== null && Math.abs(p.xp_next - p.solio_next) >= 1) {
    out.push({ tone: 'plain', text: `Solio projects ${p.solio_next.toFixed(1)} against our ${p.xp_next.toFixed(1)}` })
  }
  if (p.analyst && p.analyst.direction !== 'NEUTRAL') out.push({ tone: p.analyst.direction === 'NEGATIVE' ? 'red' : p.analyst.direction === 'POSITIVE' ? 'green' : 'plain', text: `${p.analyst.match}: ${plain(p.analyst.observed)}` })
  return out.slice(0, 4)
}

/** The scouting report in two lines: his profile, and the measures he ranks highest and lowest on among players in his
 * position, each with its value and percentile. */
function ScoutLine({ s }: { s: NonNullable<WeekPlanPlayer['scouting']> }) {
  const parts = [...s.strengths.map((m) => ({ m, good: true })), ...s.weaknesses.map((m) => ({ m, good: false }))]
  if (s.profile.length === 0 && parts.length === 0) return null
  return (
    <div className="mt-3 space-y-1.5" title={`Percentiles ${s.pool_note}`}>
      {s.profile.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {s.profile.map((t) => (
            <span key={t} className="rounded-full border border-pitch-green/35 bg-pitch-green/10 px-2 py-0.5 text-[11.5px] font-semibold text-pitch-green">
              {t}
            </span>
          ))}
        </div>
      )}
      {parts.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-text-muted">
          {parts.map(({ m, good }) => (
            <span key={m.key}>
              {m.label} <span className="font-semibold text-text">{m.display}</span>{' '}
              <span className={good ? 'text-pitch-green' : 'text-alert-red'}>{m.percentile}th</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

const INK = { red: 'text-alert-red', gold: 'text-broadcast-gold', green: 'text-pitch-green', plain: 'text-text-muted' }

function Side({ p, side, fixtures }: { p: WeekPlanPlayer; side: 'out' | 'into'; fixtures?: FixtureContext }) {
  const run = p.team_code !== null ? fixtures?.[String(p.team_code)] : undefined
  const ns = notes(p, side)
  return (
    <div className="min-w-0">
      <div className="mb-2 text-[13px] font-medium text-text-faint">{side === 'out' ? 'Sell' : 'Buy'}</div>
      <div className="flex items-center gap-3">
        <Face code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} size="md" muted={side === 'out'} />
        <div className="min-w-0">
          <Link to={`/player/${p.player_id}`} className={`block truncate font-display text-xl font-semibold leading-tight hover:text-pitch-green ${side === 'into' ? 'text-text' : 'text-text-muted'}`}>
            {p.name}
          </Link>
          <div className="tabular text-[13px] text-text-faint">
            {p.team_short} &middot; {p.position} &middot; {money(p.price_tenths)}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="tabular text-[13px] text-text-faint">
          <span className={`font-display text-2xl font-semibold leading-none ${side === 'into' ? 'text-pitch-green' : 'text-text-muted'}`}>{p.xp_next.toFixed(1)}</span> xP next GW
          <span className="text-text-faint"> &middot; {p.xp_horizon.toFixed(1)} over 5</span>
        </div>
        <FixtureRun fixtures={run} max={4} showEvent className="shrink-0 [&>span]:rounded-sm" />
      </div>
      {p.scouting && <ScoutLine s={p.scouting} />}
      {ns.length > 0 && (
        <ul className="mt-3 space-y-1.5 text-[13px] leading-snug">
          {ns.map((n) => (
            <li key={n.text} className={`border-l-2 pl-2.5 ${n.tone === 'red' ? 'border-alert-red' : n.tone === 'gold' ? 'border-broadcast-gold' : n.tone === 'green' ? 'border-pitch-green' : 'border-divider'} ${INK[n.tone]}`}>
              <span className="line-clamp-2" title={n.text}>{n.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Expected points gameweek by gameweek for both players, as paired bars with the incoming club's opponent underneath: where
 * the gain comes from (a soft run, a double, an away game that lands in week four), not just how much. */
function GwCompare({ m, fixtures, startEvent }: { m: WeekPlanMove; fixtures?: FixtureContext; startEvent: number }) {
  const out = m.out.xp_by_gw ?? []
  const inn = m.into.xp_by_gw ?? []
  if (out.length === 0 || inn.length === 0) return null
  const top = Math.max(...out, ...inn, 1)
  const run = m.into.team_code !== null ? fixtures?.[String(m.into.team_code)] : undefined
  const accent = clubColors(m.into.team_code).accent
  const H = 76
  return (
    <div className="mt-5 rounded-lg bg-void/40 px-4 pb-3 pt-3">
      <div className="mb-2 flex items-center justify-between text-[12px] text-text-faint">
        <span>Expected points by gameweek</span>
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1"><span className="size-2 rounded-sm bg-text-faint/50" />{m.out.name}</span>
          <span className="flex items-center gap-1"><span className="size-2 rounded-sm" style={{ background: accent }} />{m.into.name}</span>
        </span>
      </div>
      <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${inn.length}, minmax(0, 1fr))` }}>
        {inn.map((v, i) => {
          const f = run?.find((x) => x.event === startEvent + i)
          return (
            <div key={i} className="flex flex-col items-center">
              <div className="flex items-end gap-1" style={{ height: H }}>
                <div className="flex flex-col items-center justify-end">
                  <span className="tabular mb-0.5 text-[11px] text-text-faint">{(out[i] ?? 0).toFixed(1)}</span>
                  <div className="w-4 rounded-t-sm bg-text-faint/45" style={{ height: `${((out[i] ?? 0) / top) * (H - 16)}px` }} />
                </div>
                <div className="flex flex-col items-center justify-end">
                  <span className="tabular mb-0.5 text-[11px] font-semibold text-text">{v.toFixed(1)}</span>
                  <div className="w-4 rounded-t-sm" style={{ height: `${(v / top) * (H - 16)}px`, background: accent }} />
                </div>
              </div>
              <div className="mt-1.5 text-center text-[11px] leading-tight text-text-faint">
                <div className="font-semibold">GW{startEvent + i}</div>
                <div>{f ? `${f.opponent_short} ${f.is_home ? 'H' : 'A'}` : 'no game'}</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const DEFENSIVE = new Set(['GKP', 'DEF'])

function attackTone(xg: number) {
  if (xg >= 1.85) return 'bg-pitch-green/30 text-pitch-green'
  if (xg >= 1.55) return 'bg-pitch-green/15 text-pitch-green'
  if (xg >= 1.25) return 'bg-raised text-text'
  return 'bg-alert-red/15 text-alert-red'
}

function defenceTone(cs: number) {
  if (cs >= 0.4) return 'bg-pitch-green/30 text-pitch-green'
  if (cs >= 0.3) return 'bg-pitch-green/15 text-pitch-green'
  if (cs >= 0.2) return 'bg-raised text-text'
  return 'bg-alert-red/15 text-alert-red'
}

function leaky(xga: number, league: number) {
  if (xga >= league * 1.25) return { label: 'leaky', cls: 'text-pitch-green' }
  if (xga <= league * 0.8) return { label: 'tight', cls: 'text-alert-red' }
  return null
}

const TILT: Record<string, string> = { 'open play': 'open play', corners: 'corners', 'set pieces': 'set pieces', 'fast breaks': 'breaks', penalties: 'pens' }

/** Where his chances come from, weighted by how much this opponent concedes from each source against the league. Above 1
 * the opponent gives away the kind of chance he lives on; below 1 it shuts that kind out. A lens (Matchup Lab ratios), not
 * part of the projection. */
function styleFit(mix: Record<string, number> | null | undefined, concede: Record<string, number> | null | undefined) {
  if (!mix || !concede) return null
  let fit = 0
  let weight = 0
  for (const [source, share] of Object.entries(mix)) {
    if (concede[source] === undefined) continue
    fit += share * concede[source]
    weight += share
  }
  if (weight < 0.5) return null
  const value = fit / weight
  const main = Object.entries(mix).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k, v]) => `${Math.round(v * 100)}% ${k}`).join(', ')
  return { value, detail: `his chances: ${main}; this opponent concedes ${Object.entries(concede).map(([k, v]) => `${k} ×${v.toFixed(2)}`).join(', ')}` }
}

function MatchupCell({ f, defensive, league, mix }: { f: MatchupFixture; defensive: boolean; league: number; mix?: Record<string, number> | null }) {
  const fit = styleFit(mix, f.opp_concede)
  const opp = f.opponent_form
  const recent = opp ? (defensive ? opp.xg_for_recent : opp.xg_against_recent) : null
  const tag = opp && !defensive ? leaky(opp.xg_against_recent, league) : null
  const crest = crestUrl(f.opponent_code)
  return (
    <div
      className={`min-w-0 rounded-md px-1.5 py-1.5 ${defensive ? defenceTone(f.cs) : attackTone(f.xg_for)}`}
      title={`${f.opponent} ${f.home ? 'at home' : 'away'}: ${defensive ? `${Math.round(f.cs * 100)}% clean-sheet chance` : `${f.xg_for.toFixed(2)} team goals expected`}${
        recent !== null ? `; ${f.opponent} ${defensive ? 'create' : 'concede'} ${recent.toFixed(1)} xG a game over their last four` : ''
      }${f.tilt ? `; matchup tilts toward ${f.tilt.source}` : ''}`}
    >
      <div className="flex items-center gap-1">
        {crest && <img src={crest} alt="" className="size-3.5 shrink-0" />}
        <span className="truncate text-[11.5px] font-semibold text-text">{f.opponent}</span>
        <span className="text-[10.5px] text-text-faint">{f.home ? 'H' : 'A'}</span>
      </div>
      <div className="mt-0.5 font-display text-[17px] font-bold leading-none tabular-nums">{defensive ? `${Math.round(f.cs * 100)}%` : f.xg_for.toFixed(2)}</div>
      {recent !== null && (
        <div className="mt-1 truncate text-[10.5px] leading-tight text-text-muted">
          {recent.toFixed(1)} {defensive ? 'made' : 'let in'}
          {tag && <span className={`ml-1 font-semibold ${tag.cls}`}>{tag.label}</span>}
        </div>
      )}
      {f.tilt && <div className="truncate text-[10.5px] leading-tight text-broadcast-gold">+{TILT[f.tilt.source] ?? f.tilt.source}</div>}
      {fit && (fit.value >= 1.1 || fit.value <= 0.9) && (
        <div className={`truncate text-[10.5px] font-semibold leading-tight ${fit.value >= 1.1 ? 'text-pitch-green' : 'text-alert-red'}`} title={fit.detail}>
          {fit.value >= 1.1 ? 'suits him' : 'bad fit'} ×{fit.value.toFixed(1)}
        </div>
      )}
    </div>
  )
}

/** Both clubs' next fixtures side by side, read the way a football eye reads them: who they play, the team's expected goals
 * (or, for a defender or keeper, the clean-sheet chance) in that fixture, how many chances the opponent has let in or made
 * over its last four, and the kind of chance the matchup tilts toward. Green favours the player, red is against him. Two
 * players from one club share a row. */
function MatchupBoard({ m, board, startEvent, horizon }: { m: WeekPlanMove; board?: MatchupBoardData; startEvent: number; horizon: number }) {
  if (!board) return null
  const events = Array.from({ length: horizon }, (_, i) => startEvent + i)
  const sameClub = m.out.team_id === m.into.team_id
  const rows = (sameClub ? [m.into] : [m.out, m.into]).map((p) => ({ p, team: board.teams[String(p.team_id)] }))
  if (rows.some((r) => !r.team)) return null
  return (
    <div className="mt-5 rounded-lg bg-void/40 px-3 pb-3 pt-3">
      <div className="mb-2 text-[12px] text-text-faint">
        Fixture by fixture <span className="text-text-faint/80">· opponents over their last four · league average {board.league.xg_for.toFixed(2)} goals a team</span>
      </div>
      <div className="grid gap-1" style={{ gridTemplateColumns: `5.5rem repeat(${events.length}, minmax(0, 1fr))` }}>
        <div />
        {events.map((e) => (
          <div key={e} className="text-center text-[11px] font-semibold text-text-faint">
            GW{e}
          </div>
        ))}
        {rows.flatMap(({ p, team }) => {
          const defensive = DEFENSIVE.has(p.position)
          return [
            <div key={`${p.player_id}-h`} className="flex min-w-0 flex-col justify-center pr-1">
              <span className={`truncate text-[12.5px] font-semibold ${p === m.into ? 'text-text' : 'text-text-muted'}`}>
                {sameClub ? `${team!.short}, both` : p.name}
              </span>
              <span className="text-[10.5px] leading-tight text-text-faint">{defensive ? 'clean-sheet chance' : 'team goals expected'}</span>
            </div>,
            ...events.map((e) => {
              const fs = team!.fixtures.filter((f) => f.event === e)
              return (
                <div key={`${p.player_id}-${e}`} className="flex min-w-0 flex-col gap-1">
                  {fs.length === 0 ? (
                    <div className="flex h-full items-center justify-center rounded-md bg-alert-red/10 text-[11px] text-alert-red">blank</div>
                  ) : (
                    fs.map((f) => <MatchupCell key={`${f.opponent}-${f.home}`} f={f} defensive={defensive} league={board.league.xg_against} mix={p.scouting?.source_mix} />)
                  )}
                </div>
              )
            }),
          ]
        })}
      </div>
    </div>
  )
}

export function MoveCard({ m, horizon, fixtures, startEvent, board }: { m: WeekPlanMove; horizon: number; fixtures?: FixtureContext; startEvent: number; board?: MatchupBoardData }) {
  return (
    <div className="rounded-lg border border-divider bg-void/40 p-5">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Side p={m.out} side="out" fixtures={fixtures} />
        <Side p={m.into} side="into" fixtures={fixtures} />
      </div>
      <GwCompare m={m} fixtures={fixtures} startEvent={startEvent} />
      <MatchupBoard m={m} board={board} startEvent={startEvent} horizon={horizon} />
      <div className="mt-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-t border-divider pt-3 text-[13px] text-text-muted">
        <div className="min-w-0">
          {(m.alternatives ?? []).length > 0 ? (
            <>
              <span className="text-text-faint">If not {m.into.name}: </span>
              {m.alternatives!.map((a, i) => (
                <span key={a.into.player_id} className="tabular">
                  {i > 0 && ', '}
                  <span className="font-semibold text-text">{a.into.name}</span> ({money(a.into.price_tenths)}) <span className="text-pitch-green">+{a.gain.toFixed(1)}</span>
                </span>
              ))}
              <span className="text-text-faint"> over {horizon} GW</span>
            </>
          ) : (
            m.timing_note && <span>{m.timing_note}</span>
          )}
        </div>
        <Link to={`/compare?a=${m.out.player_id}&b=${m.into.player_id}`} className="shrink-0 font-medium text-text-faint hover:text-text">
          Compare them &rarr;
        </Link>
      </div>
      {m.timing && m.timing !== 'any' && m.timing_note && (m.alternatives ?? []).length > 0 && <p className="mt-2 text-[13px] text-broadcast-gold">{m.timing_note}</p>}
    </div>
  )
}
