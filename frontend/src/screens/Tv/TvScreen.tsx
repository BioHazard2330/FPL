import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import confetti from 'canvas-confetti'
import { PitchFor, TvCups, anyInPlay, useLiveMatches } from '@/components/match/PlayByPlay'
import { Odometer } from '@/components/ui/Odometer'
import { Flap } from '@/components/ui/Flap'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { DepartureBoard } from '@/components/live/DepartureBoard'
import { crestUrl, fetchLiveSnapshot, getJson } from '@/lib/api'
import { useCrowd } from '@/lib/crowd'
import { useFetch } from '@/lib/useFetch'
import type { LiveMatch, LiveSnapshot, LiveSquadPlayer } from '@/lib/types'

/** MATCHDAY TV - the gameweek as a broadcast for a second screen (rebuilt 2026-11-27).
 *  Left: the scoreboard - your points, your edge on the top 10k, the rank, the armband.
 *  Centre: your eleven on a pitch, each player's live points on his plate, pulsing while his match is on, goals, assists
 *  and cards stamped on him, the bench beneath.
 *  Right: the matches - FotMob's live tracker for the selected one, then a card per match with the minute, the score, your
 *  players in it and what the next goal at either end is worth to you against the top 10k.
 *  Bottom: who is helping and hurting you, then the events crawl. A goal or assist by one of yours takes the screen. */

interface Splash { id: number; kind: 'GOAL' | 'ASSIST' | 'RED CARD'; name: string; points: number; captain: boolean; photo?: number | null; team?: number | null
  shot?: { x: number; y: number; gy: number | null; gz: number | null } | null }
interface SwingSide { short: string; code: number | null; goals: number; next_goal: number }
interface SwingCard { fixture: number; status: string; minute: number | null; home: SwingSide; away: SwingSide; cheer: string | null }
interface Mover { player_id: number; name: string; photo_code: number | null; team_code: number | null; points: number; edge: number }
interface Swing { status: string; edge?: number; matches?: SwingCard[]; helping?: Mover[]; hurting?: Mover[] }

const GoalReplay = lazy(() => import('@/components/live/GoalReplay').then((m) => ({ default: m.GoalReplay })))
const GOLD = '#ffc400', SPOT = '#ff4614', GREEN = '#4fd88a', RED = '#ff6b57', INK = '#07090d'
const ROWS = ['GKP', 'DEF', 'MID', 'FWD'] as const
const pad2 = (n: number) => String(n).padStart(2, '0')

function findGoalShot(snap: LiveSnapshot, name: string): Splash['shot'] {
  const want = name.toLowerCase().split('.').pop()?.trim() ?? ''
  const g = (snap.active_matches ?? []).flatMap((m) => m.shots ?? [])
    .filter((s) => s.outcome?.toLowerCase() === 'goal' && s.x !== null && s.y !== null && (s.player_name ?? '').toLowerCase().includes(want))
    .sort((a, b) => (b.minute ?? 0) - (a.minute ?? 0))[0]
  return g ? { x: g.x!, y: g.y!, gy: g.goal_crossed_y, gz: g.goal_crossed_z } : null
}

function Clock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => { const t = window.setInterval(() => setNow(new Date()), 1000); return () => window.clearInterval(t) }, [])
  return <Flap text={`${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}`} width={8} stagger={0} className="text-[1.7rem]" />
}

function minuteOf(m: LiveMatch): number {
  const n = parseInt(String(m.live_minute ?? '').replace(/[^0-9]/g, ''), 10)
  return Number.isFinite(n) ? n : m.status === 'HALFTIME' ? 45 : 0
}

