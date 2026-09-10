import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, SkelTable, ScreenError } from '@/components/shell/ScreenStates'
import { crestUrl, fetchMatchweekPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { Podium3D } from '@/components/three/Podium3D'
import type { LeaderRow, LeagueTableRow, MatchweekBlock, MatchweekFixture } from '@/lib/types'

const FORM_FILL: Record<string, string> = {
  W: 'bg-pitch-green text-pitch-green-ink',
  D: 'bg-raised text-text-muted',
  L: 'bg-alert-red text-alert-red-ink',
}

/** Real form guide, most recent first. Five cells or fewer - a team that has
 * played twice shows two, never three padded blanks. */
function Form({ form }: { form: string[] }) {
  if (form.length === 0) return <span className="text-text-faint">&mdash;</span>
  return (
    <span className="inline-flex gap-px">
      {form.map((r, i) => (
        <span
          key={i}
          className={`flex size-4 items-center justify-center text-[9px] font-bold ${FORM_FILL[r] ?? 'bg-raised text-text-muted'}`}
        >
          {r}
        </span>
      ))}
    </span>
  )
}

/** THE LEAGUE TABLE - the single most basic object in football, and this app
 * had never rendered one. Computed from real played fixtures, ordered the way
 * the real competition orders it (points, goal difference, goals for).
 *
 * The zone rules are the real ones: top four to the Champions League, bottom
 * three down. They are drawn as edge marks in the position gutter rather than
 * row washes, so they never fight the "my clubs" highlight for the same
 * pixels. */
function LeagueTable({ rows }: { rows: LeagueTableRow[] }) {
  const anyPlayed = rows.some((r) => r.played > 0)
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[54rem] text-left text-sm">
        <caption className="sr-only">Premier League table, computed from real played fixtures</caption>
        <thead>
          <tr className="border-b-2 border-divider text-[10px] uppercase tracking-[0.14em] text-text-faint">
            <th scope="col" className="w-10 py-2 pr-2 text-right font-bold">#</th>
            <th scope="col" className="py-2 pr-4 font-bold">Club</th>
            <th scope="col" className="tabular w-10 py-2 pr-2 text-right font-bold">P</th>
            <th scope="col" className="tabular w-9 py-2 pr-2 text-right font-bold">W</th>
            <th scope="col" className="tabular w-9 py-2 pr-2 text-right font-bold">D</th>
            <th scope="col" className="tabular w-9 py-2 pr-2 text-right font-bold">L</th>
            <th scope="col" className="tabular w-10 py-2 pr-2 text-right font-bold">GF</th>
            <th scope="col" className="tabular w-10 py-2 pr-2 text-right font-bold">GA</th>
            <th scope="col" className="tabular w-12 py-2 pr-4 text-right font-bold">GD</th>
            <th scope="col" className="tabular w-12 py-2 pr-4 text-right font-bold text-text">Pts</th>
            <th scope="col" className="w-28 py-2 pr-4 font-bold">Form</th>
            <th scope="col" className="tabular w-16 py-2 pr-2 text-right font-bold text-pitch-green">xG</th>
            <th scope="col" className="tabular w-16 py-2 text-right font-bold text-alert-red">xGA</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const crest = crestUrl(r.code)
            const zone =
              r.position <= 4 ? 'border-l-2 border-broadcast-blue' : r.position >= 18 ? 'border-l-2 border-alert-red' : 'border-l-2 border-transparent'
            return (
              <tr key={r.team_id} className={`border-b border-divider ${r.in_squad ? 'bg-panel' : ''}`}>
                <td className={`tabular py-2 pr-2 pl-2 text-right font-bold text-text-faint ${zone}`}>{r.position}</td>
                <th scope="row" className="py-2 pr-4 text-left font-bold text-text">
                  <Link to={`/club/${r.team_id}`} className="flex items-center gap-2 hover:text-pitch-green">
                    {crest && <img src={crest} alt="" className="h-5 w-5" />}
                    <span className="truncate">{r.name}</span>
                    {r.in_squad && (
                      <span className="shrink-0 bg-broadcast-gold px-1 py-0.5 text-[8px] font-bold text-broadcast-gold-ink">MINE</span>
                    )}
                  </Link>
                </th>
                <td className="tabular py-2 pr-2 text-right text-text-muted">{r.played}</td>
                <td className="tabular py-2 pr-2 text-right text-text-muted">{r.won}</td>
                <td className="tabular py-2 pr-2 text-right text-text-muted">{r.drawn}</td>
                <td className="tabular py-2 pr-2 text-right text-text-muted">{r.lost}</td>
                <td className="tabular py-2 pr-2 text-right text-text-muted">{r.gf}</td>
                <td className="tabular py-2 pr-2 text-right text-text-muted">{r.ga}</td>
                <td className={`tabular py-2 pr-4 text-right font-semibold ${r.gd > 0 ? 'text-pitch-green' : r.gd < 0 ? 'text-alert-red' : 'text-text-muted'}`}>
                  {r.gd > 0 ? '+' : ''}{r.gd}
                </td>
                <td className="tabular py-2 pr-4 text-right font-display text-lg font-bold text-text">{r.points}</td>
                <td className="py-2 pr-4"><Form form={r.form} /></td>
                <td className="tabular py-2 pr-2 text-right text-text-muted">{r.xg_for?.toFixed(2) ?? '—'}</td>
                <td className="tabular py-2 text-right text-text-muted">{r.xg_against?.toFixed(2) ?? '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {!anyPlayed && (
        <p className="mt-3 text-sm text-text-muted">
          No fixture has been played yet this season, so every row is a real zero rather than a projection.
        </p>
      )}
    </div>
  )
}

