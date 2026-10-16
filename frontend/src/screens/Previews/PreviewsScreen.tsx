import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import { crestUrl, fetchPreviewsPayload } from '@/lib/api'
import { fdrFill } from '@/lib/fdr'
import { useFetch } from '@/lib/useFetch'
import type { PreviewFixture, PreviewKeyPlayer, PreviewSide } from '@/lib/types'

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
      <span className="tabular text-[10px] font-bold">{w >= 0.1 ? text : ''}</span>
    </div>
  )
  return (
    <div className="flex items-center gap-3">
      <span className="w-14 shrink-0 font-mono text-[10px] uppercase tracking-[0.06em] text-text-faint">{label}</span>
      <div className={`flex w-full ${faint ? 'h-3.5 opacity-60' : 'h-6'}`}>
        {seg(h, 'bg-pitch-green text-pitch-green-ink', pct(h))}
        {seg(d, 'bg-raised text-text-muted', pct(d))}
        {seg(a, 'bg-broadcast-blue text-broadcast-blue-ink', pct(a))}
      </div>
    </div>
  )
}

function FormDots({ side }: { side: PreviewSide }) {
  if (side.form.length === 0) return <span className="text-[11px] text-text-faint">no finished match yet</span>
  return (
    <span className="inline-flex gap-0.5">
      {side.form.slice().reverse().map((r) => (
        <span
          key={r.fixture_id}
          title={`${r.home ? 'vs' : 'at'} ${r.opponent} ${r.score}`}
          className={`inline-block h-4 w-4 text-center text-[9px] font-bold leading-4 ${r.result === 'W' ? 'bg-pitch-green text-pitch-green-ink' : r.result === 'D' ? 'bg-raised text-text-muted' : 'bg-alert-red text-alert-red-ink'}`}
        >
          {r.result}
        </span>
      ))}
    </span>
  )
}

function KeyPlayer({ p }: { p: PreviewKeyPlayer }) {
  return (
    <div className="flex items-baseline gap-2 py-0.5 text-sm">
      <span className="w-8 font-mono text-[10px] uppercase text-text-faint">{p.position}</span>
      <Link to={`/player/${p.player_id}`} className="min-w-0 truncate font-semibold text-text hover:text-pitch-green">{p.name}</Link>
      {p.mine && <span className="bg-pitch-green px-1 text-[9px] font-bold uppercase leading-4 text-pitch-green-ink">yours</span>}
      {p.doubt !== null && <span className="bg-broadcast-gold px-1 text-[9px] font-bold uppercase leading-4 text-broadcast-gold-ink" title={p.news ?? ''}>{p.doubt}%</span>}
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
          <Link to={`/club/${side.team_id}`} className="block truncate font-display text-2xl font-bold uppercase leading-none text-text hover:text-pitch-green">{side.name}</Link>
          <div className={`mt-1.5 flex items-center gap-2 ${home ? '' : 'justify-end'}`}>
            <FormDots side={side} />
            {side.difficulty !== null && (
              <span className={`px-1 font-mono text-[9px] font-bold leading-4 ${fdrFill(side.difficulty)}`} title="FPL fixture difficulty for this side">FDR {side.difficulty}</span>
            )}
          </div>
        </div>
      </div>
      <div className="mt-3 text-left">
        <div className="mb-1 flex items-baseline justify-between font-mono text-[10px] uppercase tracking-[0.06em] text-text-faint">
          <span>Top projected</span>
          <span>clean sheet {pct(cs)}</span>
        </div>
        {side.key_players.map((p) => <KeyPlayer key={p.player_id} p={p} />)}
        {side.absentees.length > 0 && (
          <div className="mt-1.5 border-t border-divider pt-1.5 text-[11px] text-text-muted">
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

function Card({ f }: { f: PreviewFixture }) {
  const yours = f.home.yours.length + f.away.yours.length
  const gap = f.market ? Math.round((f.model.home_win - f.market.home_win) * 100) : null
  return (
    <article className="border-b-2 border-divider px-10 py-6">
      <div className="mb-4 flex items-baseline justify-between font-mono text-[11px] uppercase tracking-[0.08em] text-text-faint">
        <span>{kickoffLabel(f.kickoff)}</span>
        {yours > 0 && (
          <span className="bg-pitch-green px-1.5 py-0.5 font-bold text-pitch-green-ink">
            {yours} of yours · {[...f.home.yours, ...f.away.yours].map((p) => p.name).join(', ')}
          </span>
        )}
      </div>
      <div className="grid grid-cols-[1fr_300px_1fr] gap-8">
        <Side side={f.home} home cs={f.model.home_clean_sheet} />
        <div className="flex flex-col items-center justify-start text-center">
          <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">Expected goals</div>
          <div className="tabular font-display text-5xl font-bold leading-none text-text">
            {f.xg.home.toFixed(1)}<span className="mx-2 text-text-faint">–</span>{f.xg.away.toFixed(1)}
          </div>
          <div className="mt-2 text-xs text-text-muted">
            most likely <span className="tabular font-bold text-text">{f.model.likely_score[0]}–{f.model.likely_score[1]}</span> at {pct(f.model.likely_score_p)}
          </div>
          <div className="mt-0.5 text-xs text-text-muted">3+ goals {pct(f.model.over_2_5)}</div>
        </div>
        <Side side={f.away} home={false} cs={f.model.away_clean_sheet} />
      </div>
      <div className="mt-5 space-y-1.5">
        <OutcomeBar h={f.model.home_win} d={f.model.draw} a={f.model.away_win} label="Model" />
        {f.market && <OutcomeBar h={f.market.home_win} d={f.market.draw} a={f.market.away_win} label="Market" faint />}
        <div className="pl-[68px] text-[11px] text-text-faint">
          {f.market
            ? `${f.home.short} / draw / ${f.away.short}. Market: ${f.market.bookmakers} bookmaker${f.market.bookmakers === 1 ? '' : 's'}, de-vigged. The model's home-win figure is ${gap === 0 ? 'level with' : `${Math.abs(gap ?? 0)} pts ${(gap ?? 0) > 0 ? 'above' : 'below'}`} the market's.`
            : `${f.home.short} / draw / ${f.away.short}. No odds stored for this fixture, so there is no market line to compare.`}
        </div>
      </div>
    </article>
  )
}

export function PreviewsScreen() {
  const state = useFetch(fetchPreviewsPayload, [], 600000)

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        {Array.from({ length: 3 }, (_, i) => <div key={i} className="border-b-2 border-divider px-10 py-6"><Skel className="h-[250px] w-full" /></div>)}
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
        <Masthead edition="Previews" title="No fixture left to preview" />
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
      <Masthead
        edition="Previews"
        title={`Gameweek ${d.event}, match by match`}
        right={<span className="text-text-muted">{d.fixtures.length} fixtures · model goals are the same ones every projection uses</span>}
      />
      {days.map((day) => (
        <section key={day.key}>
          <h2 className="border-b border-divider bg-panel px-10 py-2 font-display text-lg font-bold uppercase tracking-wide text-text">{day.key}</h2>
          {day.fixtures.map((f) => <Card key={f.fixture_id} f={f} />)}
        </section>
      ))}
    </div>
  )
}
