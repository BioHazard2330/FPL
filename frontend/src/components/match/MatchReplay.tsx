import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MatchStory, StoryGoal, StoryShot, StorySide } from '@/lib/types'

/** THE REPLAY - the match, scrubbed.
 *
 * One pitch, both sides, drawn in metres so FotMob's shot coordinates land on
 * it untouched. The home side attacks the right-hand goal as recorded; the
 * away side's coordinates are mirrored (x -> 105 - x, y -> 68 - y) so both
 * attack their own end of one pitch. Dot area is xG, a filled dot is a goal.
 *
 * Under the pitch sits the match's spine: cumulative xG for both sides, the
 * game state as a band (who led, when), every goal, substitution and card at
 * its minute. The cursor is the minute: drag it, use the arrow keys, or press
 * play. Everything above the cursor is what had happened by then and nothing
 * is predicted. The pitch, the score and the running xG all follow it. */

const L = 105
const W = 68
const PEN_D = 16.5
const PEN_W = 40.32
const SIX_D = 5.5
const SIX_W = 18.32
const SPOT = 11
const R = 9.15
const CY = W / 2
const CHALK = 'rgba(245, 243, 238, 0.30)'
const TURF_A = '#0d2f1f'
const TURF_B = '#113a26'

const SIDE_INK: Record<StorySide, string> = { home: 'var(--pitch-green)', away: 'var(--broadcast-blue)' }

const KIND_INK: Record<string, string> = {
  INJURY_LINKED: 'var(--alert-red)',
  EARLY_UNEXPLAINED: 'var(--alert-red)',
  CHASING: 'var(--broadcast-gold)',
  TACTICAL: 'var(--broadcast-gold)',
  PROTECTING_LEAD: 'var(--broadcast-blue)',
}

function project(s: StoryShot): { px: number; py: number } | null {
  if (s.x === null || s.y === null) return null
  return s.side === 'home' ? { px: s.x, py: s.y } : { px: L - s.x, py: W - s.y }
}

function arcD(goalSide: 'left' | 'right'): string {
  const dir = goalSide === 'right' ? 1 : -1
  const spotX = goalSide === 'right' ? L - SPOT : SPOT
  const edge = goalSide === 'right' ? L - PEN_D : PEN_D
  const dy = Math.sqrt(Math.max(0, R * R - (spotX - edge) ** 2))
  const sweep = dir === 1 ? 0 : 1
  return `M ${edge} ${CY - dy} A ${R} ${R} 0 0 ${sweep} ${edge} ${CY + dy}`
}

function Turf() {
  const stripes = []
  const bands = 14
  for (let i = 0; i < bands; i++) {
    stripes.push(<rect key={i} x={(i * L) / bands} y={0} width={L / bands + 0.02} height={W} fill={i % 2 === 0 ? TURF_A : TURF_B} />)
  }
  const line = { stroke: CHALK, strokeWidth: 0.2, fill: 'none' } as const
  return (
    <g>
      {stripes}
      <rect x={0} y={0} width={L} height={W} {...line} />
      <line x1={L / 2} y1={0} x2={L / 2} y2={W} {...line} />
      <circle cx={L / 2} cy={CY} r={R} {...line} />
      <circle cx={L / 2} cy={CY} r={0.35} fill={CHALK} />
      {(['left', 'right'] as const).map((side) => {
        const x0 = side === 'right' ? L - PEN_D : 0
        const sx0 = side === 'right' ? L - SIX_D : 0
        const spot = side === 'right' ? L - SPOT : SPOT
        const gx = side === 'right' ? L : -1.8
        return (
          <g key={side}>
            <rect x={x0} y={CY - PEN_W / 2} width={PEN_D} height={PEN_W} {...line} />
            <rect x={sx0} y={CY - SIX_W / 2} width={SIX_D} height={SIX_W} {...line} />
            <circle cx={spot} cy={CY} r={0.35} fill={CHALK} />
            <path d={arcD(side)} {...line} />
            <rect x={gx} y={CY - 3.66} width={1.8} height={7.32} stroke={CHALK} strokeWidth={0.18} fill="rgba(245,243,238,0.05)" />
          </g>
        )
      })}
    </g>
  )
}

function minuteOfShot(s: StoryShot): number {
  return s.m ?? 0
}