const DAY = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

function kickoffParts(iso: string | null) {
  if (!iso) return { day: 'Date TBC', time: '' }
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return { day: 'Date TBC', time: '' }
  return {
    day: `${DAY[d.getDay()]} ${d.getDate()} ${d.toLocaleString([], { month: 'short' })}`,
    time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  }
}

/** One fixture, in the two states football actually has: a result, or a
 * kickoff time. Never both, never a placeholder score for a match that has
 * not happened. */
function FixtureLine({ f }: { f: MatchweekFixture }) {
  const home = crestUrl(f.home.code)
  const away = crestUrl(f.away.code)
  const { time } = kickoffParts(f.kickoff_time)
  const clickable = f.finished && f.match_id !== null
  // A completed fixture opens its own real match report - timeline, contest,
  // and both teams' ratings - rather than an inline panel further down the
  // page. A fixture is a thing you open, not a row you expand.
  const Wrapper: React.ElementType = clickable ? Link : 'div'
  return (
    <Wrapper
      {...(clickable ? { to: `/match/${f.match_id}` } : {})}
      className={`flex w-full items-center gap-3 border-b border-divider py-2.5 text-left ${
        f.has_squad_interest ? 'bg-panel' : ''
      } ${clickable ? 'hover:bg-raised' : ''}`}
    >
      <span className="flex flex-1 items-center justify-end gap-2 text-right">
        <span className={`truncate text-sm font-bold ${f.home.in_squad ? 'text-broadcast-gold' : 'text-text'}`}>{f.home.name}</span>
        {home && <img src={home} alt="" className="h-5 w-5 shrink-0" />}
      </span>

      <span className="w-16 shrink-0 text-center">
        {f.finished ? (
          <span className="tabular font-display text-lg font-bold leading-none text-text">
            {f.home.score ?? 0}<span className="mx-1 text-text-faint">-</span>{f.away.score ?? 0}
          </span>
        ) : (
          <span className="tabular text-sm font-semibold text-text-muted">{time || 'TBC'}</span>
        )}
      </span>

      <span className="flex flex-1 items-center gap-2">
        {away && <img src={away} alt="" className="h-5 w-5 shrink-0" />}
        <span className={`truncate text-sm font-bold ${f.away.in_squad ? 'text-broadcast-gold' : 'text-text'}`}>{f.away.name}</span>
      </span>

      {clickable && <span className="shrink-0 text-[9px] font-bold uppercase tracking-wide text-text-faint">report</span>}
    </Wrapper>
  )
}

