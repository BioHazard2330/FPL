import { crestUrl } from '@/lib/api'
import { fdrFill, fdrInk, pressureInk, runPressure } from '@/lib/fdr'
import type { FixtureEntry } from '@/lib/types'

/** The single next real fixture, as a compact broadcast chip.
 *
 * This is the piece of football the app was missing everywhere it mattered:
 * a squad tile used to show a projection with no opponent, no venue and no
 * difficulty on it at all. Renders opponent crest + short name + (H)/(A),
 * coloured by the real FDR. Renders nothing at all when there genuinely is
 * no next fixture (a blank gameweek) - never a placeholder opponent. */
export function NextFixture({ fixtures, className = '' }: { fixtures: FixtureEntry[] | undefined; className?: string }) {
  const next = fixtures?.[0]
  if (!next) return null
  const crest = crestUrl(next.opponent_code)
  return (
    <span
      className={`inline-flex items-center gap-1 px-1 py-px text-[9px] font-bold uppercase leading-none tracking-wide ${fdrFill(
        next.difficulty,
      )} ${className}`}
      title={`GW${next.event} ${next.is_home ? 'vs' : 'away to'} ${next.opponent_short} · FDR ${next.difficulty}`}
    >
      {crest && <img src={crest} alt="" className="h-2.5 w-2.5" />}
      {next.opponent_short}
      <span className="opacity-70">{next.is_home ? 'H' : 'A'}</span>
    </span>
  )
}

/** A run of upcoming fixtures as flat FDR cells - the ticker grammar, at a
 * size that fits beside a player rather than filling a row. */
export function FixtureRun({
  fixtures,
  max = 5,
  showEvent = false,
  className = '',
}: {
  fixtures: FixtureEntry[] | undefined
  max?: number
  showEvent?: boolean
  className?: string
}) {
  if (!fixtures || fixtures.length === 0) return null
  const run = fixtures.slice(0, max)
  return (
    <span className={`inline-flex gap-px ${className}`}>
      {run.map((f) => (
        <span
          key={f.event}
          className={`flex min-w-[1.6rem] flex-col items-center justify-center px-1 py-0.5 text-[8px] font-bold uppercase leading-tight ${fdrFill(
            f.difficulty,
          )}`}
          title={`GW${f.event} ${f.is_home ? 'vs' : 'away to'} ${f.opponent_short} · FDR ${f.difficulty}`}
        >
          {showEvent && <span className="opacity-70">GW{f.event}</span>}
          <span>{f.opponent_short}</span>
          <span className="opacity-70">{f.is_home ? 'H' : 'A'}</span>
        </span>
      ))}
    </span>
  )
}

/** The run's mean FDR, stated as such. Arithmetic over the cells drawn
 * beside it - not a model output, and labelled so nobody reads it as one. */
export function RunPressure({ fixtures, max = 5 }: { fixtures: FixtureEntry[] | undefined; max?: number }) {
  if (!fixtures || fixtures.length === 0) return null
  const run = fixtures.slice(0, max)
  const p = runPressure(run)
  if (p === null) return null
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">Avg FDR</span>
      <span className={`tabular font-display text-lg font-bold ${pressureInk(p)}`}>{p.toFixed(1)}</span>
    </span>
  )
}

/** One-line prose form, for a dense table cell where even a chip is too
 * much furniture. */
export function FixtureLine({ fixtures }: { fixtures: FixtureEntry[] | undefined }) {
  const next = fixtures?.[0]
  if (!next) return <span className="text-text-faint">&mdash;</span>
  return (
    <span className={`text-xs font-semibold ${fdrInk(next.difficulty)}`}>
      {next.is_home ? '' : '@'}
      {next.opponent_short}
    </span>
  )
}
