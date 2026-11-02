import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import confetti from 'canvas-confetti'
import { Odometer } from '@/components/ui/Odometer'
import { Flap } from '@/components/ui/Flap'
import { DepartureBoard } from '@/components/live/DepartureBoard'
import { crestUrl, fetchLiveSnapshot } from '@/lib/api'
import { useCrowd } from '@/lib/crowd'
import { useFetch } from '@/lib/useFetch'
import type { LiveSnapshot } from '@/lib/types'

/** MATCHDAY TV - the gameweek as a broadcast for a second screen. Your points on a rolling scoreboard, the rank, every
 * match in play with your players in it, your eleven with their live points, a ticker of events, and a full-screen
 * splash (with confetti and, if switched on, the crowd) when one of your players scores or sets one up. Before kickoff
 * it shows the departures board and the deadline. Reads the same live snapshot as the Live screen, every 10 seconds. */

interface Splash { id: number; kind: 'GOAL' | 'ASSIST' | 'RED CARD' | 'POINTS'; name: string; points: number; captain: boolean }

const pad2 = (n: number) => String(n).padStart(2, '0')

function Clock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => { const t = window.setInterval(() => setNow(new Date()), 1000); return () => window.clearInterval(t) }, [])
  return <Flap text={`${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}`} width={8} stagger={0} className="text-[2rem]" />
}

function fmtRank(v: number | null | undefined) {
  if (!v) return '—'
  return v.toLocaleString()
}

