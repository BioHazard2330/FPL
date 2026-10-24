import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { XgRace } from '@/components/charts/XgRace'
import { crestUrl, fetchAuditPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { LuckRow, MatchRebuild } from '@/lib/types'

/** THE AUDIT - which points were earned and which were luck.
 *
 * Every player's gameweek points are set against the chances behind them (FPL's
 * own xG, xA and goals-against). The gap is the luck: goals from small chances,
 * assists the pass did not deserve, a clean sheet the defence did not earn. z is
 * that gap over its own standard error; above 2 is rare enough to be worth
 * asking whether it will repeat. The page explains the past - it does not feed
 * the projections, which already use chances and not results - and it does not
 * know whether a player is a genuinely better finisher than his xG. The matches
 * are rebuilt from their shots: the result the same chances would produce. */

const pct = (p: number) => `${Math.round(p * 100)}%`

function LuckBar({ v, scale }: { v: number; scale: number }) {
  const w = Math.min(1, Math.abs(v) / scale) * 50
  return (
    <span className="relative inline-block h-3 w-40 align-middle">
      <span className="absolute left-1/2 top-0 h-full w-px bg-divider" />
      <span className={`absolute top-0 h-full ${v >= 0 ? 'bg-broadcast-gold' : 'bg-broadcast-blue'}`} style={v >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }} />
    </span>
  )
}

function why(r: LuckRow): string {
  const bits: string[] = []
  if (Math.abs(r.goals_luck) >= 1.5) bits.push(`${r.goals} goal${r.goals === 1 ? '' : 's'} from ${r.xg.toFixed(1)} xG`)
  if (Math.abs(r.assists_luck) >= 1.5) bits.push(`${r.assists} assist${r.assists === 1 ? '' : 's'} from ${r.xa.toFixed(1)} xA`)
  if (Math.abs(r.cs_luck) >= 1.5) bits.push(`clean sheets ${r.cs_luck > 0 ? 'above' : 'below'} what the chances said`)
  if (Math.abs(r.conceded_luck) >= 1.5) bits.push(`goals against ${r.conceded_luck > 0 ? 'fewer' : 'more'} than expected`)
  return bits.join(' · ') || 'close to what the chances said'
}

function Row({ r, scale }: { r: LuckRow; scale: number }) {
  return (
    <div className="grid grid-cols-[2.2rem_minmax(0,1fr)_5.5rem_10.5rem_3rem] items-center gap-3 border-b border-divider py-2">
      <PlayerPhoto code={r.photo_code} teamCode={r.team_code} isGkp={r.position === 'GKP'} className="h-9 w-7" />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <Link to={`/player/${r.player_id}`} className="truncate text-sm font-bold text-text hover:text-pitch-green">{r.name}</Link>
          {r.mine && <span className="bg-pitch-green px-1 text-[12px] font-bold leading-4 text-pitch-green-ink">yours</span>}
          <span className="text-[12px] text-text-faint">{r.team_short} · {r.position}{r.owned !== null ? ` · ${r.owned.toFixed(0)}%` : ''}</span>
        </div>
        <div className="truncate text-[13px] text-text-muted">{why(r)}</div>
      </div>
      <div className="tabular text-right text-xs text-text-muted">
        <span className="font-bold text-text">{r.actual}</span> got
        <br />
        <span className="font-bold text-text">{r.deserved.toFixed(0)}</span> earned
      </div>
      <div className="text-center"><LuckBar v={r.luck} scale={scale} /></div>
      <div className={`tabular text-right text-sm font-bold ${r.z >= 2 ? 'text-broadcast-gold' : r.z <= -2 ? 'text-broadcast-blue' : 'text-text-muted'}`}>
        {r.z > 0 ? '+' : ''}{r.z.toFixed(1)}
      </div>
    </div>
  )
}

function Radar({ title, note, rows, scale }: { title: string; note: string; rows: LuckRow[]; scale: number }) {
  return (
    <div>
      <h3 className="font-display text-xl font-bold text-text">{title}</h3>
      <p className="mb-2 text-xs text-text-muted">{note}</p>
      {rows.map((r) => <Row key={r.player_id} r={r} scale={scale} />)}
    </div>
  )
}

