import { useMemo, useState } from 'react'
import { Masthead } from '@/components/shell/Masthead'
import { ShotAtlas, type Hover } from '@/components/football/ShotAtlas'
import { fetchAtlasPayload, shirtUrl } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { Skel, SkelMasthead, ScreenError } from '@/components/shell/ScreenStates'
import type { AtlasPayload, AtlasShot } from '@/lib/types'

/** THE ATLAS - the whole league's shooting on one pitch, and any one
 * player's season on it when you ask.
 *
 * Everything is a real recorded shot. Filters hide dots, never invent them;
 * the rail's numbers are sums over exactly the dots on screen; the story
 * strip is the same dots sorted. The one derived layer, heat, is a smoothed
 * density of what is on screen and says so. */

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
    <button type="button" onClick={onClick}
      className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] transition-colors ${on ? active : 'bg-raised text-text-muted hover:text-text'}`}>
      {children}
    </button>
  )
}

function Big({ v, label, tone = 'text-text' }: { v: string; label: string; tone?: string }) {
  return (
    <div>
      <div className={`tabular font-display text-4xl font-bold leading-none ${tone}`}>{v}</div>
      <div className="mt-1 text-[10px] uppercase tracking-[0.14em] text-text-faint">{label}</div>
    </div>
  )
}

/** HERO - the pitch belongs to one player. Shirt, name in the display
 * face, his season in four numbers, and the two shots that define it: the
 * biggest chance he had (whatever he did with it) and, if he scored one,
 * the coldest finish - the goal from the least likely chance. */
function HeroBand({ shots, onClear }: { shots: AtlasShot[]; onClear: () => void }) {
  const first = shots[0]
  const goals = shots.filter((s) => s.outcome === 'Goal')
  const xg = shots.reduce((a, s) => a + (s.xg ?? 0), 0)
  const biggest = shots.reduce<AtlasShot | null>((b, s) => ((s.xg ?? 0) > (b?.xg ?? -1) ? s : b), null)
  const coldest = goals.reduce<AtlasShot | null>((b, s) => ((s.xg ?? 9) < (b?.xg ?? 9) ? s : b), null)
  const diff = goals.length - xg
  const shirt = shirtUrl(first.team_code, false, 110)

  return (
    <div className="data-in flex flex-wrap items-center gap-x-10 gap-y-4 border-b-2 border-divider bg-panel px-10 py-6">
      {shirt && <img src={shirt} alt="" className="h-16 w-auto" />}
      <div className="min-w-[220px]">
        <div className="font-display text-5xl font-bold uppercase leading-none tracking-tight text-text">{first.player}</div>
        <div className="mt-1 text-[11px] uppercase tracking-[0.18em] text-text-faint">{first.team} · this season, every shot</div>
      </div>
      <Big v={String(shots.length)} label="shots" />
      <Big v={xg.toFixed(1)} label="xG" />
      <Big v={String(goals.length)} label="goals" />
      <Big v={`${diff >= 0 ? '+' : ''}${diff.toFixed(1)}`} label="goals minus xG" tone={diff >= 0.5 ? 'text-pitch-green' : diff <= -0.5 ? 'text-alert-red' : 'text-text'} />
      <div className="ml-auto grid gap-2 text-xs">
        {biggest && (
          <div className="flex items-baseline gap-2">
            <span className="inline-block size-2 rounded-full border border-dashed border-broadcast-gold" />
            <span className="text-text-faint">biggest chance</span>
            <span className="tabular font-semibold text-text">{(biggest.xg ?? 0).toFixed(2)} xG</span>
            <span className="text-text-muted">{biggest.minute !== null ? `${biggest.minute}'` : ''} · {OUTCOME_ONE[biggest.outcome] ?? biggest.outcome}</span>
          </div>
        )}
        {coldest && (
          <div className="flex items-baseline gap-2">
            <span className="inline-block size-2 rounded-full bg-text" />
            <span className="text-text-faint">coldest finish</span>
            <span className="tabular font-semibold text-text">{(coldest.xg ?? 0).toFixed(2)} xG</span>
            <span className="text-text-muted">{coldest.minute !== null ? `${coldest.minute}'` : ''} · {SITUATION_LABEL[coldest.situation ?? ''] ?? coldest.situation}</span>
          </div>
        )}
      </div>
      <button type="button" onClick={onClear} className="text-[10px] font-bold uppercase tracking-[0.14em] text-broadcast-gold hover:text-text">
        × back to the league
      </button>
    </div>
  )
}

