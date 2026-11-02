import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

gsap.registerPlugin(ScrollTrigger)

/** THE STORY OF YOUR SEASON - a scroll-driven film of the finished gameweeks (`models/season_story`). The rank river draws
 * as you scroll with its moments pinned on it; the weeks pass sideways; the race against the managers ranked around
 * 10,000 and your league runs gameweek by gameweek under the scroll; the moments; and where it stands. */

interface Pic { player_id: number; name: string; photo_code: number | null; team_code: number | null; points: number; multiplier?: number }
interface Week { event: number; points: number; total: number; rank: number | null; average: number | null; bench: number | null; hits: number; chip: string | null; captain: Pic | null; star: Pic | null }
interface Racer { entry_id: number; name: string; team: string; totals: Record<string, number> }
interface Story {
  status: string; weeks: Week[]; cohort_total: Record<string, number>; league: string | null; racers: Racer[]
  moments: { best_week: number; worst_week: number; best_climb: [number, number] | null; worst_fall: [number, number] | null; best_captain: number; worst_bench: number }
  season_average: number; average_average: number
}

const CHIP: Record<string, string> = { wildcard: 'Wildcard', freehit: 'Free hit', bboost: 'Bench boost', '3xc': 'Triple captain' }
const fmtRank = (v: number) => (v >= 1_000_000 ? `${(v / 1_000_000).toFixed(2)}m` : v >= 1000 ? `${Math.round(v / 1000)}k` : String(v))

function River({ weeks, moments }: { weeks: Week[]; moments: Story['moments'] }) {
  const W = 1100, H = 440, padX = 70, padY = 50
  const ranked = weeks.filter((w) => w.rank)
  const logs = ranked.map((w) => Math.log10(w.rank!))
  const lo = Math.min(...logs) - 0.08, hi = Math.max(...logs) + 0.08
  const x = (i: number) => padX + (i * (W - 2 * padX)) / Math.max(1, ranked.length - 1)
  const y = (r: number) => padY + ((Math.log10(r) - lo) / (hi - lo)) * (H - 2 * padY)
  const d = ranked.map((w, i) => `${i ? 'L' : 'M'}${x(i)},${y(w.rank!)}`).join(' ')
  const area = `${d} L${x(ranked.length - 1)},${H - padY + 30} L${x(0)},${H - padY + 30} Z`
  const notes: { i: number; text: string; tone: string }[] = []
  ranked.forEach((w, i) => {
    if (w.chip) notes.push({ i, text: CHIP[w.chip] ?? w.chip, tone: '#ff4614' })
    if (moments.best_climb && w.event === moments.best_climb[0]) notes.push({ i, text: `▲ ${fmtRank(moments.best_climb[1])}`, tone: '#0b7d40' })
    if (moments.worst_fall && w.event === moments.worst_fall[0]) notes.push({ i, text: `▼ ${fmtRank(-moments.worst_fall[1])}`, tone: '#d4321c' })
  })
  return (
    <svg viewBox={`0 0 ${W} ${H + 40}`} className="w-full">
      <defs>
        <linearGradient id="river" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ff4614" stopOpacity="0.35" />
          <stop offset="1" stopColor="#ff4614" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[1_000, 10_000, 100_000, 1_000_000, 10_000_000].filter((g) => Math.log10(g) > lo && Math.log10(g) < hi).map((g) => (
        <g key={g}>
          <line x1={padX} x2={W - padX} y1={y(g)} y2={y(g)} stroke="#fbf6ea" strokeOpacity={0.15} strokeDasharray="5 6" />
          <text x={padX - 10} y={y(g) + 4} textAnchor="end" fill="#fbf6ea" fillOpacity={0.5} fontSize={13} fontWeight={800}>{fmtRank(g)}</text>
        </g>
      ))}
      <path className="river-area" d={area} fill="url(#river)" />
      <path className="river-line" d={d} fill="none" stroke="#ff4614" strokeWidth={6} strokeLinejoin="round" strokeLinecap="round" />
      {ranked.map((w, i) => (
        <g key={w.event} className="river-dot">
          <circle cx={x(i)} cy={y(w.rank!)} r={8} fill="#07090d" stroke="#fbf6ea" strokeWidth={3} />
          <text x={x(i)} y={H - padY + 30} textAnchor="middle" fill="#fbf6ea" fillOpacity={0.55} fontSize={13} fontWeight={800}>GW{w.event}</text>
          <text x={x(i)} y={y(w.rank!) - 16} textAnchor="middle" fill="#fbf6ea" fontSize={14} fontWeight={900} fontFamily="Big Shoulders Display, Impact, sans-serif">{fmtRank(w.rank!)}</text>
        </g>
      ))}
      {notes.map((n, k) => (
        <g key={k} className="river-note">
          <rect x={x(n.i) - 54} y={y(ranked[n.i].rank!) + 18 + (k % 2) * 30} width={108} height={24} fill={n.tone} />
          <text x={x(n.i)} y={y(ranked[n.i].rank!) + 35 + (k % 2) * 30} textAnchor="middle" fill="#fbf6ea" fontSize={13} fontWeight={900} fontFamily="Big Shoulders Display, Impact, sans-serif">{n.text.toUpperCase()}</text>
        </g>
      ))}
    </svg>
  )
}