function stateSegments(goals: StoryGoal[], length: number): { from: number; to: number; lead: StorySide | null }[] {
  const segs: { from: number; to: number; lead: StorySide | null }[] = []
  let h = 0
  let a = 0
  let from = 0
  const sorted = [...goals].sort((x, y) => x.minute - y.minute)
  const lead = () => (h > a ? 'home' : a > h ? 'away' : null)
  for (const g of sorted) {
    const before = lead()
    if (g.minute > from) segs.push({ from, to: g.minute, lead: before })
    if (g.side === 'home') h += 1
    else a += 1
    from = Math.max(from, g.minute)
  }
  segs.push({ from, to: length, lead: lead() })
  return segs
}

type Props = { story: MatchStory; homeShort: string; awayShort: string; homeId: number }

export function MatchReplay({ story, homeShort, awayShort }: Props) {
  const length = Math.max(90, story.length)
  const [minute, setMinute] = useState<number>(length)
  const [playing, setPlaying] = useState(false)
  const [hover, setHover] = useState<StoryShot | null>(null)
  const raf = useRef<number | null>(null)
  const last = useRef<number>(0)
  const timelineRef = useRef<SVGSVGElement | null>(null)
  const dragging = useRef(false)

  const reducedMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

  const shots = useMemo(() => story.shots.filter((s) => s.m !== null && s.x !== null && s.y !== null), [story.shots])
  const goals = story.timeline

  const stop = useCallback(() => {
    if (raf.current !== null) cancelAnimationFrame(raf.current)
    raf.current = null
    setPlaying(false)
  }, [])

  useEffect(() => {
    if (!playing) return
    last.current = performance.now()
    const tick = (now: number) => {
      const dt = (now - last.current) / 1000
      last.current = now
      let reached = false
      setMinute((m) => {
        const next = m + dt * 11
        if (next >= length) {
          reached = true
          return length
        }
        return next
      })
      if (reached) {
        setPlaying(false)
        return
      }
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current)
    }
  }, [playing, length])

  const cur = Math.round(minute)
  const visibleShots = useMemo(() => shots.filter((s) => minuteOfShot(s) <= cur), [shots, cur])
  const revealedGoals = goals.filter((g) => g.minute <= cur)
  const score: [number, number] = revealedGoals.length ? revealedGoals[revealedGoals.length - 1].score : [0, 0]
  const cumulative = useMemo(() => {
    let h = 0
    let a = 0
    for (const s of visibleShots) {
      if (s.side === 'home') h += s.xg
      else a += s.xg
    }
    return { home: h, away: a }
  }, [visibleShots])

  const totals = useMemo(() => {
    let h = 0
    let a = 0
    for (const s of shots) {
      if (s.side === 'home') h += s.xg
      else a += s.xg
    }
    return { home: h, away: a, max: Math.max(h, a, 0.5) }
  }, [shots])

  const steps = useMemo(() => {
    const build = (side: StorySide) => {
      let c = 0
      const pts: [number, number][] = [[0, 0]]
      for (const s of shots.filter((x) => x.side === side).sort((x, y) => minuteOfShot(x) - minuteOfShot(y))) {
        pts.push([minuteOfShot(s), c])
        c += s.xg
        pts.push([minuteOfShot(s), c])
      }
      pts.push([length, c])
      return pts
    }
    return { home: build('home'), away: build('away') }
  }, [shots, length])

  const TW = 1000
  const TH = 190
  const PADL = 52
  const PADR = 14
  const BAND_Y = 6
  const CHART_T = 30
  const CHART_B = 128
  const sx = (m: number) => PADL + (m / length) * (TW - PADL - PADR)
  const sy = (v: number) => CHART_B - (v / (totals.max * 1.12)) * (CHART_B - CHART_T)
  const pathOf = (pts: [number, number][], upto?: number) => {
    const out: string[] = []
    pts.forEach(([m, v], i) => {
      if (upto !== undefined && m > upto) return
      out.push(`${i === 0 ? 'M' : 'L'} ${sx(m).toFixed(1)} ${sy(v).toFixed(1)}`)
    })
    if (upto !== undefined && out.length) {
      const pts2 = pts.filter(([m]) => m <= upto)
      const lastVal = pts2[pts2.length - 1]?.[1] ?? 0
      out.push(`L ${sx(upto).toFixed(1)} ${sy(lastVal).toFixed(1)}`)
    }
    return out.join(' ')
  }

  const segs = useMemo(() => stateSegments(goals, length), [goals, length])

  const setFromEvent = (clientX: number) => {
    const svg = timelineRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const px = ((clientX - rect.left) / rect.width) * TW
    const m = ((px - PADL) / (TW - PADL - PADR)) * length
    setMinute(Math.max(0, Math.min(length, m)))
  }

  const onKey = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 10 : 1
    if (e.key === 'ArrowRight') setMinute((m) => Math.min(length, Math.round(m) + step))
    else if (e.key === 'ArrowLeft') setMinute((m) => Math.max(0, Math.round(m) - step))
    else if (e.key === 'Home') setMinute(0)
    else if (e.key === 'End') setMinute(length)
    else if (e.key === ' ') {
      e.preventDefault()
      setPlaying((p) => !p)
    } else return
    e.preventDefault()
  }

  const latest = useMemo(() => {
    type Item = { minute: number; text: string; side: StorySide }
    const items: Item[] = []
    for (const g of goals) {
      const shot = story.shots.find((s) => s.o === 'Goal' && s.m === g.minute && s.side === g.side)
      const who = g.own_goal ? 'own goal' : `${g.player_name ?? shot?.name ?? 'goal'}${g.penalty ? ' (penalty)' : ''}`
      items.push({ minute: g.minute, text: `Goal, ${who}${shot ? ` · ${shot.xg.toFixed(2)} xG` : ''}`, side: g.side })
    }
    for (const c of story.cards) items.push({ minute: c.minute, text: `Card, ${c.name ?? 'player'}`, side: c.side })
    for (const s of story.subs) items.push({ minute: s.minute, text: `${s.on} on for ${s.off}`, side: s.side })
    return items.filter((i) => i.minute <= cur).sort((a, b) => b.minute - a.minute).slice(0, 4)
  }, [goals, story.cards, story.subs, story.shots, cur])

  const nearest = visibleShots.slice(-1)[0]

  return (
    <div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_280px]">
        <div>
          <div className="relative">
            <svg viewBox={`-1.8 -1.5 ${L + 3.6} ${W + 3}`} className="block h-auto w-full select-none" role="img" aria-label="Both sides' shots on one pitch, shown up to the chosen minute" onMouseLeave={() => setHover(null)}>
              <Turf />
              <text x={3} y={5.4} fontSize={3.1} fontWeight={800} letterSpacing="0.25" fill="var(--broadcast-blue)" opacity={0.85}>{awayShort.toUpperCase()}</text>
              <text x={L - 3} y={5.4} fontSize={3.1} fontWeight={800} letterSpacing="0.25" fill="var(--pitch-green)" textAnchor="end" opacity={0.85}>{homeShort.toUpperCase()}</text>
              {visibleShots.map((s, i) => {
                const p = project(s)
                if (!p) return null
                const r = 0.5 + Math.sqrt(s.xg) * 2.2
                const goal = s.o === 'Goal'
                const post = s.o === 'Post'
                const ink = SIDE_INK[s.side]
                const recent = cur - minuteOfShot(s) <= 2
                return (
                  <g key={`${s.m}-${i}`} onMouseEnter={() => setHover(s)} style={{ cursor: 'default' }}>
                    {recent && <circle cx={p.px} cy={p.py} r={r + 1.1} fill="none" stroke={ink} strokeWidth={0.18} opacity={0.7} />}
                    <circle
                      cx={p.px}
                      cy={p.py}
                      r={r}
                      fill={goal ? ink : ink}
                      fillOpacity={goal ? 1 : 0.28}
                      stroke={goal ? '#fff' : post ? 'var(--broadcast-gold)' : ink}
                      strokeWidth={goal ? 0.3 : post ? 0.32 : 0.2}
                    />
                  </g>
                )
              })}
            </svg>
            {hover && (() => {
              const p = project(hover)
              if (!p) return null
              const left = ((p.px + 1.8) / (L + 3.6)) * 100
              const top = ((p.py + 1.5) / (W + 3)) * 100
              return (
                <div
                  className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap border border-divider bg-panel px-2.5 py-1.5 text-[12px] shadow-lg"
                  style={{ left: `${Math.min(88, Math.max(12, left))}%`, top: `${Math.max(14, top - 2)}%` }}
                >
                  <div className="font-bold text-text">{hover.name ?? 'Unknown'} <span className="tabular text-text-faint">{hover.m}'</span></div>
                  <div className="tabular text-text-muted">
                    {hover.xg.toFixed(2)} xG · {hover.sit ?? '?'} · {hover.type ?? '?'} · {hover.o ?? '?'}
                  </div>
                </div>
              )
            })()}
          </div>

          <div className="mt-3 flex items-center gap-4">
            <button
              type="button"
              onClick={() => {
                if (playing) stop()
                else {
                  if (minute >= length) setMinute(0)
                  setPlaying(true)
                }
              }}
              className="shrink-0 border border-divider bg-raised px-3 py-1.5 text-[12px] font-bold uppercase tracking-[0.12em] text-text transition-colors hover:border-pitch-green hover:text-pitch-green"
              aria-label={playing ? 'Pause the replay' : 'Play the replay'}
            >
              {playing ? 'Pause' : minute >= length ? 'Replay' : 'Play'}
            </button>
            <span className="text-[12px] text-text-faint">
              {reducedMotion ? 'Drag the cursor along the match.' : 'Drag along the match, use the arrow keys, or press play.'}
            </span>
          </div>

          <svg
            ref={timelineRef}
            viewBox={`0 0 ${TW} ${TH}`}
            className="mt-2 block h-auto w-full cursor-ew-resize touch-none select-none outline-none focus-visible:ring-1 focus-visible:ring-pitch-green"
            role="slider"
            tabIndex={0}
            aria-label="Match minute"
            aria-valuemin={0}
            aria-valuemax={length}
            aria-valuenow={cur}
            aria-valuetext={`Minute ${cur}`}
            onKeyDown={onKey}
            onPointerDown={(e) => {
              dragging.current = true
              stop()
              ;(e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId)
              setFromEvent(e.clientX)
            }}
            onPointerMove={(e) => {
              if (dragging.current) setFromEvent(e.clientX)
            }}
            onPointerUp={() => {
              dragging.current = false
            }}
          >
            {/* game state band: who was ahead, when */}
            {segs.map((sg, i) => (
              <rect
                key={i}
                x={sx(sg.from)}
                y={BAND_Y}
                width={Math.max(0, sx(sg.to) - sx(sg.from))}
                height={8}
                fill={sg.lead === 'home' ? 'var(--pitch-green)' : sg.lead === 'away' ? 'var(--broadcast-blue)' : 'var(--divider)'}
                opacity={sg.lead ? 0.85 : 1}
              />
            ))}
            <text x={PADL - 8} y={BAND_Y + 7} textAnchor="end" fontSize={11} fontWeight={700} fill="var(--text-faint)" letterSpacing="1">LEAD</text>

            {/* xG axis */}
            {[0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5].filter((v) => v <= totals.max * 1.1).map((v) => (
              <g key={v}>
                <line x1={PADL} x2={TW - PADR} y1={sy(v)} y2={sy(v)} stroke="var(--divider)" strokeOpacity={0.55} />
                <text x={PADL - 8} y={sy(v) + 3} textAnchor="end" fontSize={11} fill="var(--text-faint)" className="tabular">{v}</text>
              </g>
            ))}
            {[0, 15, 30, 45, 60, 75, 90].filter((m) => m <= length).map((m) => (
              <g key={m}>
                <line x1={sx(m)} x2={sx(m)} y1={CHART_T} y2={CHART_B} stroke="var(--divider)" strokeOpacity={m === 45 ? 0.9 : 0.35} />
                <text x={sx(m)} y={CHART_B + 16} textAnchor="middle" fontSize={11} fill="var(--text-faint)" className="tabular">{m}'</text>
              </g>
            ))}

            {/* the whole race, faint; the revealed part, solid */}
            <path d={pathOf(steps.away)} fill="none" stroke="var(--broadcast-blue)" strokeWidth={1.4} opacity={0.25} />
            <path d={pathOf(steps.home)} fill="none" stroke="var(--pitch-green)" strokeWidth={1.4} opacity={0.25} />
            <path d={pathOf(steps.away, cur)} fill="none" stroke="var(--broadcast-blue)" strokeWidth={2.4} strokeLinejoin="round" />
            <path d={pathOf(steps.home, cur)} fill="none" stroke="var(--pitch-green)" strokeWidth={2.4} strokeLinejoin="round" />

            {/* events */}
            {goals.map((g, i) => {
              const pts = steps[g.side]
              const val = pts.filter(([m]) => m <= g.minute).slice(-1)[0]?.[1] ?? 0
              return (
                <g key={`g${i}`} opacity={g.minute <= cur ? 1 : 0.35}>
                  <circle cx={sx(g.minute)} cy={sy(val)} r={5.2} fill={g.own_goal ? 'var(--raised)' : SIDE_INK[g.side]} stroke="#fff" strokeWidth={1.4} />
                  {g.own_goal && <text x={sx(g.minute)} y={sy(val) + 2.6} textAnchor="middle" fontSize={6.5} fontWeight={800} fill="var(--text)">OG</text>}
                </g>
              )
            })}
            {story.subs.map((s, i) => (
              <rect key={`s${i}`} x={sx(s.minute) - 1.6} y={CHART_B + 26} width={3.2} height={10} fill={KIND_INK[s.kind] ?? 'var(--text-faint)'} opacity={s.minute <= cur ? 0.95 : 0.35}>
                <title>{`${s.minute}' ${s.on} on for ${s.off} (${s.kind.replace(/_/g, ' ').toLowerCase()})`}</title>
              </rect>
            ))}
            {story.cards.map((c, i) => (
              <rect key={`c${i}`} x={sx(c.minute) - 2.2} y={CHART_B + 40} width={4.4} height={7} fill="var(--broadcast-gold)" opacity={c.minute <= cur ? 1 : 0.35}>
                <title>{`${c.minute}' card, ${c.name ?? 'player'}`}</title>
              </rect>
            ))}
            <text x={PADL - 8} y={CHART_B + 35} textAnchor="end" fontSize={10} fontWeight={700} fill="var(--text-faint)" letterSpacing="0.5">SUBS</text>
            <text x={PADL - 8} y={CHART_B + 47} textAnchor="end" fontSize={10} fontWeight={700} fill="var(--text-faint)" letterSpacing="0.5">CARDS</text>

            {/* the cursor */}
            <line x1={sx(cur)} x2={sx(cur)} y1={BAND_Y - 2} y2={CHART_B + 4} stroke="var(--text)" strokeWidth={1.4} />
            <rect x={sx(cur) - 17} y={BAND_Y + 9} width={34} height={17} fill="var(--text)" />
            <text x={sx(cur)} y={BAND_Y + 21.5} textAnchor="middle" fontSize={12} fontWeight={800} fill="var(--void)" className="tabular">{cur}'</text>
          </svg>
        </div>

        <aside className="space-y-5 border-t border-divider pt-5 xl:border-l xl:border-t-0 xl:pl-6 xl:pt-0">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">At minute {cur}</div>
            <div className="mt-1 flex items-baseline justify-center gap-4 xl:justify-start">
              <span className="tabular font-display text-6xl font-bold leading-none text-text">{score[0]}</span>
              <span className="font-display text-3xl text-text-faint">-</span>
              <span className="tabular font-display text-6xl font-bold leading-none text-text">{score[1]}</span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-3">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-pitch-green">{homeShort} xG</div>
                <div className="tabular font-display text-3xl font-bold text-text">{cumulative.home.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-broadcast-blue">{awayShort} xG</div>
                <div className="tabular font-display text-3xl font-bold text-text">{cumulative.away.toFixed(2)}</div>
              </div>
            </div>
          </div>
          <div>
            <div className="mb-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">Latest</div>
            {latest.length === 0 ? (
              <div className="text-[13px] text-text-faint">Nothing yet.</div>
            ) : (
              <ul className="space-y-1.5">
                {latest.map((it, i) => (
                  <li key={i} className="flex gap-2 text-[13px]">
                    <span className="tabular w-8 shrink-0 text-right font-bold text-text-muted">{it.minute}'</span>
                    <span className={`mt-1.5 size-1.5 shrink-0 ${it.side === 'home' ? 'bg-pitch-green' : 'bg-broadcast-blue'}`} />
                    <span className="min-w-0 text-text">{it.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {nearest && (
            <div className="border-t border-divider pt-4 text-[12px] text-text-faint">
              Last shot: <span className="font-bold text-text-muted">{nearest.name ?? '?'}</span>, minute {nearest.m}, {nearest.xg.toFixed(2)} xG.
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
