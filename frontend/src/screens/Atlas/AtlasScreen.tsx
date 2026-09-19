import { useMemo, useState } from 'react'
import { Masthead } from '@/components/shell/Masthead'
import { ShotAtlas, type Hover } from '@/components/football/ShotAtlas'
import { fetchAtlasPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import type { AtlasPayload, AtlasShot } from '@/lib/types'

/** THE ATLAS - the whole league's shooting, on one pitch.
 *
 * 1,136 real shots across 41 matches were sitting in `match_shots` with
 * nowhere to be seen except one match at a time. This is the screen that
 * shows the season's attacking football as a single picture: where the
 * chances come from, who takes them, who finishes them and who doesn't.
 *
 * Everything is a real shot. Filters only hide dots, never invent them, and
 * the rail's numbers are sums of the dots on screen. The one derived layer,
 * zone xG, is a plain mean of the dots inside each cell and shows its own
 * shot count so a cell built on three shots reads as three shots. */

type Scope = 'all' | 'mine'
const OUTCOMES = ['Goal', 'AttemptSaved', 'Miss', 'Post'] as const
const OUTCOME_LABEL: Record<string, string> = { Goal: 'Goals', AttemptSaved: 'Saved', Miss: 'Missed', Post: 'Woodwork' }
const OUTCOME_ONE: Record<string, string> = { Goal: 'Goal', AttemptSaved: 'Saved', Miss: 'Missed', Post: 'Hit the woodwork' }
const SITUATION_LABEL: Record<string, string> = {
  RegularPlay: 'Open play', FromCorner: 'From corner', FastBreak: 'Fast break', SetPiece: 'Set piece',
  ThrowInSetPiece: 'Throw-in', FreeKick: 'Free kick', IndividualPlay: 'Solo', Penalty: 'Penalty',
}

function Toggle({ on, onClick, children, tone = 'text' }: { on: boolean; onClick: () => void; children: React.ReactNode; tone?: 'text' | 'gold' }) {
  const active = tone === 'gold' ? 'bg-broadcast-gold text-broadcast-gold-ink' : 'bg-text text-void'
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] transition-colors ${on ? active : 'bg-raised text-text-muted hover:text-text'}`}
    >
      {children}
    </button>
  )
}

export function AtlasScreen() {
  const state = useFetch(fetchAtlasPayload, [], 300000)
  const [scope, setScope] = useState<Scope>('all')
  const [team, setTeam] = useState<number | null>(null)
  const [situation, setSituation] = useState<string | null>(null)
  const [outcomes, setOutcomes] = useState<Set<string>>(new Set(OUTCOMES))
  const [player, setPlayer] = useState<number | null>(null)
  const [showZones, setShowZones] = useState(false)
  const [hover, setHover] = useState<Hover>(null)

  const data: AtlasPayload | null = state.status === 'ready' ? state.data : null

  const matches = useMemo(() => {
    if (!data) return () => false
    return (s: AtlasShot) =>
      (scope === 'all' || s.mine) &&
      (team === null || s.team_id === team) &&
      (situation === null || s.situation === situation) &&
      outcomes.has(s.outcome) &&
      (player === null || s.player_id === player)
  }, [data, scope, team, situation, outcomes, player])

  const visible = useMemo(() => (data ? data.shots.filter(matches) : []), [data, matches])

  const rail = useMemo(() => {
    // Shooters ranked over the dots currently visible - the rail always
    // describes the pitch beside it, never a different population.
    const by = new Map<number, { player: string; team: string | null; shots: number; goals: number; xg: number; mine: boolean }>()
    for (const s of visible) {
      if (s.player_id === null) continue
      const p = by.get(s.player_id) ?? { player: s.player, team: s.team, shots: 0, goals: 0, xg: 0, mine: s.mine }
      p.shots += 1; p.goals += s.outcome === 'Goal' ? 1 : 0; p.xg += s.xg ?? 0
      by.set(s.player_id, p)
    }
    return [...by.entries()].map(([id, p]) => ({ id, ...p })).sort((a, b) => b.xg - a.xg).slice(0, 18)
  }, [visible])

  const sums = useMemo(() => ({
    shots: visible.length,
    goals: visible.filter((s) => s.outcome === 'Goal').length,
    xg: visible.reduce((a, s) => a + (s.xg ?? 0), 0),
  }), [visible])

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="px-10 py-8"><Skel className="h-[520px] w-full" /></div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="No shots to show"
        description="The shot atlas could not be fetched. Every dot on this screen is a real recorded shot, so an empty atlas means the data is unavailable right now, not that nobody has shot."
        message={state.error.message}
      />
    )
  }
  if (!data || !data.has_shots) {
    return (
      <div>
        <Masthead edition="The Atlas" title="Every shot this season" />
        <div className="px-10 py-16 text-sm text-text-muted">No synced matches carry shot data yet.</div>
      </div>
    )
  }

  const t = data.totals
  const overperf = sums.goals - sums.xg
  const teamsSorted = data.teams.slice().sort((a, b) => (a.team ?? '').localeCompare(b.team ?? ''))

  return (
    <div className="pb-16">
      <Masthead edition="The Atlas" title="Every shot this season" />

      {/* HEADLINE NUMBERS - the whole league, then your slice of it */}
      <div className="flex flex-wrap items-baseline gap-x-10 gap-y-3 border-b-2 border-divider px-10 py-6">
        <div><span className="tabular font-display text-4xl font-bold text-text">{t.shots}</span><span className="ml-2 text-[10px] uppercase tracking-wide text-text-faint">shots · {t.matches} matches</span></div>
        <div><span className="tabular font-display text-4xl font-bold text-text">{t.goals}</span><span className="ml-2 text-[10px] uppercase tracking-wide text-text-faint">goals</span></div>
        <div><span className="tabular font-display text-4xl font-bold text-text">{t.xg.toFixed(1)}</span><span className="ml-2 text-[10px] uppercase tracking-wide text-text-faint">xG</span></div>
        <div className="ml-auto flex items-baseline gap-2 border-l-2 border-broadcast-gold pl-4">
          <span className="tabular font-display text-3xl font-bold text-broadcast-gold">{t.mine_goals}</span>
          <span className="text-[10px] uppercase tracking-wide text-text-faint">your goals from</span>
          <span className="tabular text-xl font-bold text-broadcast-gold">{t.mine_xg.toFixed(1)}</span>
          <span className="text-[10px] uppercase tracking-wide text-text-faint">xG · {t.mine_shots} shots</span>
          <span className={`tabular ml-2 text-sm font-bold ${t.mine_goals - t.mine_xg >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
            {t.mine_goals - t.mine_xg >= 0 ? '+' : ''}{(t.mine_goals - t.mine_xg).toFixed(1)}
          </span>
        </div>
      </div>

      {/* CONTROLS */}
      <div className="flex flex-wrap items-center gap-2 border-b border-divider px-10 py-3">
        <Toggle on={scope === 'all'} onClick={() => setScope('all')}>League</Toggle>
        <Toggle on={scope === 'mine'} onClick={() => setScope('mine')} tone="gold">My squad</Toggle>
        <span className="mx-2 h-4 w-px bg-divider" />
        {OUTCOMES.map((o) => (
          <Toggle key={o} on={outcomes.has(o)} onClick={() => {
            const next = new Set(outcomes); next.has(o) ? next.delete(o) : next.add(o); setOutcomes(next)
          }}>{OUTCOME_LABEL[o]}</Toggle>
        ))}
        <span className="mx-2 h-4 w-px bg-divider" />
        <select
          value={situation ?? ''}
          onChange={(e) => setSituation(e.target.value || null)}
          className="bg-raised px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-text-muted"
        >
          <option value="">Any situation</option>
          {data.situations.map(([s, n]) => <option key={s} value={s}>{SITUATION_LABEL[s] ?? s} ({n})</option>)}
        </select>
        <select
          value={team ?? ''}
          onChange={(e) => setTeam(e.target.value ? Number(e.target.value) : null)}
          className="bg-raised px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-text-muted"
        >
          <option value="">Any club</option>
          {teamsSorted.map((tm) => <option key={tm.team_id} value={tm.team_id}>{tm.team} · {tm.shots}</option>)}
        </select>
        <span className="mx-2 h-4 w-px bg-divider" />
        <Toggle on={showZones} onClick={() => setShowZones(!showZones)}>Zone xG</Toggle>
        {player !== null && (
          <button type="button" onClick={() => setPlayer(null)} className="ml-2 text-[10px] font-bold uppercase tracking-[0.12em] text-broadcast-gold">
            × clear player
          </button>
        )}
        <div className="ml-auto text-[10px] uppercase tracking-wide text-text-faint">
          showing <span className="tabular font-bold text-text">{sums.shots}</span> shots ·{' '}
          <span className="tabular font-bold text-text">{sums.goals}</span> goals ·{' '}
          <span className="tabular font-bold text-text">{sums.xg.toFixed(1)}</span> xG ·{' '}
          <span className={`tabular font-bold ${overperf >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{overperf >= 0 ? '+' : ''}{overperf.toFixed(1)}</span>
        </div>
      </div>

      {/* THE PITCH + THE RAIL */}
      <div className="grid grid-cols-[1fr_300px] gap-0">
        <div className="relative border-r border-divider px-6 py-6">
          <div className="h-[66vh]">
          <ShotAtlas
            shots={data.shots}
            zones={data.zones}
            showZones={showZones}
            dim={(s) => !matches(s)}
            onHover={setHover}
          />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[10px] uppercase tracking-wide text-text-faint">
            <span><span className="mr-1.5 inline-block size-2 rounded-full bg-broadcast-gold align-middle" />your player, goal</span>
            <span><span className="mr-1.5 inline-block size-2 rounded-full border border-broadcast-gold align-middle" />your player, no goal</span>
            <span><span className="mr-1.5 inline-block size-2 rounded-full bg-broadcast-blue align-middle" />league, goal</span>
            <span><span className="mr-1.5 inline-block size-2 rounded-full border border-broadcast-blue align-middle" />league, no goal</span>
            <span><span className="mr-1.5 inline-block size-2 rounded-full border-2 border-alert-red align-middle" />hit the woodwork</span>
            <span className="ml-auto">dot area = xG · goal on the right</span>
          </div>

          {hover && (
            <div
              className="pointer-events-none fixed z-50 border-l-2 bg-raised px-3 py-2 text-xs"
              style={{ left: hover.px + 14, top: hover.py + 14, borderColor: hover.shot.mine ? 'var(--broadcast-gold)' : 'var(--broadcast-blue)' }}
            >
              <div className="font-semibold text-text">{hover.shot.player} <span className="text-text-faint">{hover.shot.team}</span></div>
              <div className="tabular text-text-muted">
                {hover.shot.minute !== null ? `${hover.shot.minute}' · ` : ''}
                <span className={hover.shot.outcome === 'Goal' ? 'font-bold text-pitch-green' : ''}>{OUTCOME_ONE[hover.shot.outcome] ?? hover.shot.outcome}</span>
                {' · '}{hover.shot.xg !== null ? `${hover.shot.xg.toFixed(2)} xG` : 'no xG'}
              </div>
              <div className="text-[10px] uppercase tracking-wide text-text-faint">
                {SITUATION_LABEL[hover.shot.situation ?? ''] ?? hover.shot.situation}{hover.shot.foot ? ` · ${hover.shot.foot}` : ''}
              </div>
            </div>
          )}
        </div>

        <div className="px-5 py-6">
          <div className="mb-3 text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">
            Shooters on this pitch · by xG
          </div>
          {rail.map((p) => {
            const diff = p.goals - p.xg
            const active = player === p.id
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => setPlayer(active ? null : p.id)}
                className={`grid w-full grid-cols-[1fr_auto_auto_auto] items-baseline gap-3 border-b border-divider py-2 text-left transition-colors hover:bg-raised/60 ${active ? 'bg-raised' : ''}`}
              >
                <div className="truncate">
                  <span className={`text-sm font-semibold ${p.mine ? 'text-broadcast-gold' : 'text-text'}`}>{p.player}</span>
                  <span className="ml-1.5 text-[10px] uppercase text-text-faint">{p.team}</span>
                </div>
                <div className="tabular text-xs text-text-muted">{p.shots}<span className="text-text-faint">sh</span></div>
                <div className="tabular text-xs text-text-muted">{p.xg.toFixed(1)}<span className="text-text-faint">xG</span></div>
                <div className={`tabular w-12 text-right text-xs font-bold ${diff > 0.5 ? 'text-pitch-green' : diff < -0.5 ? 'text-alert-red' : 'text-text-muted'}`}>
                  {p.goals}<span className="text-[10px] font-normal text-text-faint">g</span>
                  <span className="ml-1 text-[10px]">{diff >= 0 ? '+' : ''}{diff.toFixed(1)}</span>
                </div>
              </button>
            )
          })}
          <div className="mt-3 text-[10px] leading-relaxed text-text-faint">
            Last column: goals, and goals minus xG. Green is finishing above the chances taken; red is below.
            Neither is a projection.
          </div>
        </div>
      </div>

      <div className="border-t-2 border-divider bg-raised/40 px-10 py-6">
        <div className="mb-2 text-[11px] font-bold uppercase tracking-wide text-broadcast-gold">What this is</div>
        <div className="max-w-3xl text-xs leading-relaxed text-text-muted">{data.method}</div>
      </div>
    </div>
  )
}
