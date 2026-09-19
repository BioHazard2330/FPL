import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ShotAtlas, type Hover } from '@/components/football/ShotAtlas'
import { fetchAtlasPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { AtlasShot, PlayerShot } from '@/lib/types'

/** WHERE HE SHOOTS - his season on the Atlas pitch, over the league.
 *
 * His shots are the white hero dots, minute-labelled, a second ring on a
 * goal and a gold halo on his biggest chance - the same language as
 * isolating him on THE ATLAS. Underneath, when the league's shots have
 * loaded, the density field of every shot in the league this season,
 * so a reader can see whether he shoots from where goals come from. */

const OUTCOME_ONE: Record<string, string> = { Goal: 'Goal', AttemptSaved: 'Saved', Miss: 'Missed', Post: 'Hit the woodwork' }
const SITUATION_LABEL: Record<string, string> = {
  RegularPlay: 'Open play', FromCorner: 'From corner', FastBreak: 'Fast break', SetPiece: 'Set piece',
  ThrowInSetPiece: 'Throw-in', FreeKick: 'Free kick', IndividualPlay: 'Solo', Penalty: 'Penalty',
}

export function PlayerShots({ playerId, name, teamShort, shots, mine }: {
  playerId: number; name: string; teamShort: string; shots: PlayerShot[]; mine: boolean
}) {
  const league = useFetch(() => fetchAtlasPayload(), [], 0)
  const [hover, setHover] = useState<Hover>(null)
  const [showLeague, setShowLeague] = useState(true)

  const own: AtlasShot[] = useMemo(() => shots.map((s) => ({
    player_id: playerId, player: name, team_id: null, team: teamShort, team_code: null,
    minute: s.minute, x: s.x, y: s.y, xg: s.xg, outcome: s.outcome, situation: s.situation,
    foot: s.foot, match: s.match, mine,
  })), [shots, playerId, name, teamShort, mine])

  const leagueLoaded = league.status === 'ready'
  const field: AtlasShot[] = useMemo(() => {
    if (!leagueLoaded || !showLeague) return own
    return league.data.shots.filter((s) => s.player_id !== playerId).concat(own)
  }, [leagueLoaded, showLeague, league, own, playerId])
  const allVisible = useMemo(() => () => true, [])

  const goals = shots.filter((s) => s.outcome === 'Goal').length
  const xg = shots.reduce((a, s) => a + (s.xg ?? 0), 0)
  const onTarget = shots.filter((s) => s.outcome === 'Goal' || s.outcome === 'AttemptSaved').length
  const biggest = shots.reduce<PlayerShot | null>((b, s) => ((s.xg ?? 0) > (b?.xg ?? -1) ? s : b), null)
  const bySituation = useMemo(() => {
    const m = new Map<string, { n: number; xg: number; goals: number }>()
    for (const s of shots) {
      const k = s.situation ?? 'Unknown'
      const cur = m.get(k) ?? { n: 0, xg: 0, goals: 0 }
      cur.n += 1; cur.xg += s.xg ?? 0; cur.goals += s.outcome === 'Goal' ? 1 : 0
      m.set(k, cur)
    }
    return [...m.entries()].sort((a, b) => b[1].n - a[1].n)
  }, [shots])
  const byMatch = useMemo(() => {
    const m = new Map<string, { opp: string; home: boolean; score: string | null; n: number; xg: number; goals: number; kickoff: string | null; match_id: number | null }>()
    for (const s of shots) {
      const k = s.match ?? '?'
      const cur = m.get(k) ?? { opp: s.opponent_short ?? '?', home: s.is_home, score: s.score, n: 0, xg: 0, goals: 0, kickoff: s.kickoff, match_id: s.match_id }
      cur.n += 1; cur.xg += s.xg ?? 0; cur.goals += s.outcome === 'Goal' ? 1 : 0
      m.set(k, cur)
    }
    return [...m.entries()]
  }, [shots])

  if (!shots.length) {
    return (
      <p className="max-w-2xl text-sm text-text-muted">
        No shot has been recorded for {name} in a synced match this season. That is a real absence in the shot feed
        (or a season without a shot), never a blank drawn as zero.
      </p>
    )
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-8">
      <div className="relative">
        <div className="mb-2 flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowLeague((v) => !v)}
            disabled={!leagueLoaded}
            className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] transition-colors ${showLeague && leagueLoaded ? 'bg-text text-void' : 'bg-raised text-text-muted hover:text-text'} disabled:opacity-50`}
          >
            League underneath
          </button>
          <span className="text-[11px] text-text-faint">
            {league.status === 'loading' ? 'loading the league’s shots…' : leagueLoaded ? `${league.data.totals.shots.toLocaleString()} league shots as a density field` : 'league shots unavailable'}
          </span>
          <Link to="/atlas" className="ml-auto text-[10px] font-bold uppercase tracking-[0.14em] text-broadcast-blue hover:underline">Open on the Atlas</Link>
        </div>
        <div className="h-[520px]">
          <ShotAtlas shots={field} visible={allVisible} heroId={playerId} showHeat={leagueLoaded && showLeague} onHover={setHover} />
        </div>
        {hover && hover.shot.player_id === playerId && (
          <div className="pointer-events-none fixed z-50 border-l-2 border-text bg-raised px-3 py-2 text-xs"
               style={{ left: hover.px + 14, top: hover.py + 14 }}>
            <div className="tabular text-text">
              {hover.shot.minute !== null ? `${hover.shot.minute}' · ` : ''}
              <span className={hover.shot.outcome === 'Goal' ? 'font-bold text-pitch-green' : ''}>{OUTCOME_ONE[hover.shot.outcome] ?? hover.shot.outcome}</span>
              {' · '}{hover.shot.xg !== null ? `${hover.shot.xg.toFixed(2)} xG` : 'no xG'}
            </div>
            <div className="mt-0.5 text-text-muted">
              {SITUATION_LABEL[hover.shot.situation ?? ''] ?? hover.shot.situation}{hover.shot.foot ? ` · ${hover.shot.foot}` : ''}
            </div>
          </div>
        )}
      </div>

      <div className="space-y-5">
        <div className="grid grid-cols-4 gap-x-3">
          <Big label="shots" value={shots.length} />
          <Big label="on target" value={onTarget} />
          <Big label="xG" value={xg.toFixed(1)} tone="green" />
          <Big label="goals" value={goals} tone={goals - xg >= 0 ? 'green' : 'red'} />
        </div>
        <div className={`tabular text-xs font-semibold ${goals - xg >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
          {goals - xg >= 0 ? '+' : ''}{(goals - xg).toFixed(1)} <span className="font-normal text-text-faint">goals minus xG · {(xg / shots.length).toFixed(2)} xG per shot</span>
        </div>
        {biggest && (
          <div className="border-t border-divider pt-4">
            <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">Biggest chance</div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="tabular font-display text-2xl font-bold text-broadcast-gold">{(biggest.xg ?? 0).toFixed(2)}</span>
              <span className="tabular text-xs text-text-muted">
                {biggest.minute}' {biggest.is_home ? 'v' : 'at'} {biggest.opponent_short}{' · '}
                <span className={biggest.outcome === 'Goal' ? 'font-bold text-pitch-green' : 'text-alert-red'}>{OUTCOME_ONE[biggest.outcome] ?? biggest.outcome}</span>
              </span>
            </div>
          </div>
        )}
        <div className="border-t border-divider pt-4">
          <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">By situation</div>
          {bySituation.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[1fr_auto_auto_auto] items-baseline gap-3 border-b border-divider py-1.5 text-xs">
              <span className="text-text">{SITUATION_LABEL[k] ?? k}</span>
              <span className="tabular text-text-muted">{v.n} sh</span>
              <span className="tabular text-pitch-green">{v.xg.toFixed(2)} xG</span>
              <span className="tabular font-semibold text-text">{v.goals} G</span>
            </div>
          ))}
        </div>
        <div className="border-t border-divider pt-4">
          <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">By match</div>
          {byMatch.map(([k, v]) => (
            <Link key={k} to={`/match/${v.match_id ?? ''}`} className="grid grid-cols-[1fr_auto_auto_auto] items-baseline gap-3 border-b border-divider py-1.5 text-xs hover:bg-raised/60">
              <span className="text-text">{v.home ? 'v' : 'at'} {v.opp} <span className="text-text-faint">{v.score ?? ''}</span></span>
              <span className="tabular text-text-muted">{v.n} sh</span>
              <span className="tabular text-pitch-green">{v.xg.toFixed(2)}</span>
              <span className="tabular font-semibold text-text">{v.goals} G</span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}

function Big({ label, value, tone }: { label: string; value: number | string; tone?: 'green' | 'red' }) {
  const color = tone === 'green' ? 'text-pitch-green' : tone === 'red' ? 'text-alert-red' : 'text-text'
  return (
    <div>
      <div className={`tabular font-display text-3xl font-bold ${color}`}>{value}</div>
      <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-text-faint">{label}</div>
    </div>
  )
}
