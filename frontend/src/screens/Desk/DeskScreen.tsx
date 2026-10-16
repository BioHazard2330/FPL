import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Play } from 'lucide-react'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import { crestUrl, fetchDeskPayload } from '@/lib/api'
import { relativeTime } from '@/lib/time'
import { useFetch } from '@/lib/useFetch'
import type { DeskArticle, DeskInjury, DeskPayload, DeskPlayerChip, DeskPost, DeskPriceLean, DeskPriceMove, DeskVideo } from '@/lib/types'

/** THE DESK - everything being said about football this week, ranked by what
 * it means for this squad.
 *
 * Nothing on this page is written by the product. Articles, videos and posts
 * are what BBC, Sky, The Guardian, four YouTube channels and r/FantasyPL
 * published, linked back to their source; the injury wire is the official FPL
 * note verbatim; the price board is the club-of-record's own price changes plus
 * the transfer-momentum lean the project already computes. The only thing the
 * desk adds is order: an item naming one of your players comes first, one
 * naming a player the plan buys or declined comes next, everything else is
 * newest first. A tag says why an item is where it is. */

type WireFilter = 'all' | 'yours' | 'targets' | 'injury'

function Chip({ c }: { c: DeskPlayerChip }) {
  const tone = c.mine ? 'bg-pitch-green text-pitch-green-ink' : c.target ? 'bg-broadcast-gold text-broadcast-gold-ink' : 'bg-raised text-text-muted'
  const crest = crestUrl(c.team_code)
  return (
    <Link to={`/player/${c.player_id}`} className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] ${tone}`}>
      {crest && <img src={crest} alt="" className="h-3 w-3" />}
      {c.name}
      {c.mine && <span className="opacity-70">· yours</span>}
      {!c.mine && c.target && <span className="opacity-70">· plan</span>}
    </Link>
  )
}

function Chips({ players }: { players: DeskPlayerChip[] }) {
  if (players.length === 0) return null
  const ordered = players.slice().sort((a, b) => Number(b.mine) - Number(a.mine) || Number(b.target) - Number(a.target))
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {ordered.slice(0, 6).map((c) => <Chip key={c.player_id} c={c} />)}
    </div>
  )
}

function Picture({ src, className, label }: { src: string | null; className: string; label?: string }) {
  const [broken, setBroken] = useState(false)
  if (!src || broken) {
    return (
      <div className={`${className} flex items-end bg-raised p-2 font-display text-lg font-bold uppercase leading-none text-text-faint`}>
        {label}
      </div>
    )
  }
  return <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} className={`${className} object-cover`} />
}

function Kicker({ children }: { children: React.ReactNode }) {
  return <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">{children}</div>
}

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="border-b-2 border-divider px-10 py-7">
      <div className="mb-4 flex items-baseline justify-between gap-6">
        <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-text">{title}</h2>
        {aside && <div className="text-xs text-text-muted">{aside}</div>}
      </div>
      {children}
    </section>
  )
}

function Lead({ a }: { a: DeskArticle }) {
  return (
    <a href={a.link} target="_blank" rel="noreferrer" className="group grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] items-stretch border-b-2 border-divider bg-panel">
      <Picture src={a.image} label={a.source} className="h-full min-h-[300px] w-full" />
      <div className="flex flex-col justify-center gap-3 px-8 py-6">
        <Kicker>
          {a.source} · {relativeTime(a.published_at) ?? 'undated'}
          {a.relevance >= 2 ? ' · names your player' : a.relevance === 1 ? ' · names a plan target' : ''}
        </Kicker>
        <div className="font-display text-4xl font-bold leading-[1.02] text-text group-hover:text-pitch-green">{a.title}</div>
        {a.summary && <p className="text-sm leading-relaxed text-text-muted">{a.summary}</p>}
        <Chips players={a.players} />
      </div>
    </a>
  )
}

function WireRow({ a }: { a: DeskArticle }) {
  const rail = a.relevance >= 2 ? 'border-l-pitch-green' : a.relevance === 1 ? 'border-l-broadcast-gold' : 'border-l-transparent'
  return (
    <article className={`grid grid-cols-[132px_minmax(0,1fr)] gap-4 border-b border-l-4 border-divider py-3 pl-3 ${rail}`}>
      <Picture src={a.image} label={a.source} className="h-[78px] w-[132px]" />
      <div className="min-w-0">
        <Kicker>
          {a.source} · {relativeTime(a.published_at) ?? 'undated'}
          {a.injury && <span className="text-alert-red"> · fitness</span>}
        </Kicker>
        <a href={a.link} target="_blank" rel="noreferrer" className="mt-0.5 block text-[15px] font-semibold leading-snug text-text hover:text-pitch-green">{a.title}</a>
        {a.summary && <p className="mt-0.5 line-clamp-2 text-xs text-text-muted">{a.summary}</p>}
        <Chips players={a.players} />
      </div>
    </article>
  )
}

function InjuryRow({ i }: { i: DeskInjury }) {
  const chance = i.chance ?? (i.status === 'i' || i.status === 'u' || i.status === 's' ? 0 : null)
  const crest = crestUrl(i.team_code)
  const tone = chance === null ? 'bg-text-faint' : chance >= 75 ? 'bg-pitch-green' : chance >= 50 ? 'bg-broadcast-gold' : 'bg-alert-red'
  return (
    <div className="border-b border-divider py-2.5">
      <div className="flex items-center gap-2">
        {crest && <img src={crest} alt="" className="h-4 w-4" />}
        <Link to={`/player/${i.player_id}`} className="text-sm font-bold text-text hover:text-pitch-green">{i.name}</Link>
        {i.mine && <span className="bg-pitch-green px-1 text-[9px] font-bold uppercase leading-4 text-pitch-green-ink">yours</span>}
        {!i.mine && i.target && <span className="bg-broadcast-gold px-1 text-[9px] font-bold uppercase leading-4 text-broadcast-gold-ink">plan</span>}
        <span className="ml-auto font-mono text-[10px] uppercase text-text-faint">{i.team_short}{i.owned !== null ? ` · ${i.owned.toFixed(1)}% owned` : ''}</span>
      </div>
      <div className="mt-1 flex items-center gap-3">
        <div className="h-1.5 w-20 shrink-0 bg-raised">
          {chance !== null && <div className={`h-full ${tone}`} style={{ width: `${chance}%` }} />}
        </div>
        <span className="tabular w-9 shrink-0 text-xs font-bold text-text">{chance !== null ? `${chance}%` : '—'}</span>
        <span className="min-w-0 truncate text-xs text-text-muted" title={i.news}>{i.news}</span>
      </div>
      <div className="mt-0.5 font-mono text-[10px] text-text-faint">official FPL note · {relativeTime(i.added_at) ?? ''}</div>
    </div>
  )
}

function Video({ v, playing, onPlay }: { v: DeskVideo; playing: boolean; onPlay: () => void }) {
  return (
    <div className="min-w-0">
      <div className="relative aspect-video w-full bg-raised">
        {playing ? (
          <iframe
            className="absolute inset-0 h-full w-full"
            src={`https://www.youtube-nocookie.com/embed/${v.video_id}?autoplay=1&rel=0`}
            title={v.title}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
          />
        ) : (
          <button type="button" onClick={onPlay} className="group absolute inset-0 block h-full w-full text-left" aria-label={`Play ${v.title}`}>
            <Picture src={v.thumbnail} label={v.channel} className="h-full w-full" />
            <span className="absolute left-3 top-3 flex h-9 w-9 items-center justify-center bg-void text-text group-hover:bg-pitch-green group-hover:text-pitch-green-ink">
              <Play size={16} fill="currentColor" />
            </span>
          </button>
        )}
      </div>
      <div className="mt-2">
        <Kicker>{v.channel} · {relativeTime(v.published_at) ?? ''}</Kicker>
        <a href={v.link} target="_blank" rel="noreferrer" className="mt-0.5 line-clamp-2 text-sm font-semibold leading-snug text-text hover:text-pitch-green">{v.title}</a>
        <Chips players={v.players} />
      </div>
    </div>
  )
}