/** One of your players on the pitch: photo, name plate, live points, event stamps. */
function PitchPlayer({ s, pts, state, events }: { s: LiveSquadPlayer; pts: number; state: string; events: { goal: number; assist: number; red: number } }) {
  const live = state === 'live'
  const done = state === 'played'
  return (
    <div className={`relative flex w-[7.6rem] flex-col items-center ${state === '' || state === 'to_play' || state === 'unplayed' ? 'opacity-60' : ''}`}>
      <div className={`relative ${live ? 'tv-live-ring' : ''}`}>
        <PlayerPhoto code={s.photo_code ?? null} teamCode={s.team_code ?? null} isGkp={s.position === 'GKP'} className="h-[5.2rem] w-[4.4rem]" />
        {s.is_captain && <span className="absolute -left-2 top-0 grid size-7 place-items-center rounded-full font-display text-[15px] font-black" style={{ background: GOLD, color: INK }}>C</span>}
        {s.is_vice && <span className="absolute -left-2 top-0 grid size-7 place-items-center rounded-full border-2 border-paper/70 bg-[#07090d] font-display text-[14px] font-black">V</span>}
        <div className="absolute -right-3 top-0 flex flex-col gap-0.5">
          {Array.from({ length: events.goal }).map((_, i) => <span key={`g${i}`} className="grid size-6 place-items-center rounded-full bg-paper text-[13px]">⚽</span>)}
          {Array.from({ length: events.assist }).map((_, i) => <span key={`a${i}`} className="grid size-6 place-items-center rounded-full font-display text-[12px] font-black" style={{ background: GREEN, color: INK }}>A</span>)}
          {events.red > 0 && <span className="h-6 w-4 rounded-[2px]" style={{ background: '#ff3b30' }} />}
        </div>
      </div>
      <div className="mt-1 w-full border-2 border-[#07090d] text-center shadow-[3px_3px_0_rgba(0,0,0,0.6)]">
        <div className="truncate bg-[#07090d] px-1 font-display text-[15px] font-black uppercase leading-[1.35] text-paper">{s.web_name}</div>
        <div className={`tabular font-display text-[1.9rem] font-black leading-[1.05] ${live ? 'animate-pulse' : ''}`} style={{ background: done || live ? GOLD : '#2a2f38', color: done || live ? INK : '#fbf6ea99' }}>
          <Odometer value={pts} className="justify-center" />
        </div>
      </div>
    </div>
  )
}

