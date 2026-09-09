import type { BonusDefconRow } from '@/lib/types'

/** Real live bonus + defensive-contribution rail. Both are genuine
 * in-match FPL point sources that resolve AFTER the whistle, so this is
 * the one place on the screen where "provisional" has to be labelled as
 * such - a provisional BPS bonus can still evaporate, and the screen must
 * never imply it has been banked. `defcon_threshold`/`defcon_reached` are
 * legitimately null for players the DefCon rule doesn't apply to; those
 * rows show minutes and bonus only rather than an invented 0/0 bar. */
export function BonusDefconRail({ rows }: { rows: BonusDefconRow[] }) {
  const playing = rows.filter((r) => (r.minutes ?? 0) > 0)
  if (playing.length === 0) return null

  return (
    <div className="divide-y divide-divider">
      {playing
        .slice()
        .sort((a, b) => (b.provisional_bonus ?? 0) - (a.provisional_bonus ?? 0) || (b.minutes ?? 0) - (a.minutes ?? 0))
        .map((r) => {
          const bonus = r.confirmed_bonus ?? r.provisional_bonus
          const confirmed = r.confirmed_bonus !== null
          const hasDefcon = r.defcon_threshold !== null && r.defensive_contribution !== null
          const pct = hasDefcon
            ? Math.min(100, ((r.defensive_contribution as number) / (r.defcon_threshold as number)) * 100)
            : 0
          return (
            <div key={r.player_id} className="flex items-center gap-4 py-2.5">
              <span className="w-32 shrink-0 truncate text-sm font-bold text-text">{r.web_name}</span>
              <span className="tabular w-10 shrink-0 text-xs text-text-faint">{r.minutes ?? 0}&prime;</span>

              {bonus ? (
                <span
                  className={`shrink-0 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                    confirmed ? 'bg-broadcast-gold text-broadcast-gold-ink' : 'border border-broadcast-gold text-broadcast-gold'
                  }`}
                >
                  +{bonus} {confirmed ? 'bonus' : 'prov.'}
                </span>
              ) : (
                <span className="shrink-0 text-[10px] uppercase tracking-wide text-text-faint">no bonus</span>
              )}

              {hasDefcon ? (
                <span className="ml-auto flex min-w-0 flex-1 items-center gap-2">
                  <span className="relative h-2 min-w-16 flex-1 bg-void">
                    <span
                      className={`bar-draw absolute inset-y-0 left-0 ${r.defcon_reached ? 'bg-pitch-green' : 'bg-broadcast-blue'}`}
                      style={{ width: `${pct}%` }}
                    />
                    <span className="absolute inset-y-0 right-0 w-px bg-text-faint" />
                  </span>
                  <span
                    className={`tabular w-16 shrink-0 text-right text-xs font-bold ${
                      r.defcon_reached ? 'text-pitch-green' : 'text-text-muted'
                    }`}
                  >
                    {r.defensive_contribution}/{r.defcon_threshold}
                  </span>
                </span>
              ) : (
                <span className="ml-auto shrink-0 text-[10px] uppercase tracking-wide text-text-faint">no defcon rule</span>
              )}
            </div>
          )
        })}
    </div>
  )
}