function Post({ p }: { p: DeskPost }) {
  return (
    <div className="border-b border-divider py-3">
      <Kicker>r/FantasyPL · u/{p.author ?? 'unknown'} · {relativeTime(p.published_at) ?? ''}</Kicker>
      <a href={p.link} target="_blank" rel="noreferrer" className="mt-0.5 block text-sm font-semibold leading-snug text-text hover:text-pitch-green">{p.title}</a>
      <Chips players={p.players} />
    </div>
  )
}

function MoveCell({ m, rise }: { m: DeskPriceMove; rise: boolean }) {
  const crest = crestUrl(m.team_code)
  return (
    <div className="flex items-center gap-2 border-b border-divider py-1.5 text-sm">
      {crest && <img src={crest} alt="" className="h-4 w-4" />}
      <Link to={`/player/${m.player_id}`} className="font-semibold text-text hover:text-pitch-green">{m.name}</Link>
      {m.mine && <span className="bg-pitch-green px-1 text-[9px] font-bold uppercase leading-4 text-pitch-green-ink">yours</span>}
      {!m.mine && m.target && <span className="bg-broadcast-gold px-1 text-[9px] font-bold uppercase leading-4 text-broadcast-gold-ink">plan</span>}
      <span className={`tabular ml-auto text-xs font-bold ${rise ? 'text-pitch-green' : 'text-alert-red'}`}>
        {Number(m.old).toFixed(1)} → {Number(m.new).toFixed(1)}
      </span>
    </div>
  )
}