export function TvScreen() {
  const state = useFetch(fetchLiveSnapshot, [], 10000)
  const swingState = useFetch(() => getJson<Swing>('/api/swing'), [], 15000)
  const pbpMatches = useLiveMatches()
  const snap: LiveSnapshot | null = state.status === 'ready' ? state.data : null
  const swing = swingState.status === 'ready' && swingState.data.status === 'ok' ? swingState.data : null
  const captainId = snap?.squad?.find((s) => s.is_captain)?.player_id ?? null
  const crowd = useCrowd(snap?.match_events ?? [], captainId)
  const [splash, setSplash] = useState<Splash | null>(null)
  const [pitchId, setPitchId] = useState<number | null>(null)
  const prev = useRef<{ pts: Map<number, number>; ev: Map<string, number> } | null>(null)
  const [log, setLog] = useState<string[]>([])
  const [full, setFull] = useState(false)
  const squad = useMemo(() => new Map((snap?.squad ?? []).map((s) => [s.player_id, s])), [snap])

  useEffect(() => {
    if (!snap) return
    const pts = new Map((snap.points?.by_player ?? []).map((b) => [b.player_id, b.points * Math.max(1, b.multiplier)]))
    const ev = new Map((snap.match_events ?? []).map((e) => [`${e.player_id}:${e.kind}`, e.count]))
    const before = prev.current
    prev.current = { pts, ev }
    if (!before) return
    const lines: string[] = []
    let best: Splash | null = null
    for (const e of snap.match_events ?? []) {
      const was = before.ev.get(`${e.player_id}:${e.kind}`) ?? 0
      if (e.count <= was || !squad.has(e.player_id)) continue
      const kind = e.kind === 'goal' ? 'GOAL' : e.kind === 'assist' ? 'ASSIST' : 'RED CARD'
      const sp = squad.get(e.player_id)
      const name = e.web_name ?? sp?.web_name ?? ''
      lines.push(`${kind} · ${name}`)
      const gained = (pts.get(e.player_id) ?? 0) - (before.pts.get(e.player_id) ?? 0)
      const cand: Splash = { id: Date.now(), kind, name, points: gained, captain: e.player_id === captainId, photo: sp?.photo_code, team: sp?.team_code,
        shot: kind === 'GOAL' ? findGoalShot(snap, name) : null }
      if (!best || (kind === 'GOAL' && best.kind !== 'GOAL')) best = cand
    }
    for (const [pid, p] of pts) {
      const was = before.pts.get(pid) ?? 0
      if (p - was >= 2 && !lines.some((l) => l.endsWith(squad.get(pid)?.web_name ?? '#'))) lines.push(`+${p - was} · ${squad.get(pid)?.web_name ?? pid}`)
    }
    if (lines.length) setLog((l) => [...lines, ...l].slice(0, 30))
    if (best) {
      setSplash(best)
      if (best.kind !== 'RED CARD') {
        const colors = [SPOT, GOLD, '#fbf6ea', '#0b7d40']
        confetti({ particleCount: best.captain ? 260 : 160, spread: 90, origin: { y: 0.6 }, colors, scalar: 1.2 })
        window.setTimeout(() => confetti({ particleCount: 120, angle: 60, spread: 70, origin: { x: 0 }, colors }), 250)
        window.setTimeout(() => confetti({ particleCount: 120, angle: 120, spread: 70, origin: { x: 1 }, colors }), 400)
      }
      window.setTimeout(() => setSplash((s) => (s && s.id === best!.id ? null : s)), best.shot ? 10500 : 6500)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap])

  const toggleFull = () => {
    if (document.fullscreenElement) { void document.exitFullscreen(); setFull(false) } else { void document.documentElement.requestFullscreen(); setFull(true) }
  }

  const points = snap?.points
  const matches = snap?.active_matches ?? []
  const inPlay = (m: LiveMatch) => m.status === 'LIVE' || m.status === 'HALFTIME'
  const pitchMatch = matches.find((m) => m.match_id === pitchId) ?? matches.find(inPlay)
  const live = matches.some(inPlay)
  const byPlayer = new Map((points?.by_player ?? []).map((b) => [b.player_id, b]))
  const evOf = (pid: number) => {
    const out = { goal: 0, assist: 0, red: 0 }
    for (const e of snap?.match_events ?? []) if (e.player_id === pid) {
      if (e.kind === 'goal') out.goal += e.count
      else if (e.kind === 'assist') out.assist += e.count
      else if (e.kind.includes('red')) out.red += e.count
    }
    return out
  }
  const starters = (snap?.squad ?? []).filter((s) => s.slot === 'starting')
  const bench = (snap?.squad ?? []).filter((s) => s.slot === 'bench')
  const rank = snap?.rank
  const edge = swing?.edge
  const cardFor = (m: LiveMatch) => (swing?.matches ?? []).find((c) => c.home.short === m.home_short && c.away.short === m.away_short)
  const ticker = log.length ? log : (snap?.match_events ?? []).filter((e) => squad.has(e.player_id)).map((e) => `${e.kind.toUpperCase()} · ${e.web_name ?? ''}${e.count > 1 ? ` ×${e.count}` : ''}`)
  const sortedMatches = [...matches].sort((a, b) => (inPlay(b) ? 1 : 0) - (inPlay(a) ? 1 : 0) || Number(b.is_squad_match) - Number(a.is_squad_match))

  return (
    <div className="tv fixed inset-0 overflow-hidden bg-[#07090d] text-paper">
      <div className="tv-floodlight pointer-events-none absolute inset-0" />

      {/* Top bar */}
      <div className="relative z-10 flex items-center justify-between border-b-2 border-paper/10 px-8 py-3">
        <div className="flex items-center gap-4">
          <span className={`size-3 rounded-full ${live ? 'animate-pulse' : ''}`} style={{ background: live ? SPOT : '#fbf6ea4d' }} />
          <span className="font-display text-[1.9rem] font-black uppercase tracking-[0.04em]">Matchday <span style={{ color: GOLD }}>GW{snap?.gw?.event ?? snap?.event ?? ''}</span></span>
          <span className="font-display text-[14px] font-black uppercase tracking-[0.2em] text-paper/50">{live || anyInPlay(pbpMatches) ? `${matches.filter(inPlay).length} in play` : 'nothing in play'}</span>
        </div>
        <div className="flex items-center gap-4">
          <button type="button" onClick={crowd.toggle} className={`border-2 border-paper/40 px-3 py-1 font-display text-[13px] font-black uppercase ${crowd.on ? 'bg-[#ff4614] text-[#07090d]' : 'text-paper/80'}`}>{crowd.on ? 'Crowd on' : 'Crowd off'}</button>
          <button type="button" onClick={toggleFull} className="border-2 border-paper/40 px-3 py-1 font-display text-[13px] font-black uppercase text-paper/80">{full ? 'Exit full screen' : 'Full screen'}</button>
          <Link to="/live" className="font-display text-[13px] font-black uppercase text-paper/50 hover:text-paper">Exit TV</Link>
          <Clock />
        </div>
      </div>

      <div className="relative z-10 grid h-[calc(100vh-8.6rem)] grid-cols-[22rem_minmax(0,1fr)_29rem] gap-6 px-8 py-5">
        {/* Scoreboard */}
        <div className="flex min-h-0 flex-col gap-4">
          <div className="border-2 border-paper/15 bg-paper/[0.03] p-4">
            <div className="text-[12px] font-bold uppercase tracking-[0.3em] text-paper/50">your points</div>
            <Odometer value={points?.points ?? 0} className="font-display text-[9rem] font-black leading-[0.9] text-paper" />
            <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-paper/10" title="your eleven: played, in play, to play">
              {(() => {
                const t = Math.max(1, (points?.played ?? 0) + (points?.live ?? 0) + (points?.yet_to_play ?? 0))
                return (<>
                  <span style={{ width: `${((points?.played ?? 0) / t) * 100}%`, background: '#fbf6eacc' }} />
                  <span className="animate-pulse" style={{ width: `${((points?.live ?? 0) / t) * 100}%`, background: SPOT }} />
                </>)
              })()}
            </div>
            <div className="mt-1.5 flex justify-between text-[12px] font-bold uppercase tracking-[0.12em] text-paper/55">
              <span>{points?.played ?? 0} played</span><span style={{ color: SPOT }}>{points?.live ?? 0} live</span><span>{points?.yet_to_play ?? 0} to play</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="border-2 border-paper/15 p-3">
              <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-paper/45">vs top 10k</div>
              <div className="tabular font-display text-5xl font-black leading-none" style={{ color: edge == null ? undefined : edge >= 0 ? GREEN : RED }}>
                {edge == null ? '—' : `${edge >= 0 ? '+' : ''}${edge.toFixed(1)}`}
              </div>
            </div>
            <div className="border-2 border-paper/15 p-3">
              <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-paper/45">rank, live</div>
              <div className="tabular font-display text-[2rem] font-black leading-none">{rank?.estimated_rank ? rank.estimated_rank.toLocaleString() : '—'}</div>
              {rank?.rank_gain != null && (
                <div className="font-display text-lg font-black" style={{ color: rank.rank_gain >= 0 ? GREEN : RED }}>{rank.rank_gain >= 0 ? '▲' : '▼'} {Math.abs(rank.rank_gain).toLocaleString()}</div>
              )}
            </div>
          </div>

          {points?.captain_name && (() => {
            const cap = snap?.squad?.find((s) => s.is_captain)
            return (
              <div className="flex items-center gap-3 border-2 p-3" style={{ borderColor: `${GOLD}99`, background: `${GOLD}14` }}>
                {cap && <PlayerPhoto code={cap.photo_code ?? null} teamCode={cap.team_code ?? null} className="h-20 w-16" />}
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] font-bold uppercase tracking-[0.18em]" style={{ color: `${GOLD}cc` }}>armband · {(points.captain_play_state ?? '').replace(/_/g, ' ')}</div>
                  <div className="truncate font-display text-[1.7rem] font-black uppercase leading-none">{points.captain_name}</div>
                </div>
                <span className="tabular font-display text-6xl font-black" style={{ color: GOLD }}>{points.captain_points ?? 0}</span>
              </div>
            )
          })()}

          {swing && ((swing.helping ?? []).length > 0 || (swing.hurting ?? []).length > 0) && (
            <div className="min-h-0 flex-1 overflow-hidden border-2 border-paper/15 p-3">
              <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.18em] text-paper/45">who is moving your rank</div>
              {[...(swing.helping ?? []).slice(0, 3).map((m) => ({ ...m, good: true })), ...(swing.hurting ?? []).slice(0, 3).map((m) => ({ ...m, good: false }))].map((m) => (
                <div key={`${m.good}${m.player_id}`} className="flex items-center gap-2 border-b border-paper/10 py-1 last:border-0">
                  <span className="size-2 rounded-full" style={{ background: m.good ? GREEN : RED }} />
                  <span className="flex-1 truncate font-display text-[17px] font-black uppercase">{m.name}</span>
                  <span className="tabular text-[13px] text-paper/50">{m.points} pts</span>
                  <span className="tabular w-12 text-right font-display text-lg font-black" style={{ color: m.good ? GREEN : RED }}>{m.edge >= 0 ? '+' : ''}{m.edge.toFixed(1)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Your eleven on the pitch */}
        <div className="relative flex min-h-0 flex-col overflow-hidden rounded-[4px] border-2 border-paper/15">
          <div className="absolute inset-0" style={{ background: 'repeating-linear-gradient(180deg, #0f5a33 0 9%, #0d5130 9% 18%)' }} />
          <div className="pointer-events-none absolute inset-4 rounded-[2px] border-2 border-paper/25" />
          <div className="pointer-events-none absolute left-1/2 top-4 h-[12%] w-[38%] -translate-x-1/2 border-2 border-t-0 border-paper/25" />
          <div className="pointer-events-none absolute bottom-[23%] left-4 right-4 border-t-2 border-paper/20" />
          <div className="relative flex flex-1 flex-col justify-around py-5">
            {ROWS.map((pos) => {
              const row = starters.filter((s) => s.position === pos)
              if (!row.length) return null
              return (
                <div key={pos} className="flex justify-center gap-6">
                  {row.map((s) => {
                    const b = byPlayer.get(s.player_id)
                    return <PitchPlayer key={s.player_id} s={s} pts={b ? b.points * Math.max(1, b.multiplier) : 0} state={b?.play_state ?? ''} events={evOf(s.player_id)} />
                  })}
                </div>
              )
            })}
          </div>
          <div className="relative flex items-center justify-center gap-5 border-t-2 border-paper/15 bg-[#07090d]/70 px-4 py-2">
            <span className="font-display text-[13px] font-black uppercase tracking-[0.2em] text-paper/50">bench</span>
            {bench.map((s) => {
              const b = byPlayer.get(s.player_id)
              const sub = (snap?.autosubs ?? []).find((a) => a.into === s.player_id)
              return (
                <span key={s.player_id} className={`flex items-center gap-2 border px-2 py-1 font-display text-[15px] font-black uppercase ${sub ? 'border-[#4fd88a] text-paper' : 'border-paper/20 text-paper/55'}`}>
                  {s.web_name}<span className="tabular" style={{ color: sub ? GREEN : undefined }}>{b?.points ?? 0}</span>{sub && <span className="text-[11px]" style={{ color: GREEN }}>{sub.status === 'made' ? 'ON' : 'STANDBY'}</span>}
                </span>
              )
            })}
            {points && points.bench > 0 && <span className="tabular font-display text-[15px] font-black text-paper/50">{points.bench} on the bench</span>}
          </div>
        </div>

        {/* The matches */}
        <div className="min-h-0 overflow-y-auto pr-1">
          {matches.length === 0 && anyInPlay(pbpMatches) ? <TvCups matches={pbpMatches} /> : matches.length > 0 ? (
            <div className="space-y-3">
              {pitchMatch?.fotmob_match_id && inPlay(pitchMatch) && <PitchFor fotmobId={pitchMatch.fotmob_match_id} className="!mb-0" />}
              {sortedMatches.map((m) => {
                const playing = inPlay(m)
                const c = cardFor(m)
                const min = minuteOf(m)
                return (
                  <button type="button" key={m.match_id} onClick={() => setPitchId(m.match_id)}
                    className={`block w-full border-2 p-3 text-left ${m.is_squad_match ? 'border-[#ff4614]/70 bg-[#ff4614]/[0.06]' : 'border-paper/15'} ${pitchMatch?.match_id === m.match_id ? 'outline outline-2 outline-[#ffc400]' : ''}`}>
                    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
                      <span className="flex items-center gap-2 font-display text-[1.6rem] font-black uppercase">
                        {crestUrl(m.home_code) && <img src={crestUrl(m.home_code)!} alt="" className="size-8" />}{m.home_short}
                      </span>
                      <span className="tabular font-display text-[2.6rem] font-black leading-none">{m.home_score ?? 0}<span className="mx-1.5 text-paper/30">–</span>{m.away_score ?? 0}</span>
                      <span className="flex items-center justify-end gap-2 font-display text-[1.6rem] font-black uppercase">
                        {m.away_short}{crestUrl(m.away_code) && <img src={crestUrl(m.away_code)!} alt="" className="size-8" />}
                      </span>
                    </div>
                    <div className="mt-1.5 flex items-center gap-2">
                      <span className="w-16 font-display text-[14px] font-black uppercase" style={{ color: playing ? SPOT : '#fbf6ea80' }}>
                        {playing ? (m.status === 'HALFTIME' ? 'HT' : m.live_minute ?? 'live') : m.status === 'FULL_TIME' ? 'FT' : 'to come'}
                      </span>
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-paper/10">
                        <span className="block h-full" style={{ width: `${m.status === 'FULL_TIME' ? 100 : Math.min(100, (min / 90) * 100)}%`, background: playing ? SPOT : '#fbf6ea55' }} />
                      </span>
                    </div>
                    {c && playing && (
                      <div className="mt-2 grid grid-cols-2 gap-2 text-center">
                        {[c.home, c.away].map((s, i) => (
                          <div key={i} className="border border-paper/15 py-1">
                            <div className="text-[10.5px] font-bold uppercase tracking-[0.14em] text-paper/45">{s.short} score next</div>
                            <div className="tabular font-display text-2xl font-black" style={{ color: s.next_goal >= 0 ? GREEN : RED }}>{s.next_goal >= 0 ? '+' : ''}{s.next_goal.toFixed(1)}</div>
                          </div>
                        ))}
                      </div>
                    )}
                    {(m.my_players ?? []).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {m.my_players.map((p) => {
                          const b = byPlayer.get(p.player_id)
                          return (
                            <span key={p.player_id} className="border border-paper/25 px-2 py-0.5 text-[13px] font-bold">
                              {p.web_name} <span className="tabular font-display" style={{ color: GOLD }}>{b ? b.points * Math.max(1, b.multiplier) : 0}</span>
                              {(p.goals ?? 0) > 0 && <span className="ml-1 px-1 text-[#07090d]" style={{ background: GOLD }}>{p.goals}G</span>}
                              {(p.assists ?? 0) > 0 && <span className="ml-1 px-1 text-[#07090d]" style={{ background: GREEN }}>{p.assists}A</span>}
                            </span>
                          )
                        })}
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          ) : (snap?.upcoming ?? []).length > 0 ? (
            <DepartureBoard matches={snap!.upcoming!} compact />
          ) : (
            <div className="flex h-full items-center justify-center font-display text-3xl font-black uppercase text-paper/30">no matches on</div>
          )}
        </div>
      </div>

      {/* Events crawl */}
      <div className="absolute inset-x-0 bottom-0 z-10 flex h-12 items-center overflow-hidden border-t-2 border-paper/10 text-[#07090d]" style={{ background: SPOT }}>
        <span className="z-10 flex h-full items-center bg-[#07090d] px-5 font-display text-lg font-black uppercase tracking-[0.1em]" style={{ color: SPOT }}>Events</span>
        <div className="ticker-track flex whitespace-nowrap">
          {[0, 1].map((k) => (
            <div key={k} className="flex shrink-0 gap-10 px-6 font-display text-xl font-black uppercase">
              {(ticker.length ? ticker : ['your players’ goals, assists and points appear here as they happen']).map((t, i) => <span key={`${k}-${i}`}>{t}</span>)}
            </div>
          ))}
        </div>
      </div>

      {splash && (
        <div key={splash.id} className="tv-splash pointer-events-none fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#07090d]/88" style={{ animationDuration: splash.shot ? '10.5s' : '6.5s' }}>
          <div className="flex items-center gap-10">
            {splash.photo != null && <PlayerPhoto code={splash.photo} teamCode={splash.team ?? null} className="h-[22rem] w-[18rem]" />}
            <div>
              <div className={`font-display text-[13rem] font-black uppercase leading-[0.8] [text-shadow:10px_10px_0_#ff4614]`} style={{ color: splash.kind === 'RED CARD' ? '#ff3b30' : GOLD }}>{splash.kind}</div>
              <div className="mt-6 font-display text-[6rem] font-black uppercase leading-none text-paper">{splash.name}</div>
              {splash.points > 0 && <div className="mt-4 font-display text-5xl font-black" style={{ color: GREEN }}>+{splash.points}{splash.captain ? ' · armband' : ''}</div>}
            </div>
          </div>
          {splash.shot && (
            <div className="mt-8"><Suspense fallback={null}><GoalReplay x={splash.shot.x} y={splash.shot.y} gy={splash.shot.gy} gz={splash.shot.gz} label={splash.name} /></Suspense></div>
          )}
        </div>
      )}
    </div>
  )
}
