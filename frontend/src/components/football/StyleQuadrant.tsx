import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { crestUrl } from '@/lib/api'
import type { TableRow, TableStyle } from '@/lib/types'

/** HOW THEY PLAY - every club on two measured dimensions of style, from the
 * shots of the matches the analyst has read. One dimension at a time; the
 * dashed lines are the league average, so a corner of the picture is a way of
 * playing, not a rank. Shares are weighted by the chances in them (a club's
 * dead-ball share is its dead-ball xG over its xG), never an average of match
 * percentages. The ledger on the Football screen says which of these carry from
 * one match to the next. */

type Dim = {
  key: string
  label: string
  x: { label: string; get: (s: TableStyle) => number | null; pct?: boolean; decimals: number }
  y: { label: string; get: (s: TableStyle) => number | null; pct?: boolean; decimals: number }
  corners: [string, string, string, string] // top-right, top-left, bottom-right, bottom-left
  note: string
}

const DIMS: Dim[] = [
  {
    key: 'dead',
    label: 'Dead balls',
    x: { label: 'share of xG created from dead balls', get: (s) => s.dead_for, pct: true, decimals: 0 },
    y: { label: 'share of xG conceded from dead balls', get: (s) => s.dead_against, pct: true, decimals: 0 },
    corners: ['LIVE AND DIE BY SET PLAYS', 'SOLID FROM SET PLAYS, OPEN-PLAY ATTACK', 'SET-PLAY ATTACK, OPEN-PLAY DEFENCE', 'OPEN PLAY BOTH WAYS'],
    note: 'Corners, free kicks, set pieces and throw-ins, as a share of the chances a club creates and concedes.',
  },
  {
    key: 'fast',
    label: 'Counter-attacks',
    x: { label: 'share of xG created on the break', get: (s) => s.fast_for, pct: true, decimals: 0 },
    y: { label: 'share of xG conceded on the break', get: (s) => s.fast_against, pct: true, decimals: 0 },
    corners: ['END-TO-END', 'EXPOSED ON THE BREAK', 'DANGEROUS ON THE BREAK', 'CONTROLLED BOTH WAYS'],
    note: 'Shots FotMob labels as fast breaks, as a share of the chances a club creates and concedes.',
  },
  {
    key: 'volume',
    label: 'Volume v quality',
    x: { label: 'shots per match', get: (s) => s.shots_per_match, decimals: 1 },
    y: { label: 'xG per shot', get: (s) => s.xg_per_shot, decimals: 3 },
    corners: ['MANY SHOTS, GOOD SHOTS', 'FEW SHOTS, GOOD SHOTS', 'MANY SHOTS, POOR SHOTS', 'FEW SHOTS, POOR SHOTS'],
    note: 'How many shots a club takes against what each one is worth. Which of these carries from match to match is on the Football screen.',
  },
  {
    key: 'box',
    label: 'Where from',
    x: { label: 'share of xG from inside the box', get: (s) => s.box_share, pct: true, decimals: 0 },
    y: { label: 'share of shots from outside the box', get: (s) => s.outside_shot_share, pct: true, decimals: 0 },
    corners: ['DISTANCE SHOOTERS WITH BOX CHANCES', 'SHOOT FROM RANGE', 'WORK THE BOX', 'PATIENT, BOX-ONLY'],
    note: 'Penalty box x >= 88.5 m and 13.84 <= y <= 54.16, FotMob coordinates.',
  },
]

const VW = 900
const VH = 520
const PAD = { l: 60, r: 40, t: 36, b: 48 }