export function TvScreen() {
  const state = useFetch(fetchLiveSnapshot, [], 10000)
  const snap: LiveSnapshot | null = state.status === 'ready' ? state.data : null
  const captainId = snap?.squad?.find((s) => s.is_captain)?.player_id ?? null
  const crowd = useCrowd(snap?.match_events ?? [], captainId)
  const [splash, setSplash] = useState<Splash | null>(null)
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
      const name = e.web_name ?? squad.get(e.player_id)?.web_name ?? ''
      lines.push(`${kind} · ${name}`)
      const gained = (pts.get(e.player_id) ?? 0) - (before.pts.get(e.player_id) ?? 0)
      const cand: Splash = { id: Date.now(), kind, name, points: gained, captain: e.player_id === captainId }
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
        const colors = ['#ff4614', '#ffc400', '#fbf6ea', '#0b7d40']
        confetti({ particleCount: best.captain ? 260 : 160, spread: 90, origin: { y: 0.6 }, colors, scalar: 1.2 })
        window.setTimeout(() => confetti({ particleCount: 120, angle: 60, spread: 70, origin: { x: 0 }, colors }), 250)
        window.setTimeout(() => confetti({ particleCount: 120, angle: 120, spread: 70, origin: { x: 1 }, colors }), 400)
      }
      window.setTimeout(() => setSplash((s) => (s && s.id === best!.id ? null : s)), 6500)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap])

  const toggleFull = () => {
    if (document.fullscreenElement) { void document.exitFullscreen(); setFull(false) } else { void document.documentElement.requestFullscreen(); setFull(true) }
  }

  const points = snap?.points
  const matches = snap?.active_matches ?? []
  const live = matches.some((m) => m.status === 'LIVE' || m.status === 'HALFTIME')
  const starters = (snap?.squad ?? []).filter((s) => s.slot === 'starting')
  const bench = (snap?.squad ?? []).filter((s) => s.slot === 'bench')
  const byPlayer = new Map((points?.by_player ?? []).map((b) => [b.player_id, b]))
  const rank = snap?.rank
  const ticker = log.length ? log : (snap?.match_events ?? []).map((e) => `${e.kind.toUpperCase()} · ${e.web_name ?? ''}${e.count > 1 ? ` ×${e.count}` : ''}`)

  return (
    <div className="tv fixed inset-0 overflow-hidden bg-[#07090d] text-paper">
      <div className="tv-floodlight pointer-events-none absolute inset-0" />
      <div className="relative z-10 flex items-center justify-between border-b-2 border-paper/10 px-8 py-4">
        <div className="flex items-center gap-4">
          <span className={`size-3 rounded-full ${live ? 'animate-pulse bg-[#ff4614]' : 'bg-paper/30'}`} />
          <span className="font-display text-[2rem] font-black uppercase tracking-[0.04em]">Matchday <span className="text-[#ffc400]">GW{snap?.gw?.event ?? snap?.event ?? ''}</span></span>
          <span className="font-display text-[15px] font-black uppercase tracking-[0.2em] text-paper/50">{live ? 'live' : 'nothing in play'}</span>
        </div>
        <div className="flex items-center gap-5">
          <button type="button" onClick={crowd.toggle} className={`border-2 border-paper/40 px-3 py-1 font-display text-[13px] font-black uppercase ${crowd.on ? 'bg-[#ff4614] text-[#07090d]' : 'text-paper/80'}`}>{crowd.on ? 'Crowd on' : 'Crowd off'}</button>
          <button type="button" onClick={toggleFull} className="border-2 border-paper/40 px-3 py-1 font-display text-[13px] font-black uppercase text-paper/80">{full ? 'Exit full screen' : 'Full screen'}</button>
          <Link to="/live" className="font-display text-[13px] font-black uppercase text-paper/50 hover:text-paper">Exit TV</Link>
          <Clock />
        </div>
      </div>

      <div className="relative z-10 grid h-[calc(100vh-9.5rem)] grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)_minmax(0,0.95fr)] gap-6 px-8 py-6">
        <div className="flex flex-col">
          <div className="text-[13px] font-bold uppercase tracking-[0.3em] text-paper/50">your points</div>
          <Odometer value={points?.points ?? 0} className="font-display text-[11rem] font-black leading-none text-paper" />
          <div className="mt-2 grid grid-cols-3 gap-2">
            {[['played', points?.played], ['live', points?.live], ['to play', points?.yet_to_play]].map(([k, v]) => (
              <div key={k as string} className="border-2 border-paper/15 px-3 py-2">
                <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-paper/45">{k}</div>
                <div className="tabular font-display text-4xl font-black">{v ?? '—'}</div>
              </div>
            ))}
          </div>
          <div className="mt-6 border-2 border-paper/15 p-4">
            <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-paper/45">overall rank, live estimate</div>
            <div className="flex items-baseline gap-3">
              <span className="tabular font-display text-6xl font-black">{fmtRank(rank?.estimated_rank)}</span>
              {rank?.rank_gain !== null && rank?.rank_gain !== undefined && (
                <span className={`font-display text-2xl font-black ${rank.rank_gain >= 0 ? 'text-[#4fd88a]' : 'text-[#ff6b57]'}`}>
                  {rank.rank_gain >= 0 ? '▲' : '▼'} {Math.abs(rank.rank_gain).toLocaleString()}
                </span>
              )}
            </div>
          </div>
          {points?.captain_name && (
            <div className="mt-4 border-2 border-[#ffc400]/50 bg-[#ffc400]/10 p-4">
              <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#ffc400]/80">armband</div>
              <div className="flex items-baseline justify-between">
                <span className="font-display text-3xl font-black uppercase">{points.captain_name}</span>
                <span className="tabular font-display text-5xl font-black text-[#ffc400]">{points.captain_points ?? 0}</span>
              </div>
            </div>
          )}
        </div>

        <div className="min-h-0 overflow-hidden">
          {matches.length > 0 ? (
            <div className="grid h-full auto-rows-min gap-3 overflow-y-auto pr-1">
              {matches.map((m) => {
                const inPlay = m.status === 'LIVE' || m.status === 'HALFTIME'
                return (
                  <div key={m.match_id} className={`border-2 p-4 ${m.is_squad_match ? 'border-[#ff4614]/70 bg-[#ff4614]/[0.07]' : 'border-paper/15'}`}>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-2 font-display text-3xl font-black uppercase">
                        {crestUrl(m.home_code) && <img src={crestUrl(m.home_code)!} alt="" className="size-9" />}{m.home_short}
                      </span>
                      <span className="tabular font-display text-5xl font-black">{m.home_score ?? 0}<span className="mx-2 text-paper/30">–</span>{m.away_score ?? 0}</span>
                      <span className="flex items-center gap-2 font-display text-3xl font-black uppercase">
                        {m.away_short}{crestUrl(m.away_code) && <img src={crestUrl(m.away_code)!} alt="" className="size-9" />}
                      </span>
                    </div>
                    <div className="mt-1 text-center font-display text-[15px] font-black uppercase tracking-[0.2em] text-paper/50">
                      {inPlay ? <span className="text-[#ff4614]">{m.live_minute ?? 'live'}</span> : m.status === 'FULL_TIME' ? 'full time' : 'to come'}
                    </div>
                    {(m.my_players ?? []).length > 0 && (
                      <div className="mt-2 flex flex-wrap justify-center gap-1.5">
                        {m.my_players.map((p) => {
                          const b = byPlayer.get(p.player_id)
                          return (
                            <span key={p.player_id} className="border border-paper/25 px-2 py-0.5 text-[13px] font-bold">
                              {p.web_name} <span className="tabular font-display text-[#ffc400]">{b ? b.points * Math.max(1, b.multiplier) : 0}</span>
                              {(p.goals ?? 0) > 0 && <span className="ml-1 bg-[#ffc400] px-1 text-[#07090d]">{p.goals}G</span>}
                              {(p.assists ?? 0) > 0 && <span className="ml-1 bg-[#4fd88a] px-1 text-[#07090d]">{p.assists}A</span>}
                            </span>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          ) : (snap?.upcoming ?? []).length > 0 ? (
            <DepartureBoard matches={snap!.upcoming!} compact />
          ) : (
            <div className="flex h-full items-center justify-center font-display text-3xl font-black uppercase text-paper/30">no matches on</div>
          )}
        </div>

        <div className="min-h-0 overflow-hidden">
          <div className="text-[13px] font-bold uppercase tracking-[0.3em] text-paper/50">your eleven</div>
          <div className="mt-2 space-y-1">
            {starters.map((s) => {
              const b = byPlayer.get(s.player_id)
              const p = b ? b.points * Math.max(1, b.multiplier) : 0
              const st = b?.play_state ?? ''
              return (
                <div key={s.player_id} className="grid grid-cols-[1.2rem_minmax(0,1fr)_3.5rem] items-center gap-3 border-b border-paper/10 py-1.5">
                  <span className={`size-2.5 rounded-full ${st === 'live' ? 'animate-pulse bg-[#ff4614]' : st === 'played' ? 'bg-paper/70' : 'bg-paper/20'}`} />
                  <span className="truncate font-display text-[1.6rem] font-black uppercase leading-none">
                    {s.web_name}{s.is_captain && <span className="ml-2 bg-[#ffc400] px-1.5 text-[1rem] text-[#07090d]">C</span>}{s.is_vice && <span className="ml-2 border border-paper/40 px-1.5 text-[1rem]">V</span>}
                  </span>
                  <Odometer value={p} className="justify-end font-display text-[1.9rem] font-black text-[#ffc400]" />
                </div>
              )
            })}
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-paper/45">
            {bench.map((s) => {
              const b = byPlayer.get(s.player_id)
              return <span key={s.player_id} className="border border-paper/15 px-2 py-0.5 text-[13px] font-bold">{s.web_name} <span className="tabular">{b?.points ?? 0}</span></span>
            })}
          </div>
        </div>
      </div>

      <div className="absolute inset-x-0 bottom-0 z-10 flex h-12 items-center overflow-hidden border-t-2 border-paper/10 bg-[#ff4614] text-[#07090d]">
        <span className="z-10 flex h-full items-center bg-[#07090d] px-5 font-display text-lg font-black uppercase tracking-[0.1em] text-[#ff4614]">Events</span>
        <div className="ticker-track flex whitespace-nowrap">
          {[0, 1].map((k) => (
            <div key={k} className="flex shrink-0 gap-10 px-6 font-display text-xl font-black uppercase">
              {(ticker.length ? ticker : ['your players’ goals, assists and points appear here as they happen']).map((t, i) => <span key={`${k}-${i}`}>{t}</span>)}
            </div>
          ))}
        </div>
      </div>

      {splash && (
        <div key={splash.id} className="tv-splash pointer-events-none fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#07090d]/80">
          <div className={`font-display text-[14rem] font-black uppercase leading-[0.8] ${splash.kind === 'RED CARD' ? 'text-[#ff3b30]' : 'text-[#ffc400]'} [text-shadow:10px_10px_0_#ff4614]`}>{splash.kind}</div>
          <div className="mt-6 font-display text-[6rem] font-black uppercase leading-none text-paper">{splash.name}</div>
          {splash.points > 0 && <div className="mt-4 font-display text-5xl font-black text-[#4fd88a]">+{splash.points}{splash.captain ? ' · armband' : ''}</div>}
        </div>
      )}
    </div>
  )
}
