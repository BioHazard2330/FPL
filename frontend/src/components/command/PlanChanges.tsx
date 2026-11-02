import { relativeTime } from '@/lib/time'
import type { PlanChangeSide, PlanChanges as Changes } from '@/lib/types'

/** SINCE THE LAST PLAN: what the rebuild changed and the evidence that moved it - each dropped or added move with both
 * players' projections over the horizon before and after, any news logged for them since, results in, and whether the
 * model itself was revised. A standing call is kept unless a replacement beats it by the bar. */
function Delta({ p }: { p: PlanChangeSide }) {
  const d = p.xp_before !== null && p.xp_after !== null ? p.xp_after - p.xp_before : null
  return (
    <span className="whitespace-nowrap">
      <span className="font-semibold text-text">{p.name}</span>{' '}
      {d !== null && Math.abs(d) >= 0.05 ? (
        <span className={`tabular font-display font-black ${d > 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
          {p.xp_before!.toFixed(1)}→{p.xp_after!.toFixed(1)}
        </span>
      ) : p.xp_after !== null ? <span className="tabular text-text-faint">{p.xp_after.toFixed(1)}</span> : null}
    </span>
  )
}

export function PlanChanges({ changes }: { changes: Changes | null | undefined; horizon?: number }) {
  if (!changes) return null
  const moved = changes.dropped.length + changes.added.length > 0 || changes.captain
  const why = [
    changes.model_changed ? 'the model was revised' : null,
    changes.matches_finished ? `${changes.matches_finished} result${changes.matches_finished === 1 ? '' : 's'} came in` : null,
  ].filter(Boolean)
  return (
    <div className="border-2 border-ink bg-paper px-5 py-3.5 shadow-[4px_4px_0_var(--ink)]">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="font-display text-[13px] font-black uppercase tracking-[0.1em] text-text">
          Since the last plan <span className="text-text-faint">· {relativeTime(changes.since)}</span>
        </div>
        <div className="text-[12px] text-text-muted">
          {why.length ? `${why.join(' and ')}. ` : ''}
          {changes.kept > 0 && `${changes.kept} move${changes.kept === 1 ? '' : 's'} held${changes.standing_bonus ? `: a replacement must beat a standing call by ${(changes.standing_bonus * 2).toFixed(1)}` : ''}.`}
        </div>
      </div>
      {!moved && <div className="mt-1 font-display text-[15px] font-black uppercase text-pitch-green">unchanged</div>}
      <div className="mt-2 space-y-1.5 text-[13px] text-text-muted">
        {changes.dropped.map((m) => (
          <div key={`d${m.out.player_id}-${m.into.player_id}`}>
            <span className="mr-2 bg-alert-red px-1.5 font-display text-[11px] font-black uppercase text-alert-red-ink">dropped</span>
            <Delta p={m.out} /> → <Delta p={m.into} />
            {[...m.out.news, ...m.into.news].slice(0, 2).map((n) => <div key={n} className="ml-16 text-[12px] text-text-faint">{n}</div>)}
          </div>
        ))}
        {changes.added.map((m) => (
          <div key={`a${m.out.player_id}-${m.into.player_id}`}>
            <span className="mr-2 bg-pitch-green px-1.5 font-display text-[11px] font-black uppercase text-paper">added</span>
            <Delta p={m.out} /> → <Delta p={m.into} />
            {[...m.out.news, ...m.into.news].slice(0, 2).map((n) => <div key={n} className="ml-16 text-[12px] text-text-faint">{n}</div>)}
          </div>
        ))}
        {changes.captain && (
          <div>
            <span className="mr-2 bg-broadcast-gold px-1.5 font-display text-[11px] font-black uppercase text-ink">armband</span>
            {changes.captain.from} → <span className="font-semibold text-text">{changes.captain.to}</span>
          </div>
        )}
      </div>
    </div>
  )
}
