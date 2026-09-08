import { crestUrl, shirtUrl } from '@/lib/api'
import type { ActionSquadBlock, ActionSquadPlayer } from '@/lib/types'

type Tier = 'captain' | 'featured' | 'normal' | 'bench'

/** Real size hierarchy, not a uniform row - the captain reads as the
 * headline player of the gallery, the rest scale down by real projected
 * median. Flat crest ring, no drop-shadow glow (DESIGN.md's own "no
 * shadow" rule - the previous version cast a colored/black shadow under
 * every shirt). */
function GalleryTile({ p, captainId, viceId, tier = 'normal' }: {
  p: ActionSquadPlayer
  captainId: number | null
  viceId: number | null
  tier?: Tier
}) {
  const pxSize = tier === 'captain' ? 220 : tier === 'featured' ? 110 : tier === 'bench' ? 66 : 110
  const shirt = shirtUrl(p.team_code, p.position === 'GKP', pxSize)
  const crest = crestUrl(p.team_code)
  const sizeClass =
    tier === 'captain' ? 'h-28 w-28' : tier === 'featured' ? 'h-[4.5rem] w-[4.5rem]' : tier === 'bench' ? 'h-10 w-10' : 'h-14 w-14'
  const nameClass = tier === 'captain' ? 'font-display text-lg font-bold' : tier === 'featured' ? 'text-sm font-bold' : 'text-xs font-bold'
  const medianClass = tier === 'captain' ? 'text-2xl' : tier === 'featured' ? 'text-base' : 'text-sm'
  return (
    <div className={`relative flex flex-col items-center text-center ${tier === 'captain' ? 'w-32' : tier === 'featured' ? 'w-24' : tier === 'bench' ? 'w-16' : 'w-20'}`}>
      {p.player_id === captainId && (
        <span className="absolute right-1 top-0 flex h-5 w-5 items-center justify-center bg-broadcast-gold text-xs font-bold text-broadcast-gold-ink">C</span>
      )}
      {p.player_id === viceId && (
        <span className="absolute right-1 top-0 flex h-4 w-4 items-center justify-center bg-raised text-[10px] font-bold text-text">V</span>
      )}
      <div className={`relative ${sizeClass}`}>
        {shirt ? <img src={shirt} alt="" className={`${sizeClass} object-contain`} /> : <div className={`${sizeClass} bg-raised`} />}
        {crest && <img src={crest} alt="" className="absolute -bottom-0.5 -right-0.5 h-4 w-4 rounded-full bg-void ring-2 ring-void" />}
      </div>
      <div className={`mt-1.5 w-full truncate text-text ${nameClass}`}>{p.name}</div>
      <div className={`tabular font-bold text-pitch-green ${medianClass}`}>{p.median.toFixed(1)}</div>
    </div>
  )
}

/** THE ACTION SQUAD as an editorial player gallery, not 11 identical
 * dashboard tiles - captain visually dominant, the next three featured,
 * the rest recede, bench recedes further still. Sits on its own flat
 * panel field (colour-block separation from the hero above/horizon
 * below, no rule needed). */
export function PlayerGallery({ block }: { block: ActionSquadBlock }) {
  if (block.starting.length === 0) return null
  const ranked = block.starting.slice().sort((a, b) => b.median - a.median)

  return (
    <section className="bg-panel px-10 py-10">
      <div className="mb-6 text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">
        {block.action ? `The ${block.action.toLowerCase()} squad` : 'Resulting squad'}
      </div>
      <div className="flex flex-wrap items-end gap-x-8 gap-y-6">
        {ranked.map((pl, i) => {
          const tier: Tier = pl.player_id === block.captain_id ? 'captain' : i < 3 ? 'featured' : 'normal'
          return <GalleryTile key={pl.player_id} p={pl} captainId={block.captain_id} viceId={block.vice_id} tier={tier} />
        })}
      </div>
      {block.bench.length > 0 && (
        <div className="mt-8 flex flex-wrap items-end gap-x-7 gap-y-4 border-t-2 border-divider/60 pt-6 opacity-60">
          {block.bench.map((pl) => (
            <GalleryTile key={pl.player_id} p={pl} captainId={null} viceId={null} tier="bench" />
          ))}
        </div>
      )}
    </section>
  )
}
