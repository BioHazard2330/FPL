import type { MatchRebuild } from '@/lib/types'

const W = 360
const H = 120
const PAD = { l: 22, r: 8, t: 8, b: 18 }

/** Cumulative expected goals against the clock for both sides, with a ring on
 * every goal. A line that climbs steadily is chance creation; a ring sitting
 * well below its line is a goal that came from a small chance, and a long flat
 * stretch with the other line rising is the match tilting. Home is green, away
 * blue, on one shared scale so the gap between the lines is the xG gap. */
export function XgRace({ match }: { match: MatchRebuild }) {
  const end = Math.max(90, ...match.shots.map((s) => s.minute))
  const build = (side: 'home' | 'away') => {
    let cum = 0
    const pts: { minute: number; cum: number; goal: boolean }[] = [{ minute: 0, cum: 0, goal: false }]
    for (const s of match.shots.filter((q) => q.side === side)) {
      pts.push({ minute: s.minute, cum, goal: false })
      cum += s.xg
      pts.push({ minute: s.minute, cum, goal: s.goal })
    }
    pts.push({ minute: end, cum, goal: false })
    return pts
  }
  const home = build('home')
  const away = build('away')
  const top = Math.max(home[home.length - 1].cum, away[away.length - 1].cum, 1) * 1.1
  const x = (m: number) => PAD.l + (m / end) * (W - PAD.l - PAD.r)
  const y = (v: number) => H - PAD.b - (v / top) * (H - PAD.t - PAD.b)
  const line = (pts: { minute: number; cum: number }[]) => pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(p.minute)} ${y(p.cum)}`).join(' ')
  const yTicks = [0, 1, 2, 3].filter((t) => t <= top)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full select-none" role="img" aria-label={`Cumulative xG, ${match.home.short} against ${match.away.short}`}>
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="var(--divider)" strokeOpacity={0.5} />
          <text x={PAD.l - 4} y={y(t) + 3} textAnchor="end" fontSize={8} fill="var(--text-faint)" className="tabular">{t}</text>
        </g>
      ))}
      {[45, 90].map((m) => (
        <text key={m} x={x(m)} y={H - 5} textAnchor="middle" fontSize={8} fill="var(--text-faint)">{m}'</text>
      ))}
      <line x1={x(45)} x2={x(45)} y1={PAD.t} y2={H - PAD.b} stroke="var(--divider)" strokeDasharray="2 3" />
      <path d={line(away)} fill="none" stroke="var(--broadcast-blue)" strokeWidth={2} />
      <path d={line(home)} fill="none" stroke="var(--pitch-green)" strokeWidth={2} />
      {[{ pts: home, c: 'var(--pitch-green)' }, { pts: away, c: 'var(--broadcast-blue)' }].flatMap(({ pts, c }) =>
        pts.filter((p) => p.goal).map((p, i) => <circle key={`${c}${i}${p.minute}`} cx={x(p.minute)} cy={y(p.cum)} r={4} fill="var(--void)" stroke={c} strokeWidth={2} />),
      )}
    </svg>
  )
}