export function AtlasScreen() {
  const state = useFetch(fetchAtlasPayload, [], 300000)
  const [scope, setScope] = useState<Scope>('all')
  const [team, setTeam] = useState<number | null>(null)
  const [situation, setSituation] = useState<string | null>(null)
  const [outcomes, setOutcomes] = useState<Set<string>>(new Set(OUTCOMES))
  const [hero, setHero] = useState<number | null>(null)
  const [showHeat, setShowHeat] = useState(false)
  const [hover, setHover] = useState<Hover>(null)

  const data: AtlasPayload | null = state.status === 'ready' ? state.data : null

  const visible = useMemo(() => {
    return (s: AtlasShot) =>
      (scope === 'all' || s.mine) &&
      (team === null || s.team_id === team) &&
      (situation === null || s.situation === situation) &&
      outcomes.has(s.outcome) &&
      (hero === null || s.player_id === hero)
  }, [scope, team, situation, outcomes, hero])

  const onScreen = useMemo(() => (data ? data.shots.filter(visible) : []), [data, visible])
  const heroShots = useMemo(() => (data && hero !== null ? data.shots.filter((s) => s.player_id === hero) : []), [data, hero])

  const rail = useMemo(() => {
    // Ranked over the dots on screen when no hero is set; over the full
    // filtered league when one is, so the rail stays a place to pick from.
    const pool = hero === null ? onScreen : (data?.shots ?? []).filter((s) =>
      (scope === 'all' || s.mine) && (team === null || s.team_id === team) && (situation === null || s.situation === situation) && outcomes.has(s.outcome))
    const by = new Map<number, { player: string; team: string | null; shots: number; goals: number; xg: number; mine: boolean }>()
    for (const s of pool) {
      if (s.player_id === null) continue
      const p = by.get(s.player_id) ?? { player: s.player, team: s.team, shots: 0, goals: 0, xg: 0, mine: s.mine }
      p.shots += 1; p.goals += s.outcome === 'Goal' ? 1 : 0; p.xg += s.xg ?? 0
      by.set(s.player_id, p)
    }
    return [...by.entries()].map(([id, p]) => ({ id, ...p })).sort((a, b) => b.xg - a.xg).slice(0, 22)
  }, [onScreen, data, hero, scope, team, situation, outcomes])

  const story = useMemo(() => {
    if (!data) return null
    const pool = data.shots.filter((s) => (scope === 'all' || s.mine))
    const misses = pool.filter((s) => s.outcome !== 'Goal' && s.xg !== null).sort((a, b) => (b.xg ?? 0) - (a.xg ?? 0)).slice(0, 5)
    const cold = pool.filter((s) => s.outcome === 'Goal' && s.xg !== null).sort((a, b) => (a.xg ?? 0) - (b.xg ?? 0)).slice(0, 5)
    return { misses, cold }
  }, [data, scope])

  const sums = useMemo(() => ({
    shots: onScreen.length,
    goals: onScreen.filter((s) => s.outcome === 'Goal').length,
    xg: onScreen.reduce((a, s) => a + (s.xg ?? 0), 0),
  }), [onScreen])

  if (state.status === 'loading') {
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="px-10 py-8"><Skel className="h-[560px] w-full" /></div>
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
      <Masthead edition="The Atlas" title={hero !== null && heroShots[0] ? heroShots[0].player : 'Every shot this season'} />

      {hero !== null && heroShots.length > 0 ? (
        <HeroBand shots={heroShots} onClear={() => setHero(null)} />
      ) : (
        <div className="flex flex-wrap items-baseline gap-x-10 gap-y-3 border-b-2 border-divider px-10 py-6">
          <Big v={String(t.shots)} label={`shots · ${t.matches} matches`} />
          <Big v={String(t.goals)} label="goals" />
          <Big v={t.xg.toFixed(1)} label="xG" />
          <div className="ml-auto flex items-baseline gap-3 border-l-2 border-broadcast-gold pl-5">
            <Big v={String(t.mine_goals)} label="your goals" tone="text-broadcast-gold" />
            <Big v={t.mine_xg.toFixed(1)} label={`from xG · ${t.mine_shots} shots`} tone="text-broadcast-gold" />
            <Big v={`${t.mine_goals - t.mine_xg >= 0 ? '+' : ''}${(t.mine_goals - t.mine_xg).toFixed(1)}`} label="finishing" tone={t.mine_goals - t.mine_xg >= 0 ? 'text-pitch-green' : 'text-alert-red'} />
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-b border-divider px-10 py-3">
        <Toggle on={scope === 'all'} onClick={() => setScope('all')}>League</Toggle>
        <Toggle on={scope === 'mine'} onClick={() => setScope('mine')} tone="gold">My squad</Toggle>
        <span className="mx-2 h-4 w-px bg-divider" />
        {OUTCOMES.map((o) => (
          <Toggle key={o} on={outcomes.has(o)} onClick={() => { const n = new Set(outcomes); n.has(o) ? n.delete(o) : n.add(o); setOutcomes(n) }}>
            {OUTCOME_LABEL[o]}
          </Toggle>
        ))}
        <span className="mx-2 h-4 w-px bg-divider" />
        <select value={situation ?? ''} onChange={(e) => setSituation(e.target.value || null)}
          className="bg-raised px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-text-muted">
          <option value="">Any situation</option>
          {data.situations.map(([s, n]) => <option key={s} value={s}>{SITUATION_LABEL[s] ?? s} ({n})</option>)}
        </select>
        <select value={team ?? ''} onChange={(e) => setTeam(e.target.value ? Number(e.target.value) : null)}
          className="bg-raised px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-text-muted">
          <option value="">Any club</option>
          {teamsSorted.map((tm) => <option key={tm.team_id} value={tm.team_id}>{tm.team} · {tm.shots}</option>)}
        </select>
        <span className="mx-2 h-4 w-px bg-divider" />
        <Toggle on={showHeat} onClick={() => setShowHeat(!showHeat)}>Heat</Toggle>
        <div className="ml-auto text-[10px] uppercase tracking-wide text-text-faint">
          on the pitch <span className="tabular font-bold text-text">{sums.shots}</span> shots ·{' '}
          <span className="tabular font-bold text-text">{sums.goals}</span> goals ·{' '}
          <span className="tabular font-bold text-text">{sums.xg.toFixed(1)}</span> xG ·{' '}
          <span className={`tabular font-bold ${overperf >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{overperf >= 0 ? '+' : ''}{overperf.toFixed(1)}</span>
        </div>
      </div>

      <div className="grid grid-cols-[1fr_300px]">
        <div className="relative border-r border-divider bg-void px-6 py-6">
          <div className="h-[68vh]">
            <ShotAtlas shots={data.shots} visible={visible} heroId={hero} showHeat={showHeat} onHover={setHover} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[10px] uppercase tracking-wide text-text-faint">
            <span><span className="mr-1.5 inline-block size-2 rounded-full bg-broadcast-gold align-middle" />your player, goal</span>
            <span><span className="mr-1.5 inline-block size-2 rounded-full border border-broadcast-gold align-middle" />your player, no goal</span>
            <span><span className="mr-1.5 inline-block size-2 rounded-full bg-broadcast-blue align-middle" />league, goal</span>
            <span><span className="mr-1.5 inline-block size-2 rounded-full border border-broadcast-blue align-middle" />league, no goal</span>
            <span><span className="mr-1.5 inline-block size-2 rounded-full border-2 border-alert-red align-middle" />woodwork</span>
            {showHeat && <span><span className="mr-1.5 inline-block h-2 w-3 bg-pitch-green/70 align-middle" />smoothed shot density, xG-weighted</span>}
            <span className="ml-auto">dot area = xG · attacking right</span>
          </div>

          {hover && (
            <div className="pointer-events-none fixed z-50 border-l-2 bg-raised px-3 py-2 text-xs"
              style={{ left: hover.px + 14, top: hover.py + 14, borderColor: hover.shot.mine ? 'var(--broadcast-gold)' : 'var(--broadcast-blue)' }}>
              <div className="font-display text-base font-bold uppercase text-text">{hover.shot.player} <span className="text-text-faint">{hover.shot.team}</span></div>
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
            {hero === null ? 'Shooters on this pitch · by xG' : 'Pick another'}
          </div>
          {rail.map((p) => {
            const diff = p.goals - p.xg
            const active = hero === p.id
            return (
              <button key={p.id} type="button" onClick={() => setHero(active ? null : p.id)}
                className={`grid w-full grid-cols-[1fr_auto_auto_auto] items-baseline gap-3 border-b border-divider py-2 text-left transition-colors hover:bg-raised/60 ${active ? 'bg-raised' : ''}`}>
                <div className="truncate">
                  <span className={`text-sm font-semibold ${active ? 'text-text' : p.mine ? 'text-broadcast-gold' : 'text-text'}`}>{p.player}</span>
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
        </div>
      </div>

      {/* THE STORY - the same dots, sorted into the two lists football
          people actually argue about. */}
      {story && (
        <div className="grid grid-cols-2 gap-10 border-t-2 border-divider px-10 py-8">
          <div>
            <div className="mb-3 text-[11px] font-bold uppercase tracking-wide text-alert-red">
              Biggest chances not taken{scope === 'mine' ? ' · your squad' : ''}
            </div>
            {story.misses.map((s, i) => (
              <button key={i} type="button" onClick={() => s.player_id !== null && setHero(s.player_id)}
                className="grid w-full grid-cols-[2.5rem_1fr_auto] items-baseline gap-3 border-b border-divider py-2 text-left hover:bg-raised/60">
                <span className="tabular font-display text-xl font-bold text-alert-red">{(s.xg ?? 0).toFixed(2)}</span>
                <span className="truncate"><span className="font-semibold text-text">{s.player}</span> <span className="text-[10px] uppercase text-text-faint">{s.team} · {s.minute}'</span></span>
                <span className="text-[10px] uppercase tracking-wide text-text-faint">{OUTCOME_ONE[s.outcome] ?? s.outcome}</span>
              </button>
            ))}
          </div>
          <div>
            <div className="mb-3 text-[11px] font-bold uppercase tracking-wide text-pitch-green">
              Coldest finishes{scope === 'mine' ? ' · your squad' : ''}
            </div>
            {story.cold.map((s, i) => (
              <button key={i} type="button" onClick={() => s.player_id !== null && setHero(s.player_id)}
                className="grid w-full grid-cols-[2.5rem_1fr_auto] items-baseline gap-3 border-b border-divider py-2 text-left hover:bg-raised/60">
                <span className="tabular font-display text-xl font-bold text-pitch-green">{(s.xg ?? 0).toFixed(2)}</span>
                <span className="truncate"><span className="font-semibold text-text">{s.player}</span> <span className="text-[10px] uppercase text-text-faint">{s.team} · {s.minute}'</span></span>
                <span className="text-[10px] uppercase tracking-wide text-text-faint">{SITUATION_LABEL[s.situation ?? ''] ?? s.situation}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="border-t border-divider bg-raised/40 px-10 py-6">
        <div className="mb-2 text-[11px] font-bold uppercase tracking-wide text-broadcast-gold">What this is</div>
        <div className="max-w-3xl text-xs leading-relaxed text-text-muted">{data.method}</div>
      </div>
    </div>
  )
}
