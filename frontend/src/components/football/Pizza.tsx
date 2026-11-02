import type { ScoutingMeasure } from '@/lib/types'

/** PIZZA - the scouting percentiles as a radial chart: one slice per measure, its length the percentile within his
 * position, coloured by what it measures (shooting, creating, defending, overall), with the percentile on the crust.
 * A second player's slices (`other`) are drawn as an outline over the first, for Compare. */

const GROUP: Record<string, 'shoot' | 'create' | 'defend' | 'overall'> = {
  npxg90: 'shoot', shots90: 'shoot', xg_per_shot: 'shoot', big_chances90: 'shoot', placement: 'shoot',
  xa90: 'create', key_passes90: 'create',
  defcon90: 'defend', prevented90: 'defend', saves90: 'defend',
  rating: 'overall', bps90: 'overall',
}
const FILL: Record<string, string> = { shoot: '#ff4614', create: '#e8a800', defend: '#1c3fd1', overall: '#0b7d40' }
const SHORT: Record<string, string> = {
  npxg90: 'npxG', shots90: 'Shots', xg_per_shot: 'xG/shot', big_chances90: 'Big chances', placement: 'Placement',
  xa90: 'xA', key_passes90: 'Key passes', defcon90: 'Def. actions', prevented90: 'Prevented', saves90: 'Saves',
  rating: 'Rating', bps90: 'BPS',
}

function slice(cx: number, cy: number, r0: number, r1: number, a0: number, a1: number): string {
  const p = (r: number, a: number) => `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`
  const large = a1 - a0 > Math.PI ? 1 : 0
  return `M${p(r0, a0)} L${p(r1, a0)} A${r1},${r1} 0 ${large} 1 ${p(r1, a1)} L${p(r0, a1)} A${r0},${r0} 0 ${large} 0 ${p(r0, a0)} Z`
}

export function Pizza({ measures, other, size = 380 }: { measures: ScoutingMeasure[]; other?: ScoutingMeasure[] | null; size?: number }) {
  const ms = measures.filter((m) => m.kind === 'quality' && m.percentile !== null)
  if (ms.length < 3) return null
  const otherBy = new Map((other ?? []).map((m) => [m.key, m.percentile]))
  const S = 400, c = S / 2, r0 = 34, rMax = 150
  const step = (Math.PI * 2) / ms.length
  const gap = 0.025
  return (
    <svg viewBox={`-55 -12 ${S + 110} ${S + 24}`} width={size * 1.27} height={size} className="pizza max-w-full" role="img" aria-label="Percentiles within his position">
      {[25, 50, 75, 100].map((q) => (
        <circle key={q} cx={c} cy={c} r={r0 + ((rMax - r0) * q) / 100} fill="none" stroke="var(--ink)" strokeOpacity={q === 100 ? 0.5 : 0.14} strokeDasharray={q === 100 ? undefined : '3 4'} />
      ))}
      {ms.map((m, i) => {
        const a0 = -Math.PI / 2 + i * step + gap, a1 = -Math.PI / 2 + (i + 1) * step - gap
        const r = r0 + ((rMax - r0) * (m.percentile ?? 0)) / 100
        const g = GROUP[m.key] ?? 'overall'
        const mid = (a0 + a1) / 2
        const lx = c + (rMax + 30) * Math.cos(mid), ly = c + (rMax + 30) * Math.sin(mid)
        const bx = c + Math.max(r - 13, r0 + 12) * Math.cos(mid), by = c + Math.max(r - 13, r0 + 12) * Math.sin(mid)
        const o = otherBy.get(m.key)
        return (
          <g key={m.key} className="pizza-slice" style={{ animationDelay: `${i * 60}ms` }}>
            <path d={slice(c, c, r0, rMax, a0, a1)} fill={FILL[g]} fillOpacity={0.08} />
            <path d={slice(c, c, r0, r, a0, a1)} fill={FILL[g]} stroke="var(--ink)" strokeWidth={1.5}>
              <title>{`${m.label}: ${m.display} (${m.percentile}th percentile)`}</title>
            </path>
            {o !== undefined && o !== null && (
              <path d={slice(c, c, r0, r0 + ((rMax - r0) * o) / 100, a0, a1)} fill="none" stroke="var(--ink)" strokeWidth={2.5} strokeDasharray="5 3" />
            )}
            <circle cx={bx} cy={by} r={11} fill="var(--paper)" stroke="var(--ink)" strokeWidth={1.5} />
            <text x={bx} y={by + 4} textAnchor="middle" fontSize={11} fontWeight={900} fill="var(--ink)" fontFamily="Big Shoulders Display, Impact, sans-serif">{m.percentile}</text>
            <text x={lx} y={ly + 4} textAnchor="middle" fontSize={12} fontWeight={800} fill="var(--text)">{SHORT[m.key] ?? m.label}</text>
          </g>
        )
      })}
      <circle cx={c} cy={c} r={r0 - 4} fill="var(--ink)" />
      <text x={c} y={c + 5} textAnchor="middle" fontSize={13} fontWeight={900} fill="var(--paper)" fontFamily="Big Shoulders Display, Impact, sans-serif">PCT</text>
    </svg>
  )
}

export function PizzaLegend() {
  return (
    <div className="flex flex-wrap gap-3 text-[11.5px] text-text-muted">
      {[['shoot', 'shooting'], ['create', 'creating'], ['defend', 'defending'], ['overall', 'overall']].map(([k, l]) => (
        <span key={k} className="flex items-center gap-1.5"><span className="inline-block size-3 border border-ink" style={{ background: FILL[k] }} />{l}</span>
      ))}
    </div>
  )
}
