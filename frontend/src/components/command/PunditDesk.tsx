import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { Info } from '@/components/ui/Info'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fdrFill } from '@/lib/fdr'
import type { PunditBrief, PunditLens, PunditMove, WeekPlanPayload } from '@/lib/types'

/** THE PUNDIT'S DESK: each of the plan's moves judged across every lens the app measures (`models/pundit.py`), shown as
 * chips - green for the move, red against, grey context - with the sentence behind each on hover; and the armband and
 * the options judged by the chance of a top-10k finish (`optimization/rank_review.py`). It argues the plan's own moves. */

const GRADE: Record<PunditMove['grade'], { label: string; tone: string }> = {
  strong: { label: 'Strong', tone: 'bg-pitch-green text-paper' },
  sound: { label: 'Sound', tone: 'bg-broadcast-blue text-paper' },
  marginal: { label: 'Marginal', tone: 'bg-broadcast-gold text-ink' },
  doubtful: { label: 'Doubtful', tone: 'bg-alert-red text-paper' },
}
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`)

function Chip({ lz }: { lz: PunditLens }) {
  const tone = lz.lean > 0 ? 'border-pitch-green bg-pitch-green/10' : lz.lean < 0 ? 'border-alert-red bg-alert-red/10' : 'border-ink/25 bg-paper'
  const mark = lz.lean > 0 ? '✓' : lz.lean < 0 ? '✗' : ''
  return (
    <HoverCard>
      <HoverCardTrigger
        render={
          <button type="button" className={`relative flex min-w-[6.2rem] flex-col items-start border-2 px-2.5 py-1.5 text-left transition-transform hover:-translate-y-0.5 ${tone}`}>
            <span className="max-w-[8rem] truncate text-[10px] font-bold uppercase tracking-[0.1em] text-text-faint">{lz.label}</span>
            <span className={`tabular font-display text-[1.25rem] font-black leading-tight ${lz.lean > 0 ? 'text-pitch-green' : lz.lean < 0 ? 'text-alert-red' : 'text-text'}`}>
              {lz.value}
            </span>
            {mark && <span className={`absolute right-1.5 top-1 text-[12px] font-black ${lz.lean > 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{mark}</span>}
            {!lz.counted && lz.lean !== 0 && <span className="absolute bottom-1 right-1.5 text-[9px] font-bold uppercase text-text-faint">note</span>}
          </button>
        }
      />
      <HoverCardContent className="w-72 rounded-none border-2 border-ink bg-paper p-3 text-[12.5px] leading-snug text-text shadow-[4px_4px_0_var(--ink)] ring-0">
        {lz.detail}
      </HoverCardContent>
    </HoverCard>
  )
}

function FixtureRow({ team, run }: { team: string | null; run: { opponent_short: string; is_home: boolean; difficulty: number }[] }) {
  if (!run.length) return null
  return (
    <div className="flex items-center gap-1">
      <span className="w-9 text-[11px] font-black text-text-muted">{team}</span>
      {run.map((f, i) => (
        <span key={i} className={`flex h-7 w-11 flex-col items-center justify-center text-[10.5px] font-black leading-none ${fdrFill(f.difficulty)}`}>
          {f.opponent_short}
          <span className="text-[8.5px] font-bold opacity-75">{f.is_home ? 'H' : 'A'}</span>
        </span>
      ))}
    </div>
  )
}

function MoveBrief({ m, i, photos }: { m: PunditMove; i: number; photos: Record<number, { code: number | null; team: number | null }> }) {
  const g = GRADE[m.grade]
  const same = m.into_team_code === m.out_team_code
  return (
    <div className="pundit-card border-2 border-ink bg-paper shadow-[5px_5px_0_var(--ink)]" style={{ animationDelay: `${i * 90}ms` }}>
      <div className="flex items-center gap-4 border-b-2 border-ink px-5 py-3">
        <PlayerPhoto code={photos[m.out_id]?.code ?? null} teamCode={photos[m.out_id]?.team ?? null} className="h-14 w-11" muted />
        <span className="font-display text-2xl font-black text-text-faint">→</span>
        <PlayerPhoto code={photos[m.into_id]?.code ?? null} teamCode={photos[m.into_id]?.team ?? null} className="h-14 w-11" />
        <div className="min-w-0 flex-1">
          <div className="truncate font-display text-[1.6rem] font-black uppercase leading-none text-text">{m.into}</div>
          <div className="truncate text-[12px] text-text-faint line-through decoration-alert-red/60">{m.out}</div>
        </div>
        <div className="text-right">
          <div className="tabular font-display text-[2rem] font-black leading-none text-pitch-green">{(m.gain ?? 0) >= 0 ? '+' : ''}{(m.gain ?? 0).toFixed(1)}</div>
          <div className="text-[10px] font-bold uppercase tracking-[0.1em] text-text-faint">pts / 5 GW</div>
        </div>
        <div className={`pundit-stamp shrink-0 -rotate-3 border-2 border-ink px-3 py-1 font-display text-[1.2rem] font-black uppercase ${g.tone}`}>{g.label}</div>
      </div>
      <div className="space-y-1 px-5 pt-3">
        <FixtureRow team={m.into_team} run={m.runs?.into ?? []} />
        {!same && <FixtureRow team={m.out_team} run={m.runs?.out ?? []} />}
      </div>
      <div className="flex flex-wrap gap-2 px-5 py-4">
        {(m.lenses ?? []).map((lz) => <Chip key={lz.key} lz={lz} />)}
      </div>
    </div>
  )
}