function LeanCell({ l }: { l: DeskPriceLean }) {
  const crest = crestUrl(l.team_code)
  const rise = l.direction === 'RISE_LIKELY'
  return (
    <div className="flex items-center gap-2 border-b border-divider py-1.5 text-sm">
      {crest && <img src={crest} alt="" className="h-4 w-4" />}
      <Link to={`/player/${l.player_id}`} className="font-semibold text-text hover:text-pitch-green">{l.name}</Link>
      {l.mine && <span className="bg-pitch-green px-1 text-[9px] font-bold uppercase leading-4 text-pitch-green-ink">yours</span>}
      {!l.mine && l.target && <span className="bg-broadcast-gold px-1 text-[9px] font-bold uppercase leading-4 text-broadcast-gold-ink">plan</span>}
      <span className={`ml-auto font-mono text-[10px] font-bold uppercase ${rise ? 'text-pitch-green' : 'text-alert-red'}`}>{rise ? 'rise lean' : 'fall lean'}</span>
    </div>
  )
}

function PriceBoard({ price }: { price: DeskPayload['price'] }) {
  const leanRise = price.leaning.filter((l) => l.direction === 'RISE_LIKELY')
  const leanFall = price.leaning.filter((l) => l.direction === 'FALL_LIKELY')
  const empty = price.rises.length + price.falls.length + price.leaning.length === 0
  if (empty) return <p className="text-sm text-text-muted">No price moves in the last 36 hours and no player is leaning either way.</p>
  return (
    <div className="grid grid-cols-4 gap-8">
      <div>
        <Kicker>Rose · last 36h</Kicker>
        {price.rises.length ? price.rises.map((m) => <MoveCell key={m.player_id} m={m} rise />) : <p className="py-2 text-xs text-text-faint">none</p>}
      </div>
      <div>
        <Kicker>Fell · last 36h</Kicker>
        {price.falls.length ? price.falls.map((m) => <MoveCell key={m.player_id} m={m} rise={false} />) : <p className="py-2 text-xs text-text-faint">none</p>}
      </div>
      <div>
        <Kicker>Leaning up</Kicker>
        {leanRise.length ? leanRise.slice(0, 8).map((l) => <LeanCell key={l.player_id} l={l} />) : <p className="py-2 text-xs text-text-faint">none</p>}
      </div>
      <div>
        <Kicker>Leaning down</Kicker>
        {leanFall.length ? leanFall.slice(0, 8).map((l) => <LeanCell key={l.player_id} l={l} />) : <p className="py-2 text-xs text-text-faint">none</p>}
      </div>
    </div>
  )
}

