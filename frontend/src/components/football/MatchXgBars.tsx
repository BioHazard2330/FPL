/** Chances for and against, match by match: a green bar for the xG a club created, a red one for what it allowed, opponent
 * underneath. Oldest on the left. A club that wins on chances shows green taller than red across the run; one living on
 * finishing shows results the bars do not explain. */
export function MatchXgBars({ matches }: { matches: { xg: number | null; xga: number | null; opponent_short: string }[] }) {
  const rows = matches.filter((m) => m.xg !== null && m.xga !== null)
  if (rows.length === 0) return null
  const top = Math.max(1, ...rows.flatMap((m) => [m.xg as number, m.xga as number]))
  const H = 140
  return (
    <div className="flex items-end gap-3 overflow-x-auto pb-1" style={{ minHeight: H + 40 }}>
      {rows.map((m, i) => (
        <div key={i} className="flex flex-col items-center">
          <div className="flex items-end gap-1" style={{ height: H }}>
            <div className="w-3.5 rounded-t-sm bg-pitch-green" style={{ height: `${((m.xg as number) / top) * H}px` }} title={`${(m.xg as number).toFixed(2)} xG created`} />
            <div className="w-3.5 rounded-t-sm bg-alert-red" style={{ height: `${((m.xga as number) / top) * H}px` }} title={`${(m.xga as number).toFixed(2)} xG allowed`} />
          </div>
          <div className="tabular mt-1.5 text-[11px] text-text-faint">{(m.xg as number).toFixed(1)}</div>
          <div className="text-[12px] font-semibold text-text-muted">{m.opponent_short}</div>
        </div>
      ))}
    </div>
  )
}