/** A gameweek, grouped by real matchday - the way a fixture list is actually
 * published. Saturday's games sit together under Saturday. */
function MatchweekBlockView({ block }: { block: MatchweekBlock }) {
  const byDay = new Map<string, MatchweekFixture[]>()
  for (const f of block.fixtures) {
    const { day } = kickoffParts(f.kickoff_time)
    const list = byDay.get(day) ?? []
    list.push(f)
    byDay.set(day, list)
  }
  return (
    <div className="px-10 py-6">
      <div className="mb-3 flex flex-wrap items-baseline gap-3">
        <span className="font-display text-2xl font-bold uppercase tracking-wide text-text">Gameweek {block.event}</span>
        <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-text-faint">
          {block.complete ? 'complete' : block.is_next ? 'next up' : 'to come'}
        </span>
      </div>
      {[...byDay.entries()].map(([day, fixtures]) => (
        <div key={day} className="mt-4 first:mt-0">
          <div className="border-b-2 border-divider pb-1 text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">{day}</div>
          {fixtures.map((f) => <FixtureLine key={f.fixture_id} f={f} />)}
        </div>
      ))}
    </div>
  )
}


/** A real season board. Three of them, because they answer three different
 * football questions: who is scoring, who is creating, and who the underlying
 * numbers say is about to - the last being the one an FPL manager acts on. */