export function DeskScreen() {
  const state = useFetch(fetchDeskPayload, [], 300000)
  const [filter, setFilter] = useState<WireFilter>('all')
  const [playing, setPlaying] = useState<number | null>(null)

  const wire = useMemo(() => {
    if (state.status !== 'ready') return []
    const w = state.data.wire
    if (filter === 'yours') return w.filter((a) => a.relevance >= 2)
    if (filter === 'targets') return w.filter((a) => a.relevance >= 1)
    if (filter === 'injury') return w.filter((a) => a.injury)
    return w
  }, [state, filter])

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <Skel className="h-[320px] w-full" />
        <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-10 px-10 py-8">
          <div className="space-y-4">{Array.from({ length: 6 }, (_, i) => <Skel key={i} className="h-[78px] w-full" />)}</div>
          <div className="space-y-3">{Array.from({ length: 8 }, (_, i) => <Skel key={i} className="h-10 w-full" />)}</div>
        </div>
      </div>
    )
  }
  if (state.status === 'error') {
    return <ScreenError title="Desk unavailable" description="The news desk could not be fetched, so nothing here is known to be current." message={state.error.message} />
  }
  const d = state.data
  const filters: { key: WireFilter; label: string; n: number }[] = [
    { key: 'all', label: 'All', n: d.wire.length },
    { key: 'yours', label: 'Your players', n: d.wire.filter((a) => a.relevance >= 2).length },
    { key: 'targets', label: 'Yours + plan targets', n: d.wire.filter((a) => a.relevance >= 1).length },
    { key: 'injury', label: 'Fitness', n: d.wire.filter((a) => a.injury).length },
  ]

  return (
    <div className="data-in pb-16">
      <Masthead
        edition="The Desk"
        title="What is being said, in the order it matters to you"
        right={<span className="text-text-muted">{d.counts.articles} articles · {d.counts.yours} name your players · {d.counts.targets} name a plan target</span>}
      />

      {d.lead && <Lead a={d.lead} />}

      <div className="grid grid-cols-[minmax(0,1fr)_420px] border-b-2 border-divider">
        <div className="border-r border-divider px-10 py-7">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-4">
            <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-text">The wire</h2>
            <div className="flex gap-1">
              {filters.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => setFilter(f.key)}
                  className={`px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] ${filter === f.key ? 'bg-text text-void' : 'bg-raised text-text-muted hover:text-text'}`}
                >
                  {f.label} <span className="tabular opacity-60">{f.n}</span>
                </button>
              ))}
            </div>
          </div>
          {wire.length ? wire.map((a) => <WireRow key={a.id} a={a} />) : <p className="py-6 text-sm text-text-muted">Nothing in this filter in the last five days.</p>}
        </div>
        <div className="sticky top-0 max-h-screen self-start overflow-y-auto px-8 py-7">
          <h2 className="mb-1 font-display text-2xl font-bold uppercase tracking-wide text-text">Injury wire</h2>
          <p className="mb-3 text-xs text-text-muted">The official FPL note as published, last ten days. Your players first, then plan targets, then the most owned.</p>
          {d.injuries.length ? d.injuries.map((i) => <InjuryRow key={i.player_id} i={i} />) : <p className="text-sm text-text-muted">No new flags.</p>}
        </div>
      </div>

      <Section title="Price board" aside="Rises and falls are FPL's own changes. A lean is the project's transfer-momentum heuristic - uncalibrated, low confidence, a direction and not a forecast.">
        <PriceBoard price={d.price} />
      </Section>

      <Section title="Studio" aside="Premier League · Sky Sports · FPL Harry · Let's Talk FPL. Click to play here; nothing loads from YouTube until you do.">
        {d.videos.length ? (
          <div className="grid grid-cols-4 gap-x-6 gap-y-7">
            {d.videos.map((v) => <Video key={v.id} v={v} playing={playing === v.id} onPlay={() => setPlaying(v.id)} />)}
          </div>
        ) : (
          <p className="text-sm text-text-muted">No videos stored yet. Run <span className="font-mono">fpl sync-media</span>.</p>
        )}
      </Section>

      <Section title="The community" aside="r/FantasyPL, in Reddit's own hot order. The feed carries no vote counts, so none are shown.">
        {d.posts.length ? (
          <div className="grid grid-cols-2 gap-x-10">
            {d.posts.map((p) => <Post key={p.id} p={p} />)}
          </div>
        ) : (
          <p className="text-sm text-text-muted">No posts stored yet.</p>
        )}
      </Section>
    </div>
  )
}
