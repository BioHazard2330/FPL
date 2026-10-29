import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { fetchPricesPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { PriceRow } from '@/lib/types'

/** TONIGHT'S PRICES: the fitted chance each player rises at the next overnight update, for the squad (team value), the
 * players the plan has lined up (a rise before you buy costs £0.1m) and the league's likeliest risers. Falls are not shown:
 * the fall model has not beaten the base rate on held-out nights. */
function Row({ r, likely, note }: { r: PriceRow; likely: number; note?: string }) {
  const p = r.p_rise ?? 0
  const hot = p >= likely
  return (
    <Link to={`/player/${r.player_id}`} className="grid grid-cols-[2rem_minmax(0,1fr)_7rem_3.5rem] items-center gap-3 py-1.5 hover:bg-raised/50">
      <PlayerPhoto code={r.photo_code} teamCode={r.team_code} isGkp={r.position === 'GKP'} className="h-9 w-7" />
      <span className="min-w-0 truncate text-[14px]">
        <span className="font-semibold text-text">{r.name}</span>
        <span className="ml-1.5 text-[12px] text-text-faint">{r.team_short} · £{r.price?.toFixed(1)}m{note ? ` · ${note}` : ''}</span>
      </span>
      <span className="h-3 border-2 border-ink bg-paper">
        <span className={`block h-full ${hot ? 'bg-pitch-green' : 'bg-text-faint/50'}`} style={{ width: `${Math.max(2, Math.min(p, 1) * 100)}%` }} />
      </span>
      <span className={`tabular text-right font-display text-lg font-black ${hot ? 'text-pitch-green' : 'text-text-faint'}`}>{Math.round(p * 100)}%</span>
    </Link>
  )
}

export function TonightPrices() {
  const state = useFetch(fetchPricesPayload, [])
  if (state.status !== 'ready' || state.data.status !== 'ok') return null
  const d = state.data
  const likely = d.likely ?? 0.25
  const squadHot = (d.squad ?? []).filter((r) => (r.p_rise ?? 0) >= 0.05)
  const targets = (d.targets ?? []).slice(0, 6)
  const risers = (d.risers ?? []).slice(0, 6)
  const head = 'mb-1 mt-4 font-display text-[13px] font-black uppercase tracking-[0.08em] text-text'
  return (
    <section className="slab px-6 pb-6 pt-5">
      <h2 className="font-display text-text">Tonight's prices</h2>
      <p className="mt-1 text-[13px] text-text-muted">
        Chance of a rise at the next overnight update. A target that rises before you buy costs £0.1m; a squad player who rises
        is team value. {d.model && <>Fitted on the stored transfer history (held-out AUC {d.model.auc}, {d.model.holdout_rises} rises).</>}
      </p>
      {squadHot.length > 0 && (<><div className={head}>Your squad</div><div className="divide-y divide-divider">{squadHot.map((r) => <Row key={r.player_id} r={r} likely={likely} />)}</div></>)}
      {targets.length > 0 && (<><div className={head}>Players the plan has lined up</div><div className="divide-y divide-divider">{targets.map((r) => <Row key={r.player_id} r={r} likely={likely} note={r.when ?? undefined} />)}</div></>)}
      {risers.length > 0 && (<><div className={head}>Likeliest risers in the game</div><div className="divide-y divide-divider">{risers.map((r) => <Row key={r.player_id} r={r} likely={likely} />)}</div></>)}
      <p className="mt-3 text-[11.5px] text-text-faint">Falls are not shown: the fall model has not beaten the base rate on held-out nights.</p>
    </section>
  )
}
