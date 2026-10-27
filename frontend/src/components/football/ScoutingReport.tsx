import type { ScoutingMeasure, ScoutingReportData } from '@/lib/types'

/** THE SCOUTING REPORT: how he plays and how good he is at it, against players in his position this season. Every line
 * carries its number and its percentile; the profile label is a rule over those percentiles, shown as such. */

const pctTone = (p: number | null) =>
  p === null ? 'bg-text-faint/40' : p >= 75 ? 'bg-pitch-green' : p <= 25 ? 'bg-alert-red' : 'bg-broadcast-blue'

function Bar({ m }: { m: ScoutingMeasure }) {
  return (
    <div className="grid grid-cols-[minmax(0,11rem)_4.5rem_minmax(0,1fr)_2.5rem] items-center gap-3 py-1.5">
      <div className="min-w-0">
        <div className="truncate text-[13.5px] font-semibold text-text">{m.label}</div>
        <div className="truncate text-[11.5px] text-text-faint">{m.unit}</div>
      </div>
      <div className="text-right font-display text-lg font-bold tabular-nums text-text">{m.display}</div>
      <div className="relative h-2.5 rounded-full bg-raised" title={m.median_display ? `median ${m.median_display}` : undefined}>
        <div className="absolute inset-y-[-3px] left-1/2 w-px bg-text-faint/60" />
        {m.percentile !== null && <div className={`bar-draw h-full rounded-full ${pctTone(m.percentile)}`} style={{ width: `${Math.max(3, m.percentile)}%` }} />}
      </div>
      <div className="text-right text-[13px] font-semibold tabular-nums text-text-muted">{m.percentile ?? '–'}</div>
    </div>
  )
}

function styleSentence(m: ScoutingMeasure): string {
  const median = m.median_display ? ` (the median is ${m.median_display})` : ''
  switch (m.key) {
    case 'box_share':
      return `${m.display} of his shots come from inside the box${median}.`
    case 'close_share':
      return `${m.display} from the six-yard box${median}.`
    case 'header_share':
      return `${m.display} of his shots are headers${median}.`
    case 'setpiece_share':
      return `${m.display} come from set pieces${median}.`
    case 'fastbreak_share':
      return `${m.display} come on the break${median}.`
    case 'saves90':
      return `${m.display} saves per 90${median}.`
    default:
      return `${m.label}: ${m.display}${median}.`
  }
}

export function ScoutingReport({ r, name }: { r: ScoutingReportData; name: string }) {
  const quality = r.measures.filter((m) => m.kind === 'quality')
  return (
    <div className="border-b border-divider px-10 py-8">
      <div className="mb-1 flex flex-wrap items-baseline gap-3">
        <span className="font-display text-2xl font-bold text-text">Scouting report</span>
        <span className="text-[13px] text-text-faint">
          {r.minutes} minutes, {r.shots} shots this season · percentiles {r.pool_note}
        </span>
      </div>
      {r.profile.length > 0 && (
        <div className="mb-5 mt-3 flex flex-wrap items-center gap-2">
          {r.profile.map((t) => (
            <span key={t} className="rounded-full border border-pitch-green/40 bg-pitch-green/10 px-3 py-1 text-[13px] font-semibold text-pitch-green">
              {t}
            </span>
          ))}
          <span className="text-[12px] text-text-faint">a reading of the percentiles below, not an observation</span>
        </div>
      )}
      {!r.ranked && <p className="mb-4 text-[13px] text-broadcast-gold">Under 270 minutes this season: shown, not ranked.</p>}
      <div className="grid gap-10 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div>
          <div className="mb-1 text-[13px] font-bold text-text-faint">How good he is at it</div>
          <div className="divide-y divide-divider/60">
            {quality.map((m) => (
              <Bar key={m.key} m={m} />
            ))}
          </div>
        </div>
        <div className="space-y-6">
          {r.style.length > 0 && (
            <div>
              <div className="mb-2 text-[13px] font-bold text-text-faint">How he plays</div>
              <ul className="space-y-1.5 text-[14px] leading-snug text-text-muted">
                {r.style.map((m) => (
                  <li key={m.key}>
                    {styleSentence(m)}
                    {m.percentile !== null && <span className="ml-1 text-[12px] text-text-faint">{m.percentile}th pct</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(r.finishing || r.prevented !== null || r.penalties > 0) && (
            <div>
              <div className="mb-2 text-[13px] font-bold text-text-faint">Finishing</div>
              <ul className="space-y-1.5 text-[14px] leading-snug text-text-muted">
                {r.finishing && (
                  <li>
                    {r.finishing.np_goals} non-penalty goal{r.finishing.np_goals === 1 ? '' : 's'} from {r.finishing.npxg.toFixed(2)} xG:{' '}
                    <span className={r.finishing.difference >= 0 ? 'font-semibold text-pitch-green' : 'font-semibold text-alert-red'}>
                      {r.finishing.difference >= 0 ? '+' : ''}
                      {r.finishing.difference.toFixed(2)}
                    </span>
                    . Finishing above or below xG has not carried to the next match in this database (r +0.03); getting the chances has (r +0.48).
                  </li>
                )}
                {r.penalties > 0 && <li>{r.penalties} penalt{r.penalties === 1 ? 'y' : 'ies'} taken this season.</li>}
                {r.prevented !== null && (
                  <li>
                    On-target shots he faced were worth {Math.abs(r.prevented).toFixed(1)} goals {r.prevented >= 0 ? 'more' : 'fewer'} than he let in:{' '}
                    <span className={r.prevented >= 0 ? 'font-semibold text-pitch-green' : 'font-semibold text-alert-red'}>
                      {r.prevented >= 0 ? `${r.prevented.toFixed(1)} prevented` : `${Math.abs(r.prevented).toFixed(1)} conceded beyond the shots`}
                    </span>
                    .
                  </li>
                )}
              </ul>
            </div>
          )}
          {r.recent.length > 0 && (
            <div>
              <div className="mb-2 text-[13px] font-bold text-text-faint">Lately (last five appearances)</div>
              <ul className="space-y-1.5 text-[14px] leading-snug text-text-muted">
                {r.recent.map((x) => (
                  <li key={x.key}>
                    {x.label} {x.recent.toFixed(2)} against {x.season.toFixed(2)} over the season{' '}
                    <span className={x.change >= 0 ? 'font-semibold text-pitch-green' : 'font-semibold text-alert-red'}>
                      ({x.change >= 0 ? '+' : ''}
                      {Math.round(x.change * 100)}%)
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {r.last_season && (
            <div className="text-[14px] leading-snug text-text-muted">
              <div className="mb-2 text-[13px] font-bold text-text-faint">Last season ({r.last_season.season})</div>
              {name}: {r.last_season.goals} goals, {r.last_season.assists} assists in {r.last_season.minutes} minutes; {r.last_season.xg90.toFixed(2)} xG and{' '}
              {r.last_season.xa90.toFixed(2)} xA per 90, {r.last_season.shots90.toFixed(1)} shots and {r.last_season.key_passes90.toFixed(1)} key passes per 90.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