function MatchCard({ m }: { m: MatchRebuild }) {
  const h = crestUrl(m.home.code)
  const a = crestUrl(m.away.code)
  const d = m.deserved
  const luckyHome = m.home.score - m.home.xg
  const luckyAway = m.away.score - m.away.xg
  const verdict =
    m.home.score > m.away.score ? (d.home_win >= 0.5 ? `${m.home.short} won it on the chances` : `${m.home.short} won a match that went the other way ${pct(1 - d.home_win)} of the time`)
    : m.home.score < m.away.score ? (d.away_win >= 0.5 ? `${m.away.short} won it on the chances` : `${m.away.short} won a match that went the other way ${pct(1 - d.away_win)} of the time`)
    : `A draw; the chances said ${pct(d.draw)} draw, ${pct(d.home_win)} ${m.home.short}, ${pct(d.away_win)} ${m.away.short}`
  return (
    <article className="border-b border-divider px-6 py-5">
      <div className="mb-2 flex items-center gap-3">
        {h && <img src={h} alt="" className="h-7 w-7" />}
        <span className="font-display text-xl font-bold text-text">{m.home.short}</span>
        <span className="tabular font-display text-3xl font-bold text-text">{m.home.score}–{m.away.score}</span>
        <span className="font-display text-xl font-bold text-text">{m.away.short}</span>
        {a && <img src={a} alt="" className="h-7 w-7" />}
        <span className="tabular ml-auto text-xs text-text-muted">
          xG <span className="font-bold text-pitch-green">{m.home.xg.toFixed(2)}</span> – <span className="font-bold text-broadcast-blue">{m.away.xg.toFixed(2)}</span>
        </span>
      </div>
      <XgRace match={m} />
      <div className="mt-2 flex h-4 w-full">
        <div className="flex items-center justify-center bg-pitch-green text-[12px] font-bold text-pitch-green-ink" style={{ width: `${d.home_win * 100}%` }}>{d.home_win >= 0.12 ? pct(d.home_win) : ''}</div>
        <div className="flex items-center justify-center bg-raised text-[12px] font-bold text-text-muted" style={{ width: `${d.draw * 100}%` }}>{d.draw >= 0.12 ? pct(d.draw) : ''}</div>
        <div className="flex items-center justify-center bg-broadcast-blue text-[12px] font-bold text-broadcast-blue-ink" style={{ width: `${d.away_win * 100}%` }}>{d.away_win >= 0.12 ? pct(d.away_win) : ''}</div>
      </div>
      <div className="mt-1.5 text-xs text-text-muted">
        {verdict}. Deserved score {d.likely_score[0]}–{d.likely_score[1]}.{' '}
        {Math.abs(luckyHome) >= 1 && <span>{m.home.short} scored {luckyHome > 0 ? `${luckyHome.toFixed(1)} more` : `${(-luckyHome).toFixed(1)} fewer`} than its chances. </span>}
        {Math.abs(luckyAway) >= 1 && <span>{m.away.short} scored {luckyAway > 0 ? `${luckyAway.toFixed(1)} more` : `${(-luckyAway).toFixed(1)} fewer`} than its chances.</span>}
      </div>
    </article>
  )
}

