import { Link } from 'react-router-dom'
import { RunOfFixtures } from '@/screens/Previews/RunOfFixtures'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import { crestUrl, fetchPreviewsPayload } from '@/lib/api'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fdrFill } from '@/lib/fdr'
import { useFetch } from '@/lib/useFetch'
import type { PreviewFixture, PreviewKeyPlayer, PreviewLens, PreviewSide } from '@/lib/types'

/** MATCH PREVIEWS - the next gameweek, one fixture at a time.
 *
 * Each card reads left to right as the match would be talked about: who is
 * at home, the model's expected goals and the score it thinks most likely,
 * who is favoured, the clean-sheet chances, how each side has been playing,
 * and who the player model rates highest on each team. The market's own 1X2
 * sits under the model's as a second bar, never blended into it, so a gap
 * between the two reads as a gap. Your own players are marked wherever they
 * appear. The method and its assumptions are in the payload builder. */

const pct = (p: number) => `${Math.round(p * 100)}%`

function kickoffLabel(iso: string | null): string {
  if (!iso) return 'Kickoff to be confirmed'
  const d = new Date(iso)
  return d.toLocaleString([], { weekday: 'long', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function dayKey(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' }) : 'Date to be confirmed'
}

function OutcomeBar({ h, d, a, label, faint }: { h: number; d: number; a: number; label: string; faint?: boolean }) {
  const seg = (w: number, tone: string, text: string) => (
    <div className={`${tone} flex h-full items-center justify-center overflow-hidden`} style={{ width: `${w * 100}%` }}>
      <span className="tabular text-[12px] font-bold">{w >= 0.1 ? text : ''}</span>
    </div>
  )
  return (
    <div className="flex items-center gap-3">
      <span className="w-14 shrink-0 text-[12px] text-text-faint">{label}</span>
      <div className={`flex w-full ${faint ? 'h-3.5 opacity-60' : 'h-6'}`}>
        {seg(h, 'bg-pitch-green text-pitch-green-ink', pct(h))}
        {seg(d, 'bg-raised text-text-muted', pct(d))}
        {seg(a, 'bg-broadcast-blue text-broadcast-blue-ink', pct(a))}
      </div>
    </div>
  )
}

function FormDots({ side }: { side: PreviewSide }) {
  if (side.form.length === 0) return <span className="text-[13px] text-text-faint">no finished match yet</span>
  return (
    <span className="inline-flex gap-0.5">
      {side.form.slice().reverse().map((r) => (
        <span
          key={r.fixture_id}
          title={`${r.home ? 'vs' : 'at'} ${r.opponent} ${r.score}`}
          className={`inline-block h-4 w-4 text-center text-[12px] font-bold leading-4 ${r.result === 'W' ? 'bg-pitch-green text-pitch-green-ink' : r.result === 'D' ? 'bg-raised text-text-muted' : 'bg-alert-red text-alert-red-ink'}`}
        >
          {r.result}
        </span>
      ))}
    </span>
  )
}

function KeyPlayer({ p, teamCode }: { p: PreviewKeyPlayer; teamCode: number }) {
  return (
    <div className="flex items-center gap-2 py-0.5 text-sm">
      <PlayerPhoto code={p.photo_code} teamCode={teamCode} isGkp={p.position === 'GKP'} className="h-9 w-7" />
      <span className="w-8 text-[12px] text-text-faint">{p.position}</span>
      <Link to={`/player/${p.player_id}`} className="min-w-0 truncate font-semibold text-text hover:text-pitch-green">{p.name}</Link>
      {p.mine && <span className="bg-pitch-green px-1 text-[12px] font-bold leading-4 text-pitch-green-ink">yours</span>}
      {p.doubt !== null && <span className="bg-broadcast-gold px-1 text-[12px] font-bold leading-4 text-broadcast-gold-ink" title={p.news ?? ''}>{p.doubt}%</span>}
      <span className="tabular ml-auto font-bold text-pitch-green">{p.xp.toFixed(1)}</span>
    </div>
  )
}

function Side({ side, home, cs }: { side: PreviewSide; home: boolean; cs: number }) {
  const crest = crestUrl(side.code)
  return (
    <div className={`min-w-0 ${home ? '' : 'text-right'}`}>
      <div className={`flex items-center gap-3 ${home ? '' : 'flex-row-reverse'}`}>
        {crest && <img src={crest} alt="" className="h-14 w-14 object-contain" />}
        <div className="min-w-0">
          <Link to={`/club/${side.team_id}`} className="block truncate font-display text-2xl font-bold leading-none text-text hover:text-pitch-green">{side.name}</Link>
          <div className={`mt-1.5 flex items-center gap-2 ${home ? '' : 'justify-end'}`}>
            <FormDots side={side} />
            {side.difficulty !== null && (
              <span className={`px-1 font-mono text-[12px] font-bold leading-4 ${fdrFill(side.difficulty)}`} title="FPL fixture difficulty for this side">FDR {side.difficulty}</span>
            )}
          </div>
        </div>
      </div>
      <div className="mt-3 text-left">
        <div className="mb-1 flex items-baseline justify-between text-[12px] text-text-faint">
          <span>Top projected</span>
          <span>clean sheet {pct(cs)}</span>
        </div>
        {side.key_players.map((p) => <KeyPlayer key={p.player_id} p={p} teamCode={side.code} />)}
        {side.absentees.length > 0 && (
          <div className="mt-1.5 border-t border-divider pt-1.5 text-[13px] text-text-muted">
            {side.absentees.map((a, i) => (
              <span key={a.player_id}>
                {i > 0 && ' · '}
                <Link to={`/player/${a.player_id}`} className="hover:text-text">{a.name}</Link>{' '}
                <span className="tabular text-text-faint">{a.chance !== null ? `${a.chance}%` : 'out'}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function LensPanel({ lens, home, away }: { lens: PreviewLens; home: PreviewSide; away: PreviewSide }) {
  const max = Math.max(0.05, ...lens.home.map((r) => r.expected), ...lens.away.map((r) => r.expected))
  const shown = lens.home.map((h, i) => ({ h, a: lens.away[i] })).filter(({ h, a }) => h.league >= 0.02 || h.expected >= 0.02 || a.expected >= 0.02)
  const delta = (v: number) => (Math.abs(v) < 0.01 ? '' : `${v > 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}`)
  const tone = (v: number) => (v > 0.02 ? 'text-pitch-green' : v < -0.02 ? 'text-alert-red' : 'text-text-faint')
  const head = lens.headline
  return (
    <div className="mt-6 rounded-lg bg-raised/40 px-5 py-4">
      <div className="mb-3 flex items-baseline justify-between">
        <span className="text-[12px] text-text-faint">Where the chances come from</span>
        <span className="text-[12px] text-text-faint">
          xG by source, this attack against that defence · {lens.matches.home} and {lens.matches.away} matches of shots
        </span>
      </div>
      <div className="space-y-1.5">
        {shown.map(({ h, a }) => (
          <div key={h.source} className="grid grid-cols-[3.5rem_minmax(0,1fr)_6.5rem_minmax(0,1fr)_3.5rem] items-center gap-3 text-[13px]">
            <span className={`tabular text-right font-semibold ${tone(h.shift)}`}>{delta(h.shift)}</span>
            <div className="flex h-3.5 justify-end"><div className="bar-draw-right h-full rounded-sm bg-pitch-green" style={{ width: `${(h.expected / max) * 100}%` }} /></div>
            <span className="text-center text-[12px] text-text-muted">{h.source}</span>
            <div className="flex h-3.5"><div className="bar-draw h-full rounded-sm bg-broadcast-blue" style={{ width: `${(a.expected / max) * 100}%` }} /></div>
            <span className={`tabular font-semibold ${tone(a.shift)}`}>{delta(a.shift)}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[13px] leading-relaxed text-text-muted">
        {head
          ? `${head.side === 'home' ? home.short : away.short}'s ${head.source} ${head.shift > 0 ? 'meet a defence that gives them up' : 'meet a defence that shuts them down'}: ${head.shift > 0 ? '+' : '−'}${Math.abs(head.shift).toFixed(2)} xG against the average fixture (attack ${head.attack.toFixed(2)}×, defence ${head.defence.toFixed(2)}×).`
          : 'Neither attack nor defence tilts any source by more than 0.08 xG against the average fixture.'}
        {lens.takers && lens.takers.length > 0 && head && (
          <> Most {head.source} xG so far:{' '}
            {lens.takers.map((t, i) => (
              <span key={t.player_id}>{i > 0 && ', '}<Link to={`/player/${t.player_id}`} className="font-semibold text-text hover:text-pitch-green">{t.name}</Link> <span className="tabular text-text-faint">{t.xg.toFixed(2)}</span></span>
            ))}.
          </>
        )}
      </p>
    </div>
  )
}

const READING_RULE: Record<string, string> = {
  neutral: 'border-divider',
  caution: 'border-broadcast-gold',
  opportunity: 'border-pitch-green',
}

/** THE ANALYST'S READ OF THE FORM - each club's last matches set against each
 * other, in numbers: chances for and against, results against the chances they
 * deserved, dead-ball dependence, and who came off hurt. A statement about
 * something measured not to persist says so in the same sentence. */
function Reading({ f }: { f: PreviewFixture }) {
  const items = f.reading?.statements ?? []
  if (items.length === 0) return null
  return (
    <div className="mt-5">
      <div className="mb-2 text-[12px] font-bold text-text-faint">The analyst&rsquo;s read of the form</div>
      <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
        {items.map((s, i) => (
          <div key={i} className={`tone bg-panel px-3 py-2 ${READING_RULE[s.tone]}`}>
            <p className="text-[13px] leading-snug text-text-muted">{s.text}</p>
            {s.weight && <p className="mt-0.5 text-[12px] font-bold text-text-faint">{s.weight}</p>}
          </div>
        ))}
      </div>
    </div>
  )
}

function Card({ f }: { f: PreviewFixture }) {
  const yours = f.home.yours.length + f.away.yours.length
  const gap = f.market ? Math.round((f.model.home_win - f.market.home_win) * 100) : null
  const hc = crestUrl(f.home.code)
  const ac = crestUrl(f.away.code)
  const time = f.kickoff ? new Date(f.kickoff).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'TBC'
  return (
    <details className="group border-b border-divider last:border-0">
      <summary className="grid cursor-pointer list-none grid-cols-[4rem_minmax(0,1fr)_7rem_minmax(0,1fr)_11rem_1.5rem] items-center gap-4 px-8 py-3.5 hover:bg-raised/30 [&::-webkit-details-marker]:hidden">
        <span className="tabular text-[13px] text-text-faint">{time}</span>
        <span className="flex items-center justify-end gap-2.5 text-right font-display text-lg font-semibold text-text">
          {f.home.name}
          {hc && <img src={hc} alt="" className="size-6 object-contain" />}
        </span>
        <span className="tabular text-center font-display text-xl font-semibold text-text">
          {f.xg.home.toFixed(1)}<span className="mx-1.5 text-text-faint">&ndash;</span>{f.xg.away.toFixed(1)}
        </span>
        <span className="flex items-center gap-2.5 font-display text-lg font-semibold text-text">
          {ac && <img src={ac} alt="" className="size-6 object-contain" />}
          {f.away.name}
        </span>
        <span className="flex items-center gap-2 text-[13px]">
          {yours > 0 ? (
            <span className="rounded-full bg-pitch-green/15 px-2 py-0.5 font-semibold text-pitch-green" title={[...f.home.yours, ...f.away.yours].map((p) => p.name).join(', ')}>
              {yours} of yours
            </span>
          ) : (
            <span className="text-text-faint">{pct(f.model.home_win)} / {pct(f.model.draw)} / {pct(f.model.away_win)}</span>
          )}
        </span>
        <span aria-hidden className="text-text-faint transition-transform group-open:rotate-90">&#9656;</span>
      </summary>
      <article className="px-8 pb-6 pt-2">
        <div className="mb-4 flex items-baseline justify-between text-[13px] text-text-faint">
          <span>{kickoffLabel(f.kickoff)}</span>
          {yours > 0 && <span>{[...f.home.yours, ...f.away.yours].map((p) => p.name).join(', ')}</span>}
        </div>
        <div className="grid grid-cols-[1fr_300px_1fr] gap-8">
          <Side side={f.home} home cs={f.model.home_clean_sheet} />
          <div className="flex flex-col items-center justify-start text-center">
            <div className="text-[12px] text-text-faint">Expected goals</div>
            <div className="tabular font-display text-5xl font-semibold leading-none text-text">
              {f.xg.home.toFixed(1)}<span className="mx-2 text-text-faint">&ndash;</span>{f.xg.away.toFixed(1)}
            </div>
            <div className="mt-2 text-xs text-text-muted">
              most likely <span className="tabular font-bold text-text">{f.model.likely_score[0]}&ndash;{f.model.likely_score[1]}</span> at {pct(f.model.likely_score_p)}
            </div>
            <div className="mt-0.5 text-xs text-text-muted">3+ goals {pct(f.model.over_2_5)}</div>
          </div>
          <Side side={f.away} home={false} cs={f.model.away_clean_sheet} />
        </div>
        <div className="mt-5 space-y-1.5">
          <OutcomeBar h={f.model.home_win} d={f.model.draw} a={f.model.away_win} label="Model" />
          {f.market && <OutcomeBar h={f.market.home_win} d={f.market.draw} a={f.market.away_win} label="Market" faint />}
          <div className="pl-[68px] text-[13px] text-text-faint">
            {f.market
              ? `${f.home.short} / draw / ${f.away.short}. Market: ${f.market.bookmakers} bookmaker${f.market.bookmakers === 1 ? '' : 's'}, de-vigged. The model's home-win figure is ${gap === 0 ? 'level with' : `${Math.abs(gap ?? 0)} pts ${(gap ?? 0) > 0 ? 'above' : 'below'}`} the market's.`
              : `${f.home.short} / draw / ${f.away.short}. No odds stored for this fixture, so there is no market line to compare.`}
          </div>
        </div>
        <Reading f={f} />
        {f.lens && <LensPanel lens={f.lens} home={f.home} away={f.away} />}
      </article>
    </details>
  )
}

export function PreviewsScreen() {
  const state = useFetch(fetchPreviewsPayload, [], 600000)

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        {Array.from({ length: 3 }, (_, i) => <div key={i} className="border-b border-divider px-10 py-6"><Skel className="h-[250px] w-full" /></div>)}
      </div>
    )
  }
  if (state.status === 'error') {
    return <ScreenError title="Previews unavailable" description="The fixture previews could not be built, so no expected goals or probabilities are shown." message={state.error.message} />
  }
  const d = state.data
  if (d.event === null || d.fixtures.length === 0) {
    return (
      <div className="pb-16">
        <Masthead />
        <p className="px-10 py-8 text-sm text-text-muted">Every fixture on record has been played.</p>
      </div>
    )
  }
  const days: { key: string; fixtures: PreviewFixture[] }[] = []
  for (const f of d.fixtures) {
    const key = dayKey(f.kickoff)
    const last = days[days.length - 1]
    if (last && last.key === key) last.fixtures.push(f)
    else days.push({ key, fixtures: [f] })
  }

  return (
    <div className="data-in pb-16">
      <Masthead right={<span>{d.fixtures.length} fixtures &middot; the expected goals are the same ones every projection uses</span>} />
      {d.ticker && (
        <RunOfFixtures
          ticker={d.ticker}
          mine={new Set(d.fixtures.flatMap((f) => [f.home, f.away]).filter((s) => s.yours.length > 0).map((s) => s.team_id))}
        />
      )}
      {days.map((day) => (
        <section key={day.key}>
          <h2 className="border-b border-divider bg-raised/40 px-8 py-2 font-display text-base font-semibold text-text-muted">{day.key}</h2>
          {day.fixtures.map((f) => <Card key={f.fixture_id} f={f} />)}
        </section>
      ))}
    </div>
  )
}
