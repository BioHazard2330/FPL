import { Link } from 'react-router-dom'
import { crestUrl } from '@/lib/api'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { FixtureRun } from '@/components/football/FixtureRun'
import { money } from '@/components/ui/kit'
import type { FixtureContext, WeekPlanMove, WeekPlanPlayer } from '@/lib/types'
import { plain } from '@/lib/text'

type Note = { tone: 'red' | 'gold' | 'green' | 'plain'; text: string }

/** The few things worth knowing about one side of a transfer, each as a plain sentence with its number. Order is by how much
 * it should change the decision: availability first, then price, then what the recent matches say. */
function notes(p: WeekPlanPlayer, side: 'out' | 'into'): Note[] {
  const out: Note[] = []
  if (p.start_percent !== null && p.start_percent < 70) {
    out.push({ tone: p.start_percent < 40 ? 'red' : 'gold', text: `${p.start_percent}% to start, per the team-news feed` })
  }
  if (side === 'out' && p.price_trend === 'FALL_LIKELY') {
    out.push({ tone: 'red', text: `Price likely to fall tonight${p.price_p_fall != null ? ` (${Math.round(p.price_p_fall * 100)}%)` : ''}` })
  }
  if (side === 'into' && p.price_trend === 'RISE_LIKELY') {
    out.push({ tone: 'gold', text: `Price likely to rise tonight${p.price_p_rise != null ? ` (${Math.round(p.price_p_rise * 100)}%)` : ''}` })
  }
  if ((p.duties ?? []).length > 0) {
    out.push({ tone: side === 'out' ? 'gold' : 'green', text: `First choice on ${p.duties!.join(', ')}` })
  }
  if (p.form && p.form.label !== 'STEADY') {
    out.push({
      tone: p.form.label === 'HOT' ? 'green' : 'gold',
      text: `Last 3 matches ${p.form.recent_xgi90.toFixed(2)} xG+xA per 90, against ${p.form.before_xgi90.toFixed(2)} before`,
    })
  }
  if (p.luck && Math.abs(p.luck.z) >= 1.5) {
    out.push({
      tone: p.luck.z > 0 ? 'gold' : 'plain',
      text: p.luck.z > 0 ? `${p.luck.luck.toFixed(0)} points above what his chances were worth` : `${Math.abs(p.luck.luck).toFixed(0)} points below what his chances were worth`,
    })
  }
  if (side === 'into' && p.solio_next !== null && Math.abs(p.xp_next - p.solio_next) >= 1) {
    out.push({ tone: 'plain', text: `Solio projects ${p.solio_next.toFixed(1)} against our ${p.xp_next.toFixed(1)}` })
  }
  if (p.analyst && p.analyst.direction !== 'NEUTRAL') out.push({ tone: p.analyst.direction === 'NEGATIVE' ? 'red' : p.analyst.direction === 'POSITIVE' ? 'green' : 'plain', text: `${p.analyst.match}: ${plain(p.analyst.observed)}` })
  return out.slice(0, 4)
}

const INK = { red: 'text-alert-red', gold: 'text-broadcast-gold', green: 'text-pitch-green', plain: 'text-text-muted' }

function Side({ p, side, fixtures }: { p: WeekPlanPlayer; side: 'out' | 'into'; fixtures?: FixtureContext }) {
  const crest = crestUrl(p.team_code)
  const run = p.team_code !== null ? fixtures?.[String(p.team_code)] : undefined
  const ns = notes(p, side)
  return (
    <div className="min-w-0">
      <div className="mb-2 text-[13px] font-medium text-text-faint">{side === 'out' ? 'Sell' : 'Buy'}</div>
      <div className="flex items-center gap-3">
        <div className="relative shrink-0">
          <PlayerPhoto code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} className="h-14 w-11" muted={side === 'out'} />
          {crest && <img src={crest} alt="" className="absolute -bottom-1 -right-1 size-5 rounded-full bg-panel ring-2 ring-panel" />}
        </div>
        <div className="min-w-0">
          <Link to={`/player/${p.player_id}`} className={`block truncate font-display text-xl font-semibold leading-tight hover:text-pitch-green ${side === 'into' ? 'text-text' : 'text-text-muted'}`}>
            {p.name}
          </Link>
          <div className="tabular text-[13px] text-text-faint">
            {p.team_short} &middot; {p.position} &middot; {money(p.price_tenths)}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="tabular text-[13px] text-text-faint">
          <span className={`font-display text-2xl font-semibold leading-none ${side === 'into' ? 'text-pitch-green' : 'text-text-muted'}`}>{p.xp_next.toFixed(1)}</span> xP next GW
          <span className="text-text-faint"> &middot; {p.xp_horizon.toFixed(1)} over 5</span>
        </div>
        <FixtureRun fixtures={run} max={4} showEvent className="shrink-0 [&>span]:rounded-sm" />
      </div>
      {ns.length > 0 && (
        <ul className="mt-3 space-y-1.5 text-[13px] leading-snug">
          {ns.map((n) => (
            <li key={n.text} className={`border-l-2 pl-2.5 ${n.tone === 'red' ? 'border-alert-red' : n.tone === 'gold' ? 'border-broadcast-gold' : n.tone === 'green' ? 'border-pitch-green' : 'border-divider'} ${INK[n.tone]}`}>
              <span className="line-clamp-2" title={n.text}>{n.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function MoveCard({ m, horizon, fixtures }: { m: WeekPlanMove; horizon: number; fixtures?: FixtureContext }) {
  return (
    <div className="rounded-lg border border-divider bg-void/40 p-5">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Side p={m.out} side="out" fixtures={fixtures} />
        <Side p={m.into} side="into" fixtures={fixtures} />
      </div>
      <div className="mt-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-t border-divider pt-3 text-[13px] text-text-muted">
        <div className="min-w-0">
          {(m.alternatives ?? []).length > 0 ? (
            <>
              <span className="text-text-faint">If not {m.into.name}: </span>
              {m.alternatives!.map((a, i) => (
                <span key={a.into.player_id} className="tabular">
                  {i > 0 && ', '}
                  <span className="font-semibold text-text">{a.into.name}</span> ({money(a.into.price_tenths)}) <span className="text-pitch-green">+{a.gain.toFixed(1)}</span>
                </span>
              ))}
              <span className="text-text-faint"> over {horizon} GW</span>
            </>
          ) : (
            m.timing_note && <span>{m.timing_note}</span>
          )}
        </div>
        <Link to={`/compare?a=${m.out.player_id}&b=${m.into.player_id}`} className="shrink-0 font-medium text-text-faint hover:text-text">
          Compare them &rarr;
        </Link>
      </div>
      {m.timing && m.timing !== 'any' && m.timing_note && (m.alternatives ?? []).length > 0 && <p className="mt-2 text-[13px] text-broadcast-gold">{m.timing_note}</p>}
    </div>
  )
}