function LeaderBoard({ title, sub, rows, metric }: {
  title: string
  sub: string
  rows: LeaderRow[]
  metric: (r: LeaderRow) => string
}) {
  if (rows.length === 0) return null
  return (
    <div className="bg-void px-10 py-8">
      <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">{title}</div>
      <div className="mb-3 text-[11px] text-text-faint">{sub}</div>
      <div className="divide-y divide-divider">
        {rows.map((r, i) => {
          const crest = crestUrl(r.team_code)
          const lead = i === 0
          return (
            <div key={r.player_id} className={`flex items-center gap-3 py-2 ${r.is_mine ? 'bg-panel' : ''}`}>
              <span className={`tabular w-5 shrink-0 text-right font-display font-bold ${lead ? 'text-lg text-pitch-green' : 'text-sm text-text-faint'}`}>
                {i + 1}
              </span>
              {crest && <img src={crest} alt="" className="h-4 w-4 shrink-0" />}
              <Link to={`/player/${r.player_id}`} className="min-w-0 flex-1 truncate text-sm font-bold text-text hover:text-pitch-green">
                {r.name}
              </Link>
              {r.is_mine && <span className="shrink-0 bg-broadcast-gold px-1 text-[8px] font-bold text-broadcast-gold-ink">MINE</span>}
              <span className="w-9 shrink-0 text-[10px] uppercase text-text-faint">{r.team_short}</span>
              <span className={`tabular w-12 shrink-0 text-right font-bold ${lead ? 'text-lg text-text' : 'text-sm text-text-muted'}`}>
                {metric(r)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MatchweekSkeleton() {
  return (
    <div className="animate-pulse pb-16">
      <SkelMasthead />
      <div className="px-10 py-8">
        <Skel className="h-2 w-40" />
        <div className="mt-4"><SkelTable rows={20} cols={12} /></div>
      </div>
    </div>
  )
}

export function MatchweekScreen() {
  const state = useFetch(fetchMatchweekPayload, [], 60000)

  if (state.status === 'loading') return <MatchweekSkeleton />
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Football data unavailable"
        description="The table, the fixture calendar and the results could not be fetched. Nothing here is being shown from cache, and no standings are being estimated."
        message={state.error.message}
      />
    )
  }

  const p = state.data
  const played = p.table.reduce((n: number, r: LeagueTableRow) => n + r.played, 0) / 2
  const leader = p.table[0]

  return (
    <div className="data-in pb-16">
      <Masthead edition="Match Desk" title="The Premier League" right={<span className="text-text-faint">{played} matches played</span>} />

      {/* THE LEADERS - a real standings hero. Football opens with who is top,
          not with a metric. */}
      {leader && leader.played > 0 && (
        <div className="relative overflow-hidden border-b-2 border-divider px-10 py-8">
          <span className="ghost-watermark pointer-events-none absolute -top-12 right-2 select-none font-display text-[11rem] font-bold uppercase leading-none">
            TABLE
          </span>
          <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end">
            <div className="h-56 w-full shrink-0 lg:w-96">
              <Podium3D
                entries={p.table.slice(0, 3).map((r: LeagueTableRow) => ({
                  position: r.position, name: r.name, points: r.points, crestUrl: crestUrl(r.code),
                }))}
              />
            </div>
            <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
              {p.table.slice(0, 3).map((r: LeagueTableRow) => {
                const crest = crestUrl(r.code)
                const first = r.position === 1
                return (
                  <div key={r.team_id} className="flex items-end gap-3">
                    <span className={`tabular font-display font-bold leading-none ${first ? 'text-5xl text-pitch-green' : 'text-2xl text-text-faint'}`}>
                      {r.position}
                    </span>
                    {crest && <img src={crest} alt="" className={first ? 'h-12 w-12' : 'h-7 w-7'} />}
                    <div>
                      <Link
                        to={`/club/${r.team_id}`}
                        className={`block font-display font-bold uppercase leading-none text-text hover:text-pitch-green ${first ? 'text-3xl' : 'text-lg'}`}
                      >
                        {r.name}
                      </Link>
                      <div className="mt-1 flex items-center gap-2">
                        <span className={`tabular font-bold ${first ? 'text-xl text-text' : 'text-sm text-text-muted'}`}>{r.points} pts</span>
                        <Form form={r.form} />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      <div className="px-10 py-8">
        <div className="mb-3 flex flex-wrap items-baseline gap-3">
          <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">League table</span>
          <span className="text-[11px] text-text-faint">
            computed from real results &middot; blue = top four &middot; red = relegation &middot; xG is per match
          </span>
        </div>
        <LeagueTable rows={p.table} />
      </div>

      {/* THE BOARDS - who is scoring, who is creating, and who is about to. */}
      {(p.leaders.scorers.length > 0 || p.leaders.assists.length > 0) && (
        <div className="grid grid-cols-1 gap-px border-t-2 border-divider bg-divider lg:grid-cols-3">
          <LeaderBoard
            title="Top scorers"
            sub="real recorded goals this season"
            rows={p.leaders.scorers}
            metric={(r) => `${r.goals ?? 0}`}
          />
          <LeaderBoard
            title="Most assists"
            sub="real recorded assists this season"
            rows={p.leaders.assists}
            metric={(r) => `${r.assists ?? 0}`}
          />
          <LeaderBoard
            title="Underlying numbers"
            sub="real xG + xA — the board that leads output"
            rows={p.leaders.underlying}
            metric={(r) => (r.xgi !== null ? r.xgi.toFixed(2) : '—')}
          />
        </div>
      )}

      {/* THE CALENDAR - results behind, fixtures ahead. */}
      <div className="border-t-2 border-divider">
        <div className="grid grid-cols-1 gap-px bg-divider xl:grid-cols-2">
          {p.matchweeks.map((b: MatchweekBlock) => (
            <div key={b.event} className="bg-void">
              <MatchweekBlockView block={b} />
            </div>
          ))}
        </div>
      </div>

      {p.results.length > 0 && (
        <div className="border-t-2 border-divider px-10 py-6 text-sm text-text-muted">
          Click any completed fixture above for its real match report &mdash; timeline, possession and xG contest, and both
          teams' player ratings. Real detail is held for {p.results.length} finished matches.
        </div>
      )}

    </div>
  )
}