function Race({ story, step }: { story: Story; step: number }) {
  const w = story.weeks[Math.min(step, story.weeks.length - 1)]
  const ev = w.event
  const rows = [
    { key: 'you', name: 'You', total: w.total, you: true, cohort: false },
    ...story.racers.map((r) => ({ key: String(r.entry_id), name: r.name, total: r.totals[String(ev)] ?? 0, you: false, cohort: false })),
    ...(story.cohort_total[String(ev)] !== undefined ? [{ key: '10k', name: 'The 10k average', total: Math.round(story.cohort_total[String(ev)]), you: false, cohort: true }] : []),
  ].sort((a, b) => b.total - a.total)
  const max = Math.max(...rows.map((r) => r.total), 1)
  const order = new Map(rows.map((r, i) => [r.key, i]))
  const all = [...rows].sort((a, b) => a.key.localeCompare(b.key))
  return (
    <div>
      <div className="mb-4 flex items-end justify-between">
        <div className="font-display text-[7rem] font-black leading-[0.8] text-[#ffc400]">GW{ev}</div>
        <div className="text-right text-[13px] text-paper/60">{story.league}<br />and the managers ranked around 10,000</div>
      </div>
      <div className="relative" style={{ height: rows.length * 52 }}>
        {all.map((r) => (
          <div key={r.key} className="absolute inset-x-0 flex h-11 items-center gap-3 transition-transform duration-500 ease-out" style={{ transform: `translateY(${(order.get(r.key) ?? 0) * 52}px)` }}>
            <div className={`w-56 truncate text-right font-display text-xl font-black uppercase ${r.you ? 'text-[#ff4614]' : r.cohort ? 'text-[#7fb6ff]' : 'text-paper'}`}>{r.name}</div>
            <div className="relative h-9 flex-1">
              <div className={`absolute inset-y-0 left-0 transition-[width] duration-500 ease-out ${r.you ? 'bg-[#ff4614]' : r.cohort ? 'bg-[#1c3fd1]' : 'bg-paper/25'}`} style={{ width: `${(r.total / max) * 100}%` }} />
              <div className="tabular absolute inset-y-0 flex items-center pl-2 font-display text-xl font-black text-paper" style={{ left: `${(r.total / max) * 100}%` }}>{r.total}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function StoryScreen() {
  const state = useFetch(() => getJson<Story>('/api/story'), [])
  const root = useRef<HTMLDivElement>(null)
  const [step, setStep] = useState(0)
  const story = state.status === 'ready' && state.data.status === 'ok' ? state.data : null
  const weeks = story?.weeks ?? []
  const first = weeks[0], last = weeks[weeks.length - 1]
  const best = useMemo(() => weeks.find((w) => w.event === story?.moments.best_week), [weeks, story])
  const worst = useMemo(() => weeks.find((w) => w.event === story?.moments.worst_week), [weeks, story])
  const cap = useMemo(() => weeks.find((w) => w.event === story?.moments.best_captain), [weeks, story])
  const bench = useMemo(() => weeks.find((w) => w.event === story?.moments.worst_bench), [weeks, story])

  useLayoutEffect(() => {
    if (!story || !root.current) return
    const ctx = gsap.context(() => {
      gsap.from('.story-hero-line', { y: 80, opacity: 0, stagger: 0.12, duration: 1, ease: 'power3.out' })
      const counter = { v: first?.rank ?? 0 }
      gsap.to(counter, {
        v: last?.rank ?? 0, ease: 'none',
        scrollTrigger: { trigger: '.story-hero', start: 'top top', end: 'bottom top', scrub: true },
        onUpdate: () => { const el = document.querySelector('.story-counter'); if (el) el.textContent = Math.round(counter.v).toLocaleString() },
      })
      const line = document.querySelector<SVGPathElement>('.river-line')
      if (line) {
        const len = line.getTotalLength()
        gsap.set(line, { strokeDasharray: len, strokeDashoffset: len })
        const tl = gsap.timeline({ scrollTrigger: { trigger: '.story-river', start: 'top top', end: '+=1600', scrub: 1, pin: true } })
        tl.to(line, { strokeDashoffset: 0, ease: 'none', duration: 1 })
          .from('.river-area', { opacity: 0, duration: 0.3 }, 0.2)
          .from('.river-dot', { opacity: 0, scale: 0.4, transformOrigin: 'center', stagger: 0.1, duration: 0.2 }, 0)
          .from('.river-note', { opacity: 0, y: 20, stagger: 0.08, duration: 0.2 }, 0.4)
      }
      const strip = document.querySelector<HTMLElement>('.story-strip')
      if (strip) {
        gsap.to(strip, {
          x: () => -(strip.scrollWidth - window.innerWidth + 260), ease: 'none',
          scrollTrigger: { trigger: '.story-weeks', start: 'top top', end: () => `+=${strip.scrollWidth}`, scrub: 1, pin: true, invalidateOnRefresh: true },
        })
      }
      ScrollTrigger.create({
        trigger: '.story-race', start: 'top top', end: `+=${weeks.length * 260}`, pin: true, scrub: true,
        onUpdate: (self) => setStep(Math.min(weeks.length - 1, Math.floor(self.progress * weeks.length))),
      })
      gsap.utils.toArray<HTMLElement>('.story-moment').forEach((el, i) => {
        gsap.from(el, { y: 120, rotate: i % 2 ? 4 : -4, opacity: 0, duration: 0.9, ease: 'back.out(1.6)', scrollTrigger: { trigger: el, start: 'top 85%' } })
      })
    }, root)
    window.setTimeout(() => ScrollTrigger.refresh(), 300)
    return () => { ctx.revert() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [story])

  if (state.status === 'loading') return <div className="p-10 text-text-muted">Rolling the film…</div>
  if (!story || !first || !last) return <div className="p-10 text-text-muted">No finished gameweeks yet.</div>
  const sign = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v)}`

  return (
    <div>
    <div ref={root} className="story bare -mx-9 -mt-7 !bg-[#07090d] text-paper">
      <div className="!bg-[#07090d] story-hero relative flex min-h-[calc(100vh-4rem)] flex-col justify-center overflow-hidden px-14">
        <div className="pointer-events-none absolute -right-20 top-0 select-none font-display text-[30rem] font-black leading-none text-paper/[0.03]">{last.event}</div>
        <div className="story-hero-line font-display text-[15px] font-black uppercase tracking-[0.4em] text-[#ff4614]">The story of your season · GW1–{last.event}</div>
        <div className="story-hero-line mt-4 font-display text-[7.5rem] font-black uppercase leading-[0.82]">From {fmtRank(first.rank ?? 0)}<br />to {fmtRank(last.rank ?? 0)}</div>
        <div className="story-hero-line mt-8 flex items-end gap-10">
          <div>
            <div className="text-[12px] font-bold uppercase tracking-[0.2em] text-paper/50">overall rank</div>
            <div className="story-counter tabular font-display text-[4.5rem] font-black leading-none text-[#ffc400]">{(first.rank ?? 0).toLocaleString()}</div>
          </div>
          <div className="pb-2 text-[14px] text-paper/60">{last.total} points · {story.season_average} a week against an average of {story.average_average}</div>
        </div>
        <div className="story-hero-line mt-14 text-[12px] font-bold uppercase tracking-[0.3em] text-paper/40">scroll ↓</div>
      </div>

      <div className="!bg-[#07090d] story-river flex h-[calc(100vh-4rem)] flex-col justify-center px-14">
        <div className="font-display text-[15px] font-black uppercase tracking-[0.4em] text-[#ff4614]">Chapter one</div>
        <h2 className="font-display text-[4rem] font-black uppercase leading-none text-paper">The rank river</h2>
        <div className="mt-6"><River weeks={weeks} moments={story.moments} /></div>
      </div>

      <div className="!bg-[#07090d] story-weeks flex h-[calc(100vh-4rem)] flex-col justify-center overflow-hidden">
        <div className="px-14">
          <div className="font-display text-[15px] font-black uppercase tracking-[0.4em] text-[#ff4614]">Chapter two</div>
          <h2 className="font-display text-[4rem] font-black uppercase leading-none text-paper">Week by week</h2>
        </div>
        <div className="story-strip mt-8 flex gap-6 pl-14">
          {weeks.map((w) => {
            const diff = w.points - (w.average ?? 0)
            return (
              <div key={w.event} className="relative w-[22rem] shrink-0 border-2 border-paper/20 bg-[#10131a] p-6">
                {w.chip && <div className="absolute -top-3 right-4 rotate-[3deg] bg-[#ff4614] px-2 py-0.5 font-display text-[13px] font-black uppercase text-[#07090d]">{CHIP[w.chip]}</div>}
                <div className="font-display text-[15px] font-black uppercase tracking-[0.2em] text-paper/50">Gameweek {w.event}</div>
                <div className="mt-1 flex items-end gap-3">
                  <span className="tabular font-display text-[6rem] font-black leading-[0.85]">{w.points}</span>
                  <span className={`tabular pb-2 font-display text-3xl font-black ${diff >= 0 ? 'text-[#4fd88a]' : 'text-[#ff6b57]'}`}>{sign(diff)}</span>
                </div>
                <div className="text-[12.5px] text-paper/50">against an average of {w.average} · rank {w.rank ? fmtRank(w.rank) : '—'}</div>
                <div className="mt-5 grid grid-cols-2 gap-3">
                  {[['armband', w.captain], ['star', w.star]].map(([k, p]) => p && typeof p === 'object' ? (
                    <div key={k as string} className="flex items-end gap-2">
                      <PlayerPhoto code={(p as Pic).photo_code} teamCode={(p as Pic).team_code} className="h-16 w-12" />
                      <div>
                        <div className="text-[10.5px] font-bold uppercase tracking-[0.16em] text-paper/45">{k as string}</div>
                        <div className="truncate text-[14px] font-bold">{(p as Pic).name}</div>
                        <div className="tabular font-display text-2xl font-black text-[#ffc400]">{(p as Pic).points}{k === 'armband' && (p as Pic).multiplier && (p as Pic).multiplier! > 1 ? ` ×${(p as Pic).multiplier}` : ''}</div>
                      </div>
                    </div>
                  ) : null)}
                </div>
                {(w.bench ?? 0) >= 12 && <div className="mt-4 text-[12px] font-bold text-[#ff6b57]">{w.bench} points left on the bench</div>}
              </div>
            )
          })}
        </div>
      </div>

      <div className="!bg-[#07090d] story-race flex h-[calc(100vh-4rem)] flex-col justify-center px-14">
        <div className="font-display text-[15px] font-black uppercase tracking-[0.4em] text-[#ff4614]">Chapter three</div>
        <h2 className="mb-6 font-display text-[4rem] font-black uppercase leading-none text-paper">The race</h2>
        <Race story={story} step={step} />
      </div>

      <div className="px-14 py-24">
        <div className="font-display text-[15px] font-black uppercase tracking-[0.4em] text-[#ff4614]">Chapter four</div>
        <h2 className="font-display text-[4rem] font-black uppercase leading-none text-paper">The moments</h2>
        <div className="mt-12 grid grid-cols-2 gap-8">
          {best && <Moment title="Best week" big={String(best.points)} sub={`GW${best.event}, ${sign(best.points - (best.average ?? 0))} on the average${best.star ? ` · ${best.star.name} ${best.star.points}` : ''}`} tone="#4fd88a" />}
          {worst && <Moment title="Worst week" big={String(worst.points)} sub={`GW${worst.event}, ${sign(worst.points - (worst.average ?? 0))} on the average${worst.chip ? ` · on the ${CHIP[worst.chip].toLowerCase()}` : ''}`} tone="#ff6b57" />}
          {cap?.captain && <Moment title="Best armband" big={String(cap.captain.points * cap.captain.multiplier!)} sub={`${cap.captain.name}, GW${cap.event}${cap.captain.multiplier! > 2 ? ' · triple captain' : ''}`} tone="#ffc400" />}
          {bench && <Moment title="The bench that hurt" big={String(bench.bench)} sub={`points left on the bench in GW${bench.event}`} tone="#7fb6ff" />}
        </div>
      </div>

      <div className="flex min-h-[70vh] flex-col items-center justify-center px-14 pb-24 text-center">
        <div className="font-display text-[15px] font-black uppercase tracking-[0.4em] text-[#ff4614]">To be continued</div>
        <div className="mt-4 max-w-4xl font-display text-[4.5rem] font-black uppercase leading-[0.9]">{38 - last.event} gameweeks left</div>
        <div className="mt-8 flex gap-4">
          <Link to="/versus" className="border-2 border-paper bg-paper px-5 py-2 font-display text-lg font-black uppercase text-[#07090d] hover:bg-[#ff4614]">Versus the 10k</Link>
          <Link to="/" className="border-2 border-paper px-5 py-2 font-display text-lg font-black uppercase text-paper hover:bg-paper hover:text-[#07090d]">This week's call</Link>
        </div>
      </div>
    </div>
    </div>
  )
}

function Moment({ title, big, sub, tone }: { title: string; big: string; sub: string; tone: string }) {
  return (
    <div className="story-moment border-2 border-paper/20 bg-[#10131a] p-8" style={{ boxShadow: `8px 8px 0 ${tone}` }}>
      <div className="font-display text-[15px] font-black uppercase tracking-[0.25em]" style={{ color: tone }}>{title}</div>
      <div className="tabular mt-2 font-display text-[7rem] font-black leading-[0.85]">{big}</div>
      <div className="mt-3 text-[15px] text-paper/60">{sub}</div>
    </div>
  )
}
