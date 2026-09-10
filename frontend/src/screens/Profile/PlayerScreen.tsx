import { Fragment } from 'react'
import { Link, useParams } from 'react-router-dom'
import Chart from 'react-apexcharts'
import { Masthead } from '@/components/shell/Masthead'
import { FixtureRun, RunPressure } from '@/components/football/FixtureRun'
import { Skel, SkelMasthead, SkelTable, ScreenError } from '@/components/shell/ScreenStates'
import { CHART_COLORS, baseChart, intAxisLabels } from '@/lib/chartTheme'
import { crestUrl, fetchPlayerProfile, shirtUrl } from '@/lib/api'
import { FlipCard } from '@/components/three/FlipCard'
import { useFetch } from '@/lib/useFetch'
import type { PlayerMatchRow } from '@/lib/types'

const STATUS_LABEL: Record<string, { label: string; fill: string }> = {
  a: { label: 'Available', fill: 'bg-pitch-green text-pitch-green-ink' },
  d: { label: 'Doubtful', fill: 'bg-broadcast-gold text-broadcast-gold-ink' },
  i: { label: 'Injured', fill: 'bg-alert-red text-alert-red-ink' },
  s: { label: 'Suspended', fill: 'bg-alert-red text-alert-red-ink' },
  u: { label: 'Unavailable', fill: 'bg-alert-red text-alert-red-ink' },
}