export function StyleQuadrant({ rows }: { rows: TableRow[] }) {
  const [dimKey, setDimKey] = useState('dead')
  const [hover, setHover] = useState<number | null>(null)
  const dim = DIMS.find((d) => d.key === dimKey) ?? DIMS[0]

  const pts = useMemo(
    () =>
      rows
        .filter((r) => r.style)
        .map((r) => ({ r, x: dim.x.get(r.style as TableStyle), y: dim.y.get(r.style as TableStyle) }))
        .filter((p): p is { r: TableRow; x: number; y: number } => p.x !== null && p.y !== null),
    [rows, dim],
  )
  if (pts.length < 4) return null

  const pad = (lo: number, hi: number) => {
    const span = Math.max(hi - lo, 1e-6)
    return [lo - span * 0.08, hi + span * 0.08]
  }
  const [xMin, xMax] = pad(Math.min(...pts.map((p) => p.x)), Math.max(...pts.map((p) => p.x)))
  const [yMin, yMax] = pad(Math.min(...pts.map((p) => p.y)), Math.max(...pts.map((p) => p.y)))
  const xAvg = pts.reduce((a, p) => a + p.x, 0) / pts.length
  const yAvg = pts.reduce((a, p) => a + p.y, 0) / pts.length
  const sx = (v: number) => PAD.l + ((v - xMin) / (xMax - xMin)) * (VW - PAD.l - PAD.r)
  const sy = (v: number) => VH - PAD.b - ((v - yMin) / (yMax - yMin)) * (VH - PAD.t - PAD.b)
  const fmt = (v: number, a: Dim['x']) => (a.pct ? `${(v * 100).toFixed(a.decimals)}%` : v.toFixed(a.decimals))
  const h = hover !== null ? pts.find((p) => p.r.team_id === hover) ?? null : null
  const ticks = (lo: number, hi: number) => Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * (i + 0.5)) / 5)

  return (
    <div className="border-b border-divider">
      <div className="flex flex-wrap items-center gap-4 px-10 pt-6">
        <span className="text-[13px] font-bold text-text-faint">How they play</span>
        {DIMS.map((d) => (
          <button
            key={d.key}
            type="button"
            onClick={() => setDimKey(d.key)}
            className={`px-2.5 py-1 text-[12px] font-bold transition-colors ${dimKey === d.key ? 'bg-text text-void' : 'bg-raised text-text-muted hover:text-text'}`}
          >
            {d.label}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-[1fr_300px]">
        <div className="border-r border-divider px-8 py-4">
          <svg viewBox={`0 0 ${VW} ${VH}`} className="h-auto w-full select-none" role="img" aria-label={`Every club by ${dim.x.label} against ${dim.y.label}`} onMouseLeave={() => setHover(null)}>
            {ticks(xMin, xMax).map((v) => (
              <g key={`x${v}`}>
                <line x1={sx(v)} y1={PAD.t} x2={sx(v)} y2={VH - PAD.b} stroke="var(--divider)" strokeOpacity={0.45} />
                <text x={sx(v)} y={VH - PAD.b + 15} textAnchor="middle" fontSize={11} fill="var(--text-faint)" className="tabular">{fmt(v, dim.x)}</text>
              </g>
            ))}
            {ticks(yMin, yMax).map((v) => (
              <g key={`y${v}`}>
                <line x1={PAD.l} y1={sy(v)} x2={VW - PAD.r} y2={sy(v)} stroke="var(--divider)" strokeOpacity={0.45} />
                <text x={PAD.l - 8} y={sy(v) + 4} textAnchor="end" fontSize={11} fill="var(--text-faint)" className="tabular">{fmt(v, dim.y)}</text>
              </g>
            ))}
            <line x1={sx(xAvg)} y1={PAD.t} x2={sx(xAvg)} y2={VH - PAD.b} stroke="var(--text)" strokeOpacity={0.35} strokeDasharray="4 4" />
            <line x1={PAD.l} y1={sy(yAvg)} x2={VW - PAD.r} y2={sy(yAvg)} stroke="var(--text)" strokeOpacity={0.35} strokeDasharray="4 4" />
            <text x={VW - PAD.r - 4} y={PAD.t + 12} textAnchor="end" fontSize={10} fontWeight={700} letterSpacing="1.4" fill="var(--text-faint)">{dim.corners[0]}</text>
            <text x={PAD.l + 4} y={PAD.t + 12} fontSize={10} fontWeight={700} letterSpacing="1.4" fill="var(--text-faint)">{dim.corners[1]}</text>
            <text x={VW - PAD.r - 4} y={VH - PAD.b - 8} textAnchor="end" fontSize={10} fontWeight={700} letterSpacing="1.4" fill="var(--text-faint)">{dim.corners[2]}</text>
            <text x={PAD.l + 4} y={VH - PAD.b - 8} fontSize={10} fontWeight={700} letterSpacing="1.4" fill="var(--text-faint)">{dim.corners[3]}</text>
            <text x={(PAD.l + VW - PAD.r) / 2} y={VH - 8} textAnchor="middle" fontSize={10} fill="var(--text-faint)" letterSpacing="1.4">{dim.x.label.toUpperCase()} →</text>
            <text x={14} y={(PAD.t + VH - PAD.b) / 2} textAnchor="middle" fontSize={10} fill="var(--text-faint)" letterSpacing="1.4" transform={`rotate(-90 14 ${(PAD.t + VH - PAD.b) / 2})`}>{dim.y.label.toUpperCase()} →</text>
            {pts.map(({ r, x, y }) => {
              const cx = sx(x)
              const cy = sy(y)
              const crest = crestUrl(r.code)
              const dimmed = hover !== null && hover !== r.team_id
              return (
                <Link key={r.team_id} to={`/club/${r.team_id}`}>
                  <g style={{ opacity: dimmed ? 0.3 : 1, transition: 'opacity 150ms' }} className="cursor-pointer" onMouseEnter={() => setHover(r.team_id)}>
                    {r.mine && <circle cx={cx} cy={cy} r={19} fill="none" stroke="var(--broadcast-gold)" strokeWidth={2} />}
                    {hover === r.team_id && <circle cx={cx} cy={cy} r={21} fill="none" stroke="var(--text)" strokeWidth={1} />}
                    {crest ? <image href={crest} x={cx - 14} y={cy - 14} width={28} height={28} /> : <circle cx={cx} cy={cy} r={11} fill="var(--raised)" />}
                    <text x={cx} y={cy + 26} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--text)" fillOpacity={0.8} letterSpacing="0.8">{r.short}</text>
                  </g>
                </Link>
              )
            })}
          </svg>
        </div>
        <div className="px-6 py-6">
          {h ? (
            <div className="data-in">
              <div className="flex items-center gap-3">
                {crestUrl(h.r.code) && <img src={crestUrl(h.r.code) as string} alt="" className="h-9 w-9" />}
                <div>
                  <div className="font-display text-3xl font-bold leading-none text-text">{h.r.short}</div>
                  <div className="text-[12px] text-text-faint">{h.r.style?.matches} matches read</div>
                </div>
              </div>
              <div className="mt-5 space-y-3 text-sm">
                <div>
                  <div className="text-[12px] font-bold text-text-faint">{dim.x.label}</div>
                  <div className="tabular font-display text-2xl font-bold text-text">{fmt(h.x, dim.x)}</div>
                  <div className="tabular text-[12px] text-text-faint">league {fmt(xAvg, dim.x)}</div>
                </div>
                <div>
                  <div className="text-[12px] font-bold text-text-faint">{dim.y.label}</div>
                  <div className="tabular font-display text-2xl font-bold text-text">{fmt(h.y, dim.y)}</div>
                  <div className="tabular text-[12px] text-text-faint">league {fmt(yAvg, dim.y)}</div>
                </div>
              </div>
            </div>
          ) : (
            <div>
              <div className="text-[12px] font-bold text-text-faint">{dim.label}</div>
              <p className="mt-2 text-sm leading-relaxed text-text-muted">{dim.note}</p>
              <p className="mt-3 text-[13px] leading-relaxed text-text-faint">
                Measured over {pts.reduce((a, p) => a + (p.r.style?.matches ?? 0), 0) / 2} matches; the smaller a club&rsquo;s sample, the more one match can move it. Hover a crest.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