export function AuditScreen() {
  const [event, setEvent] = useState<number | undefined>(undefined)
  const [window, setWindow] = useState<'season' | 'recent'>('season')
  const state = useFetch(() => fetchAuditPayload(event), [event])

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="px-10 py-8"><Skel className="h-[420px] w-full" /></div>
      </div>
    )
  }
  if (state.status === 'error') {
    return <ScreenError title="Audit unavailable" description="The luck audit could not be built, so nothing here is known." message={state.error.message} />
  }
  const d = state.data
  const radar = window === 'season' ? d.radar_season : d.radar_recent
  const scale = Math.max(8, ...d.squad.map((r) => Math.abs(r.luck)), ...radar.hot.map((r) => Math.abs(r.luck)), ...radar.cold.map((r) => Math.abs(r.luck)))
  const hotMine = d.squad.filter((r) => r.z >= 1.5)
  const coldMine = d.squad.filter((r) => r.z <= -1.5)
  const luckTotal = d.squad.reduce((s, r) => s + r.luck, 0)

  return (
    <div className="data-in pb-16">
      <Masthead
        edition="The Audit"
        title="Points you got against points the chances said"
        right={<span className="text-text-muted">through GW{d.events[d.events.length - 1] ?? '—'}</span>}
      />

      <section className="border-b border-divider bg-panel px-10 py-6">
        <div className="max-w-4xl text-base leading-relaxed text-text-muted">
          Across your fifteen, <span className="tabular font-bold text-text">{luckTotal >= 0 ? '+' : ''}{luckTotal.toFixed(0)}</span> points this season are luck on the chances behind them
          {hotMine.length > 0 && <>; the ones riding it are <span className="font-bold text-broadcast-gold">{hotMine.map((r) => r.name).join(', ')}</span></>}
          {coldMine.length > 0 && <>; the ones owed some are <span className="font-bold text-broadcast-blue">{coldMine.map((r) => r.name).join(', ')}</span></>}
          . Luck is the points above what each player's xG, xA and goals-against implied. It is a reading of the past, not a forecast: a finisher who is truly better than his xG stays above it.
        </div>
      </section>

      <section className="border-b border-divider px-10 py-7">
        <h2 className="mb-3 font-display text-2xl font-bold text-text">Your squad</h2>
        {d.squad.map((r) => <Row key={r.player_id} r={r} scale={scale} />)}
        <p className="mt-2 text-[13px] text-text-faint">Bar: gold is luck in your favour, blue is points owed. z is the luck over its own standard error; beyond ±2 is unusual.</p>
      </section>

      {d.armband.length > 0 && (
        <section className="border-b border-divider px-10 py-7">
          <div className="mb-1 flex flex-wrap items-baseline justify-between gap-4">
            <h2 className="font-display text-2xl font-bold text-text">Your armband</h2>
            <span className="text-[13px] text-text-muted">
              the armband has cost <span className="tabular font-bold text-text">{d.armband.reduce((s, r) => s + r.cost, 0).toFixed(0)}</span> points against the best in each eleven;{' '}
              <span className="tabular font-bold text-broadcast-blue">{d.armband.reduce((s, r) => s + r.owed, 0).toFixed(0)}</span> of the captains' own returns were owed by their chances
            </span>
          </div>
          <p className="mb-3 max-w-3xl text-[13px] text-text-faint">
            Cost is what the armband left on the table against the highest scorer of that gameweek's eleven, the extra a captain earns, so it is nearly always positive. Owed is the same armband's points the captain's own chances said he should have had.
          </p>
          <div className="grid grid-cols-[3.5rem_minmax(0,1.2fr)_5rem_5rem_minmax(0,1.2fr)_5rem_5rem] gap-3 border-b border-divider pb-1.5 text-[12px] text-text-faint">
            <span>GW</span><span>Captain</span><span className="text-right">Scored</span><span className="text-right">Chances</span><span>Best in the eleven</span><span className="text-right">Cost</span><span className="text-right">Owed</span>
          </div>
          {d.armband.map((r) => (
            <div key={r.event} className="grid grid-cols-[3.5rem_minmax(0,1.2fr)_5rem_5rem_minmax(0,1.2fr)_5rem_5rem] items-center gap-3 border-b border-divider py-2 text-sm last:border-b-0">
              <span className="font-mono text-[13px] text-text-faint">GW{r.event}</span>
              <span className="min-w-0 truncate font-semibold text-text">
                <Link to={`/player/${r.captain.player_id}`} className="hover:text-pitch-green">{r.captain.name}</Link>
                {r.chip === '3xc' && <span className="ml-2 rounded bg-broadcast-gold px-1 text-[12px] font-bold text-broadcast-gold-ink">TC</span>}
              </span>
              <span className="tabular text-right font-bold text-text">{r.captain.actual}</span>
              <span className="tabular text-right text-text-muted">{r.captain.deserved.toFixed(1)}</span>
              <span className="min-w-0 truncate text-text-muted">
                <Link to={`/player/${r.best_actual.player_id}`} className="hover:text-pitch-green">{r.best_actual.name}</Link>{' '}
                <span className="tabular text-text-faint">{r.best_actual.actual}</span>
              </span>
              <span className={`tabular text-right font-bold ${r.cost > 0 ? 'text-alert-red' : 'text-pitch-green'}`}>{r.cost > 0 ? `−${r.cost.toFixed(0)}` : '0'}</span>
              <span className={`tabular text-right ${r.owed > 1 ? 'text-broadcast-blue' : r.owed < -1 ? 'text-broadcast-gold' : 'text-text-faint'}`}>{r.owed > 0 ? '+' : ''}{r.owed.toFixed(1)}</span>
            </div>
          ))}
        </section>
      )}

      <section className="border-b border-divider px-10 py-7">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
          <h2 className="font-display text-2xl font-bold text-text">Regression radar</h2>
          <div className="flex gap-1">
            {(['season', 'recent'] as const).map((w) => (
              <button key={w} type="button" onClick={() => setWindow(w)} className={`px-2.5 py-1 text-[13px] font-semibold ${window === w ? 'bg-text text-void' : 'bg-raised text-text-muted hover:text-text'}`}>
                {w === 'season' ? 'Whole season' : `Last ${d.thresholds.recent_gameweeks} gameweeks`}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-12">
          <Radar title="Running hot" note={`Most luck against their own chances (${window === 'season' ? `${d.thresholds.min_minutes}+ minutes` : '180+ minutes'}). Candidates to cool.`} rows={radar.hot} scale={scale} />
          <Radar title="Running cold" note="Least luck: the points owed. Candidates to turn, if the chances are still coming." rows={radar.cold} scale={scale} />
        </div>
      </section>

      <section className="px-0 py-7">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-4 px-10">
          <h2 className="font-display text-2xl font-bold text-text">Match rebuilds</h2>
          <div className="flex gap-1">
            {d.events.map((e) => (
              <button key={e} type="button" onClick={() => setEvent(e)} className={`px-2.5 py-1 text-[13px] font-semibold ${d.event === e ? 'bg-text text-void' : 'bg-raised text-text-muted hover:text-text'}`}>
                GW{e}
              </button>
            ))}
          </div>
        </div>
        <p className="mb-2 max-w-3xl px-10 text-xs text-text-muted">
          Each match replayed from its shots: cumulative xG against the clock, a ring on every goal, and the result those chances would produce in how many replays.
        </p>
        <div className="grid grid-cols-2 gap-px bg-divider">
          {d.matches.map((m) => <div key={m.match_id} className="bg-void"><MatchCard m={m} /></div>)}
        </div>
        {d.matches.length === 0 && <p className="px-10 py-6 text-sm text-text-muted">No finished match with shot data for this gameweek.</p>}
      </section>
    </div>
  )
}
