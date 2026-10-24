import { Panel } from '@/components/ui/kit'
import { useLiveMeta } from '@/lib/useLiveMeta'

const W = 520
const H = 150
const PAD = { l: 8, r: 8, t: 14, b: 22 }

/** WHERE YOU STAND: points each gameweek against the average manager, and the overall-rank line beside it. The two answer
 * different questions (did the week beat the field; has the season moved), and together they say whether the team is
 * climbing or merely holding. Reads the series already on the live poll. */
export function SeasonRibbon() {
  const live = useLiveMeta()
  const gw = live?.charts?.gw_points
  const rank = live?.charts?.rank
  if (!gw || gw.events.length < 2) return null

  const n = gw.events.length
  const top = Math.max(...gw.you, ...gw.average.map((a) => a ?? 0), 1) * 1.1
  const bw = (W - PAD.l - PAD.r) / n
  const x = (i: number) => PAD.l + i * bw
  const y = (v: number) => PAD.t + (1 - v / top) * (H - PAD.t - PAD.b)
  const total = gw.you.reduce((a, b) => a + b, 0)
  const finished = gw.average.map((a, i) => (a !== null ? gw.you[i] - a : null)).filter((v): v is number => v !== null)
  const beat = finished.filter((v) => v > 0).length

  const rk = rank && rank.values.length >= 2 ? rank : null
  const rvals = rk ? rk.values.filter((v): v is number => v !== null) : []
  const rmax = Math.max(...rvals, 1)
  const rmin = Math.min(...rvals, rmax)
  const rx = (i: number) => PAD.l + (i / Math.max(1, rvals.length - 1)) * (W - PAD.l - PAD.r)
  const ry = (v: number) => PAD.t + ((v - rmin) / Math.max(1, rmax - rmin)) * (H - PAD.t - PAD.b)
  const latest = rvals[rvals.length - 1]
  const prev = rvals[rvals.length - 2]
  const fmt = (v: number) => (v >= 1_000_000 ? `${(v / 1_000_000).toFixed(2)}m` : `${Math.round(v / 1000)}k`)

  return (
    <Panel
      title="Where you stand"
      sub={`${total} points after ${n} gameweeks. You beat the average manager in ${beat} of ${finished.length} finished weeks.`}
    >
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div>
          <div className="mb-1 text-[13px] text-text-faint">Points each gameweek <span className="text-text-faint/70">(ticks mark the average manager)</span></div>
          <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Points each gameweek against the average manager">
            {gw.you.map((v, i) => {
              const avg = gw.average[i]
              const above = avg === null ? null : v >= avg
              const fill = above === null ? 'var(--text-faint)' : above ? 'var(--pitch-green)' : 'var(--alert-red)'
              return (
                <g key={gw.events[i]}>
                  <rect x={x(i) + bw * 0.16} y={y(v)} width={bw * 0.68} height={H - PAD.b - y(v)} rx={2} fill={fill} opacity={avg === null ? 0.45 : 0.9} />
                  {avg !== null && <line x1={x(i) + bw * 0.08} x2={x(i) + bw * 0.92} y1={y(avg)} y2={y(avg)} stroke="var(--text)" strokeWidth={2} />}
                  <text x={x(i) + bw / 2} y={H - 7} textAnchor="middle" fontSize={10} fill="var(--text-faint)">{gw.events[i]}</text>
                  <text x={x(i) + bw / 2} y={y(v) - 3} textAnchor="middle" fontSize={10} fill="var(--text-muted)">{v}</text>
                </g>
              )
            })}
          </svg>
        </div>
        {rk && rvals.length >= 2 && (
          <div>
            <div className="mb-1 flex items-baseline justify-between text-[13px] text-text-faint">
              <span>Overall rank</span>
              <span className="tabular">
                <span className="font-display text-lg font-semibold text-text">{fmt(latest)}</span>
                {prev !== undefined && (
                  <span className={latest < prev ? 'ml-2 text-pitch-green' : 'ml-2 text-alert-red'}>
                    {latest < prev ? '▲' : '▼'} {fmt(Math.abs(prev - latest))}
                  </span>
                )}
              </span>
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Overall rank by gameweek, better is higher">
              <polyline
                fill="none"
                stroke="var(--broadcast-blue)"
                strokeWidth={2.5}
                strokeLinejoin="round"
                points={rvals.map((v, i) => `${rx(i)},${ry(v)}`).join(' ')}
              />
              {rvals.map((v, i) => (
                <circle key={i} cx={rx(i)} cy={ry(v)} r={i === rvals.length - 1 ? 4.5 : 3} fill="var(--broadcast-blue)" />
              ))}
              <text x={PAD.l} y={H - 7} fontSize={10} fill="var(--text-faint)">GW{rk.events[0]}</text>
              <text x={W - PAD.r} y={H - 7} textAnchor="end" fontSize={10} fill="var(--text-faint)">GW{rk.events[rk.events.length - 1]}</text>
              <text x={PAD.l} y={PAD.t - 3} fontSize={10} fill="var(--text-faint)">{fmt(rmin)} (best)</text>
            </svg>
          </div>
        )}
      </div>
    </Panel>
  )
}
