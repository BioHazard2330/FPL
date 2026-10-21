import { Link } from 'react-router-dom'
import type { MatchStory, StoryFinding, StorySideMetrics, StorySide, StorySub } from '@/lib/types'

type Names = { home: string; away: string }

const pct = (v: number) => `${Math.round(v * 100)}%`

/** THE DESERVED RESULT - the shots replayed. Every shot carries the chance it
 * was worth; treating them as independent, the probability that the same
 * chances end as a home win, a draw or an away win is exact (a Poisson-binomial
 * for each side, convolved). The notch marks what actually happened. */
export function DeservedResult({ story, names }: { story: MatchStory; names: Names }) {
  const d = story.deserved
  if (!d) return null
  const actual: 'home' | 'draw' | 'away' =
    story.match.home.score > story.match.away.score ? 'home' : story.match.home.score < story.match.away.score ? 'away' : 'draw'
  const gapHome = d.actual_home_points - d.home_points
  const lead = Math.abs(gapHome) >= Math.abs(d.actual_away_points - d.away_points) ? gapHome : -(d.actual_away_points - d.away_points)
  const segs = [
    { key: 'home' as const, p: d.home_win, cls: 'bg-pitch-green', label: `${names.home} win` },
    { key: 'draw' as const, p: d.draw, cls: 'bg-raised', label: 'Draw' },
    { key: 'away' as const, p: d.away_win, cls: 'bg-broadcast-blue', label: `${names.away} win` },
  ]
  let acc = 0
  const marks = segs.map((s) => {
    const mid = acc + s.p / 2
    acc += s.p
    return { ...s, mid }
  })
  const actualMid = marks.find((m) => m.key === actual)!.mid
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">
          Deserved result · {story.shots.length} shots replayed
        </div>
        <div className="tabular text-[13px] text-text-muted">
          expected points <span className="font-bold text-pitch-green">{d.home_points.toFixed(1)}</span> v{' '}
          <span className="font-bold text-broadcast-blue">{d.away_points.toFixed(1)}</span>
          <span className="text-text-faint"> · actual </span>
          <span className="font-bold text-text">{d.actual_home_points}</span> v <span className="font-bold text-text">{d.actual_away_points}</span>
        </div>
      </div>
      <div className="relative">
        <div className="flex h-9 w-full gap-px overflow-hidden">
          {segs.map((s) => (
            <div key={s.key} className={`${s.cls} bar-draw flex items-center justify-center`} style={{ width: `${Math.max(s.p * 100, 0.5)}%` }}>
              {s.p >= 0.08 && <span className={`tabular text-[13px] font-bold ${s.key === 'draw' ? 'text-text-muted' : 'text-void'}`}>{pct(s.p)}</span>}
            </div>
          ))}
        </div>
        <div className="pointer-events-none absolute -bottom-3 -translate-x-1/2" style={{ left: `${actualMid * 100}%` }} aria-hidden="true">
          <div className="mx-auto h-0 w-0 border-x-[5px] border-b-[7px] border-x-transparent border-b-text" />
        </div>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-text-faint">
        <span><span className="mr-1.5 inline-block size-2 bg-pitch-green align-middle" />{names.home} win {pct(d.home_win)}</span>
        <span><span className="mr-1.5 inline-block size-2 bg-raised align-middle" />draw {pct(d.draw)}</span>
        <span><span className="mr-1.5 inline-block size-2 bg-broadcast-blue align-middle" />{names.away} win {pct(d.away_win)}</span>
        <span className="text-text-muted">▲ what happened</span>
        {Math.abs(lead) >= 1 && (
          <span className={`font-bold ${lead > 0 ? 'text-broadcast-gold' : 'text-text-muted'}`}>
            {lead > 0 ? 'result ahead of the chances' : 'result behind the chances'} by {Math.abs(lead).toFixed(1)} pts
          </span>
        )}
      </div>
    </div>
  )
}

const STATE_INK = { leading: 'bg-pitch-green', level: 'bg-raised', trailing: 'bg-broadcast-gold' } as const
const STATE_LABEL = { leading: 'Leading', level: 'Level', trailing: 'Trailing' } as const

/** GAME STATE - how long each side spent ahead, level and behind, and what its
 * chances did in each. A side that scores early and then sits deep creates
 * little while ahead, and the side behind creates more: the same 90 minutes
 * read differently once the score is taken out of it. */