function Armband({ brief }: { brief: PunditBrief }) {
  const c = brief.captain
  if (!c) return null
  const chosen = c.options.find((o) => o.chosen)
  const fav = [...c.options].sort((a, b) => (b.field_captain_share ?? 0) - (a.field_captain_share ?? 0))[0]
  const differential = chosen && fav && fav.player_id !== chosen.player_id && (fav.field_captain_share ?? 0) >= 0.3
  const top = Math.max(...c.options.map((o) => o.xp))
  return (
    <div className="pundit-card border-2 border-ink bg-paper shadow-[5px_5px_0_var(--ink)]">
      <div className="flex items-center justify-between border-b-2 border-ink px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="font-display text-[1.6rem] font-black uppercase leading-none text-text">The armband</span>
          <Info label="The armband, argued">{c.lines.map((l, i) => <p key={i}>{l}</p>)}</Info>
        </div>
        {differential && (
          <span className="bg-spot px-2 py-0.5 font-display text-[13px] font-black uppercase text-ink">
            differential · {Math.round((fav.field_captain_share ?? 0) * 100)}% of the top 10k on {fav.name}
          </span>
        )}
      </div>
      <div className="space-y-2 px-5 py-4">
        {c.options.map((o) => (
          <div key={o.player_id} className="grid grid-cols-[8rem_4.5rem_minmax(0,1fr)_4rem_4.5rem] items-center gap-3">
            <span className={`truncate text-[14px] ${o.chosen ? 'font-black text-text' : 'text-text-muted'}`}>{o.chosen ? '© ' : ''}{o.name}</span>
            <span className={`px-1 text-center text-[11px] font-black ${fdrFill(o.difficulty)}`}>{o.fixture ?? '—'}</span>
            <div className="relative h-4 bg-ink/10">
              <div className={`pundit-bar absolute inset-y-0 left-0 ${o.chosen ? 'bg-spot' : 'bg-ink/35'}`} style={{ width: `${(o.xp / top) * 100}%` }} />
            </div>
            <span className="tabular text-right font-display text-lg font-black text-text">{o.xp.toFixed(1)}</span>
            <span className="tabular text-right text-[12px] text-text-muted" title="top-10k managers captaining him">{o.field_captain_share === null ? '—' : `${Math.round(o.field_captain_share * 100)}% C`}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function PunditDesk({ plan }: { plan: WeekPlanPayload }) {
  const brief = plan.pundit
  if (!brief || (!brief.moves.length && !brief.captain && !brief.rank)) return null
  const rank = brief.rank
  const opts = rank?.options ?? []
  const planOpt = opts.find((o) => o.key === 'plan')
  const roll = opts.find((o) => o.key === 'roll')
  const photos: Record<number, { code: number | null; team: number | null }> = {}
  for (const m of plan.moves ?? []) {
    photos[m.out.player_id] = { code: m.out.photo_code ?? null, team: m.out.team_code ?? null }
    photos[m.into.player_id] = { code: m.into.photo_code ?? null, team: m.into.team_code ?? null }
  }
  return (
    <section className="bare">
      <div className="relative overflow-hidden border-[3px] border-ink bg-ink px-8 py-6 text-paper shadow-[8px_8px_0_var(--spot)]">
        <div className="pointer-events-none absolute -right-10 -top-16 h-56 w-56 rounded-full bg-spot/20 blur-3xl" />
        <div className="relative flex flex-wrap items-end gap-x-12 gap-y-4">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-paper/55">
              the pundit&apos;s desk · chance of top 10k
              {rank && (
                <Info label="How the chance is worked out" className="text-paper">
                  <p>This gameweek simulated against the top-10k field ({rank.field.sample_size} sampled managers, GW{rank.field.sample_event} picks aged to now).</p>
                  <p>Later horizon weeks at each option's projected gain; the rest of the season at your measured pace ({rank.pace.mean >= 0 ? '+' : ''}{rank.pace.mean.toFixed(1)} a week, sd {rank.pace.sd.toFixed(1)}, {rank.pace.weeks} weeks).</p>
                  {brief.overview.map((l, i) => <p key={i}>{l}</p>)}
                </Info>
              )}
            </div>
            <div className="tabular font-display text-[4.2rem] font-black leading-none text-spot">{pct(planOpt?.chance)}</div>
            <div className="text-[13px] text-paper/70">with the plan · {pct(roll?.chance)} rolling</div>
          </div>
          {rank && (
            <div className="flex gap-6">
              {[
                { v: `${rank.gap}`, l: 'points behind' },
                { v: (rank.gap / Math.max(rank.weeks_left, 1)).toFixed(1), l: 'needed a week' },
                { v: `${rank.pace.mean >= 0 ? '+' : ''}${rank.pace.mean.toFixed(1)}`, l: 'your pace a week' },
                { v: `${rank.weeks_left}`, l: 'weeks left' },
              ].map((t) => (
                <div key={t.l}>
                  <div className="tabular font-display text-[2.2rem] font-black leading-none text-paper">{t.v}</div>
                  <div className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-paper/50">{t.l}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="mt-6 grid grid-cols-1 gap-6 2xl:grid-cols-2">
        {brief.moves.map((m, i) => <MoveBrief key={m.into_id} m={m} i={i} photos={photos} />)}
        <Armband brief={brief} />
      </div>
    </section>
  )
}