function shortDate(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getDate()} ${d.toLocaleString([], { month: 'short' })}`
}

/** A real returns cell: a goal and an assist are the two things that make a
 * football match matter, so they get colour and weight, and a blank is a
 * blank rather than a zero shouting for attention. */
function Returns({ m }: { m: PlayerMatchRow }) {
  if (!m.goals && !m.assists) return <span className="text-text-faint">&mdash;</span>
  return (
    <span className="flex gap-2 font-bold">
      {m.goals ? <span className="text-pitch-green">{m.goals}G</span> : null}
      {m.assists ? <span className="text-broadcast-gold">{m.assists}A</span> : null}
    </span>
  )
}

export function PlayerScreen() {
  const { id } = useParams()
  const state = useFetch(() => fetchPlayerProfile(Number(id)), [id], 60000)

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="flex gap-8 border-b-2 border-divider px-10 py-8">
          <Skel className="h-32 w-32" />
          <div className="flex-1 space-y-3">
            <Skel className="h-10 w-72" />
            <Skel className="h-4 w-48" />
            <Skel className="h-6 w-full max-w-md" />
          </div>
        </div>
        <div className="px-10 py-8"><SkelTable rows={10} cols={9} /></div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Player unavailable"
        description="No profile could be fetched for this player. If the id does not exist the backend returns a real 404 rather than an empty profile."
        message={state.error.message}
      />
    )
  }

  const p = state.data
  const pl = p.player
  const shirt = shirtUrl(pl.team_code, pl.position === 'GKP', 260)
  const crest = crestUrl(pl.team_code)
  const status = STATUS_LABEL[pl.status ?? 'a']
  const thisSeason = p.match_log.filter((m) => m.season === p.match_log[0]?.season)

  // Real per-match xG vs xA, most recent last so the chart reads left to
  // right in time. Nothing is smoothed and nothing is interpolated for a
  // match the feed never covered.
  const chartRows = [...thisSeason].reverse()
  const hasChart = chartRows.some((m) => m.xg !== null || m.xa !== null)

  const totals = p.season

  return (
    <div className="data-in pb-16">
      <Masthead
        edition="Player File"
        title={pl.full_name}
        right={<Link to={`/club/${pl.team_id}`} className="text-broadcast-blue hover:underline">{pl.team_name}</Link>}
      />

      {/* THE FILE HEAD - kit at real scale, identity, and the one thing that
          changes whether any of the rest matters: availability. */}
      <div className="relative overflow-hidden border-b-2 border-divider">
        <span className="ghost-watermark pointer-events-none absolute -top-14 right-4 select-none font-display text-[12rem] font-bold uppercase leading-none">
          {pl.position}
        </span>
        <div className="relative flex flex-wrap items-end gap-8 px-10 py-8">
          {shirt && (
            <FlipCard
              className="h-32 w-32 shrink-0"
              ariaLabel={`Flip ${pl.name}'s card to see season totals`}
              front={<img src={shirt} alt="" className="h-32 w-32 object-contain" />}
              back={
                <div className="flex h-32 w-32 flex-col items-center justify-center gap-1 border-2 border-divider bg-panel text-center">
                  <span className="text-[8px] font-bold uppercase tracking-wide text-text-faint">This season</span>
                  <span className="tabular font-display text-2xl font-bold text-pitch-green">{totals?.total_points ?? '—'}</span>
                  <span className="text-[9px] uppercase tracking-wide text-text-faint">points</span>
                  {totals && (
                    <span className="tabular mt-1 text-[10px] text-text-muted">
                      {totals.goals_scored}G &middot; {totals.assists}A
                    </span>
                  )}
                </div>
              }
            />
          )}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              {crest && <img src={crest} alt="" className="h-6 w-6" />}
              <Link to={`/club/${pl.team_id}`} className="text-sm font-bold uppercase tracking-wide text-text-muted hover:text-text">
                {pl.team_name}
              </Link>
              <span className="bg-raised px-1.5 py-0.5 text-[10px] font-bold text-text-muted">{pl.position}</span>
              {pl.is_mine && <span className="bg-broadcast-gold px-1.5 py-0.5 text-[10px] font-bold text-broadcast-gold-ink">IN MY SQUAD</span>}
            </div>
            <div className="mt-1 font-display text-5xl font-bold uppercase leading-none text-text">{pl.name}</div>
            <div className="mt-3 flex flex-wrap items-center gap-4">
              {pl.price_m !== null && (
                <span className="tabular font-display text-2xl font-bold text-text">£{pl.price_m.toFixed(1)}m</span>
              )}
              {status && (
                <span className={`px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${status.fill}`}>{status.label}</span>
              )}
            </div>
            {pl.news && <p className="mt-2 max-w-2xl text-sm text-broadcast-gold">{pl.news}</p>}
          </div>
          <div className="flex flex-col items-end gap-2">
            <FixtureRun fixtures={p.fixtures} max={5} showEvent />
            <RunPressure fixtures={p.fixtures} max={5} />
          </div>
        </div>
      </div>

      {/* SEASON TOTALS - real recorded totals, never a projection. */}
      {totals && (
        <div className="grid grid-cols-2 gap-px border-b-2 border-divider bg-divider sm:grid-cols-4 lg:grid-cols-7">
          {(
            [
              ['Points', totals.total_points],
              ['Minutes', totals.minutes],
              ['Goals', totals.goals_scored],
              ['Assists', totals.assists],
              ['Bonus', totals.bonus],
              ['xG', totals.expected_goals],
              ['xA', totals.expected_assists],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="bg-void px-5 py-4">
              <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">{label}</div>
              <div className="tabular mt-1 font-display text-2xl font-bold text-text">
                {value === null || value === undefined ? '—' : typeof value === 'number' ? value : value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* THE MATCH LOG - the football. 57,200 real per-match rows have been in
          this database all season and the app had never rendered one of them;
          every rate it showed was a season aggregate. */}
      <div className="px-10 py-8">
        <div className="mb-3 flex flex-wrap items-baseline gap-3">
          <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Match log</span>
          <span className="text-[11px] text-text-faint">real per-match record, most recent first</span>
        </div>
        {p.match_log.length === 0 ? (
          <p className="max-w-2xl text-sm text-text-muted">
            No per-match record has been resolved for this player yet. That is a real gap in the underlying match data,
            not an empty season &mdash; their season totals above are unaffected.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] text-left text-sm">
              <caption className="sr-only">Per-match record</caption>
              <thead>
                <tr className="border-b-2 border-divider text-[10px] uppercase tracking-[0.14em] text-text-faint">
                  <th scope="col" className="py-2 pr-4 font-bold">Date</th>
                  <th scope="col" className="py-2 pr-4 font-bold">Returns</th>
                  <th scope="col" className="tabular py-2 pr-4 text-right font-bold">Min</th>
                  <th scope="col" className="tabular py-2 pr-4 text-right font-bold">Shots</th>
                  <th scope="col" className="tabular py-2 pr-4 text-right font-bold text-pitch-green">xG</th>
                  <th scope="col" className="tabular py-2 pr-4 text-right font-bold text-broadcast-gold">xA</th>
                  <th scope="col" className="tabular py-2 pr-4 text-right font-bold">KP</th>
                  <th scope="col" className="py-2 text-right font-bold">Cards</th>
                </tr>
              </thead>
              <tbody>
                {p.match_log.map((m, i) => {
                  // The log runs back past the start of this season. Saying
                  // so is the difference between "three quiet games" and
                  // "three games, then last season" - without the divider a
                  // reader would treat a May fixture as recent form.
                  const newSeason = i > 0 && m.season !== p.match_log[i - 1].season
                  return (
                    <Fragment key={i}>
                    {newSeason && (
                      <tr className="border-b-2 border-divider">
                        <td colSpan={8} className="bg-panel py-1.5 text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">
                          {m.season} season
                        </td>
                      </tr>
                    )}
                  <tr className={`border-b border-divider ${m.goals || m.assists ? 'bg-panel' : ''}`}>
                    <th scope="row" className="py-2 pr-4 text-left font-bold text-text">{shortDate(m.match_date)}</th>
                    <td className="py-2 pr-4"><Returns m={m} /></td>
                    <td className="tabular py-2 pr-4 text-right text-text-muted">{m.minutes ?? '—'}</td>
                    <td className="tabular py-2 pr-4 text-right text-text-muted">{m.shots ?? '—'}</td>
                    <td className="tabular py-2 pr-4 text-right text-text">{m.xg !== null ? m.xg.toFixed(2) : '—'}</td>
                    <td className="tabular py-2 pr-4 text-right text-text">{m.xa !== null ? m.xa.toFixed(2) : '—'}</td>
                    <td className="tabular py-2 pr-4 text-right text-text-muted">{m.key_passes ?? '—'}</td>
                    <td className="py-2 text-right">
                      {m.red_cards ? <span className="inline-block h-3 w-2 bg-alert-red" title="Red card" /> : null}
                      {m.yellow_cards ? <span className="ml-1 inline-block h-3 w-2 bg-broadcast-gold" title="Yellow card" /> : null}
                      {!m.red_cards && !m.yellow_cards ? <span className="text-text-faint">&mdash;</span> : null}
                    </td>
                  </tr>
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* THREAT OVER TIME - the same rows as the log, read as a shape. */}
      {hasChart && (
        <div className="border-t-2 border-divider px-10 py-8">
          <div className="mb-3 flex flex-wrap items-baseline gap-4">
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Threat per match</span>
            <span className="flex items-center gap-1.5 text-[11px] text-text-muted">
              <span className="h-2 w-3 bg-pitch-green" /> xG
            </span>
            <span className="flex items-center gap-1.5 text-[11px] text-text-muted">
              <span className="h-2 w-3 bg-broadcast-gold" /> xA
            </span>
          </div>
          <Chart
            type="bar"
            height={220}
            options={baseChart({
              chart: { type: 'bar', stacked: false },
              colors: [CHART_COLORS.primary, CHART_COLORS.accent],
              xaxis: { categories: chartRows.map((m) => shortDate(m.match_date)), labels: { style: { cssClass: 'tabular' } } },
              yaxis: { labels: intAxisLabels },
            })}
            series={[
              { name: 'xG', data: chartRows.map((m) => Number((m.xg ?? 0).toFixed(2))) },
              { name: 'xA', data: chartRows.map((m) => Number((m.xa ?? 0).toFixed(2))) },
            ]}
          />
        </div>
      )}

      {/* PRICE - the FPL market's own read on this player over time. */}
      {p.price_history.length > 1 && (
        <div className="border-t-2 border-divider px-10 py-8">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Price</div>
          <Chart
            type="line"
            height={180}
            options={baseChart({
              chart: { type: 'line' },
              colors: [CHART_COLORS.secondary],
              stroke: { width: 3, curve: 'stepline' },
              xaxis: { categories: p.price_history.map((r) => shortDate(r.valid_from)), labels: { style: { cssClass: 'tabular' } } },
              yaxis: { labels: { formatter: (v: number) => `£${v.toFixed(1)}m`, style: { cssClass: 'tabular' } } },
            })}
            series={[{ name: 'Price', data: p.price_history.map((r) => r.price_m) }]}
          />
        </div>
      )}
    </div>
  )
}