export function GameState({ story, names }: { story: MatchStory; names: Names }) {
  const prof = story.state_profile
  if (!prof) {
    return <p className="text-[13px] text-text-faint">The goal timeline does not add up to the final score, so game state was not computed.</p>
  }
  const rows: { side: StorySide; label: string; ink: string }[] = [
    { side: 'home', label: names.home, ink: 'text-pitch-green' },
    { side: 'away', label: names.away, ink: 'text-broadcast-blue' },
  ]
  return (
    <div className="space-y-5">
      {rows.map((r) => {
        const p = prof[r.side]
        const total = p.leading.minutes + p.level.minutes + p.trailing.minutes
        return (
          <div key={r.side}>
            <div className={`mb-1.5 text-[12px] font-bold uppercase tracking-[0.12em] ${r.ink}`}>{r.label}</div>
            <div className="flex h-3 w-full gap-px">
              {(['leading', 'level', 'trailing'] as const).map((k) => (
                p[k].minutes > 0 && <div key={k} className={`${STATE_INK[k]} bar-draw`} style={{ width: `${(p[k].minutes / total) * 100}%` }} />
              ))}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-3">
              {(['leading', 'level', 'trailing'] as const).map((k) => (
                <div key={k}>
                  <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">
                    <span className={`mr-1.5 inline-block size-2 align-middle ${STATE_INK[k]}`} />
                    {STATE_LABEL[k]} · {Math.round(p[k].minutes)}'
                  </div>
                  <div className="tabular text-sm text-text">
                    <span className="font-bold">{p[k].xg_for.toFixed(2)}</span> xG for
                  </div>
                  <div className="tabular text-sm text-text-muted">
                    <span className="font-bold">{p[k].xg_against.toFixed(2)}</span> against
                  </div>
                  <div className="tabular text-[12px] text-text-faint">
                    {p[k].per90_for !== null ? `${p[k].per90_for!.toFixed(1)} per 90 for` : 'under 5 minutes'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const GROUPS = [
  { key: 'open_play' as const, label: 'Open play', cls: 'bg-text-muted' },
  { key: 'fast_break' as const, label: 'Fast break', cls: 'bg-pitch-green' },
  { key: 'dead_ball' as const, label: 'Dead balls', cls: 'bg-broadcast-gold' },
  { key: 'penalty' as const, label: 'Penalty', cls: 'bg-alert-red' },
]

function Mix({ label, parts, total, ink, unit }: { label: string; parts: Record<'open_play' | 'fast_break' | 'dead_ball' | 'penalty', number>; total: number; ink?: string; unit?: string }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr_3.2rem] items-center gap-3 py-1">
      <div className={`truncate text-[12px] font-bold uppercase tracking-[0.1em] ${ink ?? 'text-text-faint'}`}>{label}</div>
      <div className="flex h-3 w-full gap-px bg-raised/40">
        {total > 0 &&
          GROUPS.map((g) => parts[g.key] > 0 && <div key={g.key} className={`${g.cls} bar-draw`} style={{ width: `${(parts[g.key] / total) * 100}%` }} title={`${g.label} ${(parts[g.key]).toFixed(2)} xG`} />)}
      </div>
      <div className="tabular text-right text-[13px] font-bold text-text">{unit === 'share' ? '100%' : total.toFixed(2)}</div>
    </div>
  )
}

/** WHERE THE CHANCES CAME FROM - each side's xG split by how the shot arose, for
 * and against, with the league's own mix as the yardstick. */
export function SituationMix({ story, names }: { story: MatchStory; names: Names }) {
  const h: StorySideMetrics = story.metrics.home
  const a: StorySideMetrics = story.metrics.away
  const league = story.league?.group_share
  const leagueParts = league
    ? { open_play: league.open_play ?? 0, fast_break: league.fast_break ?? 0, dead_ball: league.dead_ball ?? 0, penalty: league.penalty ?? 0 }
    : null
  return (
    <div>
      <Mix label={`${names.home} created`} parts={h.xg_by_situation} total={h.xg} ink="text-pitch-green" />
      <Mix label={`${names.home} allowed`} parts={h.xga_by_situation} total={h.xg_against} />
      <Mix label={`${names.away} created`} parts={a.xg_by_situation} total={a.xg} ink="text-broadcast-blue" />
      <Mix label={`${names.away} allowed`} parts={a.xga_by_situation} total={a.xg_against} />
      {leagueParts && (
        <div className="mt-2 border-t border-divider pt-2">
          <Mix label="League mix" parts={leagueParts} total={1} unit="share" />
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-text-faint">
        {GROUPS.map((g) => (
          <span key={g.key}><span className={`mr-1.5 inline-block size-2 align-middle ${g.cls}`} />{g.label}</span>
        ))}
        <span>Each bar is that side's xG split by share; the figure is its total. The league row is the share across {story.league?.team_matches ?? 0} team-matches.</span>
      </div>
    </div>
  )
}

const KIND_STYLE: Record<string, string> = {
  INJURY_LINKED: 'bg-alert-red/15 text-alert-red',
  EARLY_UNEXPLAINED: 'bg-alert-red/15 text-alert-red',
  CHASING: 'bg-broadcast-gold/15 text-broadcast-gold',
  TACTICAL: 'bg-broadcast-gold/15 text-broadcast-gold',
  PROTECTING_LEAD: 'bg-broadcast-blue/15 text-broadcast-blue',
  MANAGED_MINUTES: 'bg-raised text-text-muted',
  HALF_TIME: 'bg-raised text-text-faint',
  LIKE_FOR_LIKE: 'bg-raised text-text-faint',
}

function kindLabel(kind: string): string {
  return kind.replace(/_/g, ' ').toLowerCase()
}

/** SUBSTITUTIONS - each change read against the score and the player coming off.
 * "Injury linked" needs an FPL status change after the match, never timing alone. */
export function Substitutions({ subs, names }: { subs: StorySub[]; names: Names }) {
  if (subs.length === 0) return null
  return (
    <div>
      {subs.map((s, i) => (
        <div key={i} className="grid grid-cols-[2.6rem_1fr_auto] items-baseline gap-3 border-b border-divider py-2 last:border-b-0">
          <span className="tabular text-right text-[13px] font-bold text-text-muted">{s.minute}'</span>
          <div className="min-w-0">
            <div className="truncate text-sm text-text">
              <span className={`mr-2 inline-block size-1.5 align-middle ${s.side === 'home' ? 'bg-pitch-green' : 'bg-broadcast-blue'}`} title={s.side === 'home' ? names.home : names.away} />
              {s.on_id !== null ? <Link to={`/player/${s.on_id}`} className="font-bold hover:text-pitch-green">{s.on}</Link> : <span className="font-bold">{s.on}</span>}
              <span className="text-text-faint"> on for </span>
              {s.off_id !== null ? <Link to={`/player/${s.off_id}`} className="hover:text-pitch-green">{s.off}</Link> : s.off}
            </div>
            <div className="truncate text-[12px] text-text-faint">{s.note}</div>
          </div>
          <span className={`px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] ${KIND_STYLE[s.kind] ?? 'bg-raised text-text-muted'}`}>{kindLabel(s.kind)}</span>
        </div>
      ))}
    </div>
  )
}

const DIRECTION_RULE: Record<string, string> = {
  POSITIVE: 'border-pitch-green',
  NEGATIVE: 'border-alert-red',
  WATCH: 'border-broadcast-gold',
  NEUTRAL: 'border-divider',
}
const VERDICT_STYLE: Record<string, string> = {
  persistent: 'bg-pitch-green/15 text-pitch-green',
  unclear: 'bg-broadcast-gold/15 text-broadcast-gold',
  none: 'bg-alert-red/15 text-alert-red',
  'too few': 'bg-raised text-text-faint',
}
const VERDICT_WORD: Record<string, string> = {
  persistent: 'carries to the next match',
  unclear: 'may carry a little',
  none: 'does not carry',
  'too few': 'too few matches to say',
}

export function Findings({ findings, limit = 10 }: { findings: StoryFinding[]; limit?: number }) {
  const shown = findings.slice(0, limit)
  if (shown.length === 0) {
    return <p className="text-[13px] text-text-faint">No finding cleared the analyst's thresholds for this match.</p>
  }
  return (
    <div className="space-y-px bg-divider">
      {shown.map((f, i) => {
        const subject =
          f.subject_type === 'player' ? (
            <Link to={`/player/${f.subject_id}`} className="font-bold text-text hover:text-pitch-green">{f.name ?? 'Player'}</Link>
          ) : (
            <Link to={`/club/${f.subject_id}`} className="font-bold text-text hover:text-pitch-green">{f.name ?? 'Club'}</Link>
          )
        return (
          <div key={i} className={`border-l-4 bg-panel px-4 py-3 ${DIRECTION_RULE[f.fpl_direction ?? 'NEUTRAL']}`}>
            <div className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">
              <span className="text-[13px] normal-case tracking-normal">{subject}</span>
              <span>{f.observation_type.replace(/_/g, ' ').toLowerCase()}</span>
              {f.fpl_direction && <span className={f.fpl_direction === 'POSITIVE' ? 'text-pitch-green' : f.fpl_direction === 'NEGATIVE' ? 'text-alert-red' : f.fpl_direction === 'WATCH' ? 'text-broadcast-gold' : ''}>{f.fpl_direction.toLowerCase()}{f.fpl_signal ? ` · ${f.fpl_signal.replace(/_/g, ' ').toLowerCase()}` : ''}</span>}
              <span>{f.confidence} confidence</span>
            </div>
            <p className="text-sm leading-snug text-text">{f.observed}</p>
            {f.inferred && <p className="mt-1 text-[13px] leading-snug text-text-muted">{f.inferred}</p>}
            {f.reliability && (
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[12px] text-text-faint">
                <span className={`px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] ${VERDICT_STYLE[f.reliability.verdict]}`}>{f.reliability.verdict}</span>
                <span>
                  {f.reliability.label} {VERDICT_WORD[f.reliability.verdict]}
                  {f.reliability.r !== null ? ` (r ${f.reliability.r >= 0 ? '+' : ''}${f.reliability.r.toFixed(2)}, n ${f.reliability.n.toLocaleString()})` : ''}
                </span>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
