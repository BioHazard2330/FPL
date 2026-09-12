import { Link, useParams } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { FixtureRun, RunPressure } from '@/components/football/FixtureRun'
import { Skel, SkelMasthead, SkelTable, ScreenError } from '@/components/shell/ScreenStates'
import { crestUrl, fetchClubProfile } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { SeasonDnaHelix } from '@/components/three/SeasonDnaHelix'
import { XgMountainRange } from '@/components/three/XgMountainRange'
import { TrophyShelf3D } from '@/components/three/TrophyShelf3D'
import { HONOURS } from '@/lib/honours'
import type { ClubResultRow } from '@/lib/types'

const RESULT_FILL: Record<string, string> = {
  W: 'bg-pitch-green text-pitch-green-ink',
  D: 'bg-raised text-text-muted',
  L: 'bg-alert-red text-alert-red-ink',
}

// SeasonDnaHelix's own spiral advances 2*pi/7 radians per real match - below
// this many points it hasn't completed enough of a turn to read as a real
// coil (confirmed live 2026-09-12: 3 points looked like two dots and a
// line, not a spiral). A plain W/D/L strip stands in until there's enough
// real season for the shape to mean something.
const MIN_SPIRAL_MATCHES = 6

function shortDate(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getDate()} ${d.toLocaleString([], { month: 'short' })}`
}

/** One played match from this club's own point of view: did they win, who
 * against, home or away, and did the xG agree with the scoreline. The last
 * of those is the whole reason a football fan looks at a result twice. */
function ResultRow({ r }: { r: ClubResultRow }) {
  const crest = crestUrl(r.opponent_code)
  const outperformed = r.xg !== null && r.xga !== null ? r.gf - r.ga - (r.xg - r.xga) : null
  return (
    <div className="flex items-center gap-3 border-b border-divider py-2.5">
      <span className={`flex size-6 shrink-0 items-center justify-center text-[11px] font-bold ${RESULT_FILL[r.result]}`}>
        {r.result}
      </span>
      <span className="w-12 shrink-0 text-[10px] uppercase tracking-wide text-text-faint">{r.is_home ? 'Home' : 'Away'}</span>
      <span className="flex min-w-0 flex-1 items-center gap-2">
        {crest && <img src={crest} alt="" className="h-5 w-5 shrink-0" />}
        <span className="truncate text-sm font-bold text-text">{r.opponent_short}</span>
      </span>
      <span className="tabular w-14 shrink-0 text-center font-display text-lg font-bold text-text">
        {r.gf}<span className="mx-1 text-text-faint">-</span>{r.ga}
      </span>
      <span className="tabular w-28 shrink-0 text-right text-xs text-text-muted">
        {r.xg !== null && r.xga !== null ? `${r.xg.toFixed(2)} - ${r.xga.toFixed(2)} xG` : '—'}
      </span>
      {outperformed !== null && (
        <span
          className={`tabular w-14 shrink-0 text-right text-xs font-bold ${
            outperformed > 0.5 ? 'text-pitch-green' : outperformed < -0.5 ? 'text-alert-red' : 'text-text-faint'
          }`}
          title="Real goal difference minus expected goal difference - did the scoreline flatter them"
        >
          {outperformed > 0 ? '+' : ''}{outperformed.toFixed(1)}
        </span>
      )}
      <span className="w-12 shrink-0 text-right text-[10px] text-text-faint">{shortDate(r.kickoff_time)}</span>
    </div>
  )
}

export function ClubScreen() {
  const { id } = useParams()
  const state = useFetch(() => fetchClubProfile(Number(id)), [id], 60000)

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="flex gap-6 border-b-2 border-divider px-10 py-8">
          <Skel className="h-20 w-20" />
          <div className="flex-1 space-y-3">
            <Skel className="h-10 w-64" />
            <Skel className="h-4 w-40" />
          </div>
        </div>
        <div className="px-10 py-8"><SkelTable rows={12} cols={8} /></div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Club unavailable"
        description="No profile could be fetched for this club. If the id does not exist the backend returns a real 404 rather than an empty profile."
        message={state.error.message}
      />
    )
  }

  const p = state.data
  const c = p.club
  const crest = crestUrl(c.code)
  const form = p.results.slice(0, 5).map((r) => r.result)
  // `p.results` is most-recent-first (a form guide's own natural order) -
  // both 3D season shapes below read as a timeline instead, so they need
  // the same real matches oldest-first.
  const chronological = p.results.slice().reverse()
  const xgMatches = chronological.filter(
    (r): r is ClubResultRow & { xg: number; xga: number } => r.xg !== null && r.xga !== null,
  )
  const honours = HONOURS[c.code]

  return (
    <div className="data-in pb-16">
      <Masthead edition="Club File" title={c.name} right={<span className="text-text-faint">{p.results.length} played</span>} />

      <div className="relative overflow-hidden border-b-2 border-divider">
        <span className="ghost-watermark pointer-events-none absolute -top-14 right-4 select-none font-display text-[12rem] font-bold uppercase leading-none">
          {c.short}
        </span>
        <div className="relative flex flex-wrap items-end gap-8 px-10 py-8">
          {crest && <img src={crest} alt="" className="h-20 w-20 shrink-0" />}
          <div className="min-w-0">
            <div className="font-display text-5xl font-bold uppercase leading-none text-text">{c.name}</div>
            <div className="mt-3 flex items-center gap-2">
              {form.length > 0 && (
                <>
                  <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">Form</span>
                  {form.map((r, i) => (
                    <span key={i} className={`flex size-5 items-center justify-center text-[10px] font-bold ${RESULT_FILL[r]}`}>
                      {r}
                    </span>
                  ))}
                </>
              )}
              {p.owned_count > 0 && (
                <span className="ml-3 bg-broadcast-gold px-2 py-0.5 text-[10px] font-bold text-broadcast-gold-ink">
                  {p.owned_count} in my squad
                </span>
              )}
            </div>
          </div>
          <div className="ml-auto flex flex-col items-end gap-2">
            <FixtureRun fixtures={p.fixtures} max={6} showEvent />
            <RunPressure fixtures={p.fixtures} max={6} />
          </div>
        </div>
      </div>

      {/* SEASON SHAPE - the same real results/xG the tables below already
          show, read instead as a timeline: a real single-strand spiral
          through the W/D/L sequence, and real per-match xG-for/xG-against
          ridgelines. Two real 3D data views, not a decorative pair - each
          renders `null` (and this whole section stays hidden) with nothing
          real to draw yet. */}
      {/* TROPHY SHELF - real major-honours counts (`lib/honours.ts`), one
          small trophy mesh per title this club has actually won, a real
          bare shelf when it has won nothing. Absent (not a zero shelf) for
          any club `HONOURS` doesn't cover - a future season's promoted/
          relegated club, never guessed at. */}
      {honours && (
        <div className="border-b-2 border-divider bg-void px-10 py-7">
          <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Trophy shelf</div>
          <div className="mb-3 text-[11px] text-text-faint">
            real major honours &middot; league {honours.league} &middot; FA Cup {honours.faCup} &middot; League Cup {honours.leagueCup} &middot; European {honours.european}
          </div>
          <div className="h-72 w-full">
            <TrophyShelf3D honours={honours} />
          </div>
        </div>
      )}

      {(chronological.length > 0 || xgMatches.length > 0) && (
        <div className="grid grid-cols-1 gap-px border-b-2 border-divider bg-divider lg:grid-cols-2">
          {chronological.length > 0 && (
            <div className="bg-void px-10 py-7">
              <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Season shape</div>
              <div className="mb-3 text-[11px] text-text-faint">real results this season, oldest at the base</div>
              {chronological.length >= MIN_SPIRAL_MATCHES ? (
                <div className="h-64 w-full">
                  <SeasonDnaHelix matches={chronological.map((r) => ({ result: r.result, opponent_short: r.opponent_short }))} />
                </div>
              ) : (
                // Real early-season honesty, not a decorative placeholder:
                // the spiral needs enough real points to actually curve -
                // at 1-2 matches it's just two dots and a line, which reads
                // as broken rather than as a season shape. The plain strip
                // reuses the exact real W/D/L colours the page's own form
                // line already establishes, so nothing new is invented.
                <div className="flex h-64 w-full flex-col items-center justify-center gap-3">
                  <div className="flex gap-1.5">
                    {chronological.map((r, i) => (
                      <span
                        key={i}
                        className={`flex size-8 items-center justify-center text-sm font-bold ${RESULT_FILL[r.result]}`}
                      >
                        {r.result}
                      </span>
                    ))}
                  </div>
                  <p className="max-w-xs text-center text-[11px] text-text-faint">
                    the 3D season spiral needs a few more real matches before it reads as a real shape
                  </p>
                </div>
              )}
            </div>
          )}
          {xgMatches.length > 0 && (
            <div className="bg-void px-10 py-7">
              <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">xG range</div>
              <div className="mb-3 text-[11px] text-text-faint">
                <span className="text-pitch-green">real xG for</span> vs <span className="text-alert-red">real xG against</span>, per match
              </div>
              <div className="h-64 w-full">
                <XgMountainRange matches={xgMatches.map((r) => ({ xg: r.xg, xga: r.xga, opponent_short: r.opponent_short }))} />
              </div>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-px bg-divider xl:grid-cols-[5fr_7fr]">
        {/* RESULTS - with the xG read beside the scoreline, because a 1-0 off
            0.3 xG and a 1-0 off 2.4 xG are different football. */}
        <div className="bg-void px-10 py-8">
          <div className="mb-3 flex flex-wrap items-baseline gap-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Results</span>
            <span className="text-[11px] text-text-faint">score vs xG &middot; right column = how much the scoreline beat the xG</span>
          </div>
          {p.results.length === 0 ? (
            <p className="text-sm text-text-muted">No completed fixture yet this season.</p>
          ) : (
            p.results.map((r) => <ResultRow key={r.fixture_id} r={r} />)
          )}
        </div>

        {/* THE SQUAD - this club's real FPL-registered players. Clicking a row
            opens their real match log. */}
        <div className="bg-void px-10 py-8">
          <div className="mb-3 flex flex-wrap items-baseline gap-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Squad</span>
            <span className="text-[11px] text-text-faint">real recorded season totals &middot; most productive first</span>
          </div>
          <div className="max-h-[36rem] overflow-y-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{c.name} squad, FPL-registered players</caption>
              <thead className="sticky top-0 bg-void">
                <tr className="border-b-2 border-divider text-[10px] uppercase tracking-[0.14em] text-text-faint">
                  <th scope="col" className="py-2 pr-3 font-bold">Player</th>
                  <th scope="col" className="py-2 pr-3 font-bold">Pos</th>
                  <th scope="col" className="tabular py-2 pr-3 text-right font-bold">Price</th>
                  <th scope="col" className="tabular py-2 pr-3 text-right font-bold">Pts</th>
                  <th scope="col" className="tabular py-2 pr-3 text-right font-bold">Min</th>
                  <th scope="col" className="tabular py-2 pr-3 text-right font-bold">G</th>
                  <th scope="col" className="tabular py-2 pr-3 text-right font-bold">A</th>
                  <th scope="col" className="tabular py-2 text-right font-bold text-pitch-green">xG</th>
                </tr>
              </thead>
              <tbody>
                {p.squad.map((s) => (
                  <tr key={s.player_id} className={`border-b border-divider ${s.is_mine ? 'bg-panel' : ''}`}>
                    <th scope="row" className="py-1.5 pr-3 text-left font-bold">
                      <Link to={`/player/${s.player_id}`} className="flex items-center gap-2 text-text hover:text-pitch-green">
                        <span className="truncate">{s.name}</span>
                        {s.is_mine && <span className="bg-broadcast-gold px-1 text-[8px] font-bold text-broadcast-gold-ink">MINE</span>}
                      </Link>
                    </th>
                    <td className="py-1.5 pr-3">
                      <span className="bg-raised px-1.5 py-0.5 text-[9px] font-bold text-text-muted">{s.position}</span>
                    </td>
                    <td className="tabular py-1.5 pr-3 text-right text-text-muted">
                      {s.price_m !== null ? `£${s.price_m.toFixed(1)}m` : '—'}
                    </td>
                    <td className="tabular py-1.5 pr-3 text-right font-semibold text-text">{s.total_points ?? '—'}</td>
                    <td className="tabular py-1.5 pr-3 text-right text-text-muted">{s.minutes ?? '—'}</td>
                    <td className="tabular py-1.5 pr-3 text-right text-text-muted">{s.goals ?? '—'}</td>
                    <td className="tabular py-1.5 pr-3 text-right text-text-muted">{s.assists ?? '—'}</td>
                    <td className="tabular py-1.5 text-right text-text-muted">
                      {s.xg !== null && s.xg !== undefined ? Number(s.xg).toFixed(2) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
