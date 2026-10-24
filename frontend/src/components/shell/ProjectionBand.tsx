import { fetchProjection } from '@/lib/api'
import { Skel } from '@/components/shell/ScreenStates'
import { useFetch } from '@/lib/useFetch'
import { FixtureRun } from '@/components/football/FixtureRun'
import type { ComparePlayer } from '@/lib/types'

const PARTS: [keyof NonNullable<ComparePlayer['components']>, string][] = [
  ['appearance', 'Appearance'], ['goals', 'Goals'], ['assists', 'Assists'], ['bonus', 'Bonus'],
  ['clean_sheet', 'Clean sheet'], ['defcon', 'Defensive actions'], ['saves', 'Saves'], ['conceded', 'Conceded'], ['cards', 'Cards'],
]
const SHADE = ['bg-pitch-green', 'bg-broadcast-blue', 'bg-broadcast-gold', 'bg-text', 'bg-pitch-green-deep', 'bg-text-muted', 'bg-alert-red', 'bg-alert-red']

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div>
      <div className="text-[12px] font-bold text-text-faint">{label}</div>
      <div className="tabular mt-0.5 font-display text-3xl font-bold leading-none text-text">{value}</div>
      {sub && <div className="mt-1 text-[12px] text-text-faint">{sub}</div>}
    </div>
  )
}

/** WHAT THE MODEL EXPECTS - the forward-looking half of a player file. The
 * season totals and shot map above are what he has done; this is the same
 * projection every other screen uses for the next gameweek and the next five,
 * with the range it could land in and where the points come from. It loads
 * separately because the first projection of a session refits team strength. */
export function ProjectionBand({ playerId }: { playerId: number }) {
  const state = useFetch(() => fetchProjection(playerId), [playerId])
  if (state.status === 'loading') {
    return (
      <div className="animate-pulse border-b border-divider px-10 py-8">
        <Skel className="h-3 w-48" />
        <Skel className="mt-4 h-16 w-full" />
      </div>
    )
  }
  if (state.status === 'error') return null
  const { player: p, window } = state.data
  const parts = p.components ? PARTS.map(([k, label], i) => ({ label, v: p.components![k], tone: SHADE[i] })).filter((x) => Math.abs(x.v) > 0.005) : []
  const positive = parts.filter((x) => x.v > 0)
  const total = positive.reduce((s, x) => s + x.v, 0) || 1
  const range = p.ceiling - p.floor || 1
  const medianAt = ((p.xp_next - p.floor) / range) * 100
  return (
    <div className="border-b border-divider px-10 py-8">
      <div className="mb-4 flex flex-wrap items-baseline gap-3">
        <span className="font-display text-2xl font-bold text-text">What the model expects</span>
        <span className="text-[13px] text-text-faint">the same projection every screen uses</span>
      </div>
      <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] gap-12">
        <div>
          <div className="flex flex-wrap gap-x-10 gap-y-4">
            <Stat label="xP next gameweek" value={<span className="text-pitch-green">{p.xp_next.toFixed(1)}</span>} sub={`${p.floor.toFixed(1)} to ${p.ceiling.toFixed(1)} (10th to 90th percentile)`} />
            <Stat label={`xP next ${window} fixtures`} value={p.xp_window.toFixed(1)} sub={`${p.fixture_count} fixture${p.fixture_count === 1 ? '' : 's'} in the window`} />
            <Stat label="Expected minutes" value={p.expected_minutes.toFixed(0)} sub={p.start_percent !== null ? `${p.start_percent}% predicted to start` : undefined} />
            {p.p_5plus !== null && <Stat label="Chance of 5+" value={`${Math.round(p.p_5plus * 100)}%`} sub={p.p_blank !== null ? `${Math.round(p.p_blank * 100)}% chance of a blank` : undefined} />}
            {p.solio_next !== null && <Stat label="Solio's number" value={p.solio_next.toFixed(1)} sub="independent projection, never fed into ours" />}
          </div>
          <div className="mt-6">
            <div className="mb-1 text-[12px] font-bold text-text-faint">Range for next gameweek</div>
            <div className="relative h-3 bg-raised">
              <div className="absolute inset-y-0 left-0 right-0 bg-broadcast-blue/40" />
              <div className="absolute inset-y-[-3px] w-1 bg-pitch-green" style={{ left: `${Math.min(98, Math.max(0, medianAt))}%` }} />
            </div>
            <div className="tabular mt-1 flex justify-between text-[12px] text-text-faint"><span>{p.floor.toFixed(1)}</span><span>median {p.xp_next.toFixed(1)}</span><span>{p.ceiling.toFixed(1)}</span></div>
          </div>
          <div className="mt-5">
            <FixtureRun fixtures={p.fixtures} max={5} showEvent />
          </div>
        </div>
        <div>
          {parts.length > 0 && (
            <>
              <div className="mb-2 text-[12px] font-bold text-text-faint">Where the next gameweek's points come from</div>
              <div className="flex h-5 w-full overflow-hidden bg-raised">
                {positive.map((x) => <div key={x.label} className={x.tone} style={{ width: `${(x.v / total) * 100}%` }} title={`${x.label} ${x.v.toFixed(2)}`} />)}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1">
                {parts.map((x) => (
                  <div key={x.label} className="flex items-center gap-2 text-xs">
                    <span className={`h-2 w-2 shrink-0 ${x.v > 0 ? x.tone : 'bg-alert-red'}`} />
                    <span className="text-text-muted">{x.label}</span>
                    <span className={`tabular ml-auto font-bold ${x.v < 0 ? 'text-alert-red' : 'text-text'}`}>{x.v.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
          {p.duties.length > 0 && <p className="mt-4 text-xs text-text-muted">First choice on: {p.duties.join(', ')} (FPL's own flag).</p>}
        </div>
      </div>
    </div>
  )
}
