import { Link } from 'react-router-dom'
import { crestUrl, shirtUrl } from '@/lib/api'
import { NextFixture } from '@/components/football/FixtureRun'
import { PitchMarkings } from '@/components/football/PitchMarkings'
import type { ActionSquadBlock, ActionSquadPlayer, FixtureContext } from '@/lib/types'

type Tier = 'captain' | 'normal' | 'bench'

const ROWS: { key: string; label: string }[] = [
  { key: 'GKP', label: 'GK' },
  { key: 'DEF', label: 'DEF' },
  { key: 'MID', label: 'MID' },
  { key: 'FWD', label: 'FWD' },
]

/** Real size hierarchy without breaking the row: the captain reads as the
 * headline player, everyone else is uniform, because inside a formation a
 * player's SIZE can no longer encode rank - their POSITION already encodes
 * something real, and two competing spatial meanings read as neither. Flat
 * crest ring, no drop-shadow glow (DESIGN.md's own no-shadow rule). */
function GalleryTile({ p, captainId, viceId, tier = 'normal', fixtures }: {
  p: ActionSquadPlayer
  captainId: number | null
  viceId: number | null
  tier?: Tier
  fixtures?: FixtureContext
}) {
  const run = p.team_code !== null ? fixtures?.[String(p.team_code)] : undefined
  const pxSize = tier === 'captain' ? 220 : tier === 'bench' ? 66 : 110
  const shirt = shirtUrl(p.team_code, p.position === 'GKP', pxSize)
  const crest = crestUrl(p.team_code)
  const sizeClass = tier === 'captain' ? 'h-[5.5rem] w-[5.5rem]' : tier === 'bench' ? 'h-10 w-10' : 'h-14 w-14'
  const nameClass = tier === 'captain' ? 'text-sm font-bold' : 'text-xs font-bold'
  const medianClass = tier === 'captain' ? 'text-xl' : 'text-sm'
  const widthClass = tier === 'captain' ? 'w-24' : tier === 'bench' ? 'w-16' : 'w-20'
  return (
    <div className={`relative flex flex-col items-center text-center ${widthClass}`}>
      {p.player_id === captainId && (
        <span className="absolute right-1 top-0 z-10 flex h-5 w-5 items-center justify-center bg-broadcast-gold text-xs font-bold text-broadcast-gold-ink">C</span>
      )}
      {p.player_id === viceId && (
        <span className="absolute right-1 top-0 z-10 flex h-4 w-4 items-center justify-center bg-raised text-[10px] font-bold text-text">V</span>
      )}
      <div className={`relative ${sizeClass}`}>
        {shirt ? <img src={shirt} alt="" className={`${sizeClass} object-contain`} /> : <div className={`${sizeClass} bg-raised`} />}
        {crest && <img src={crest} alt="" className="absolute -bottom-0.5 -right-0.5 h-4 w-4 rounded-full bg-void ring-2 ring-void" />}
      </div>
      <Link to={`/player/${p.player_id}`} className={`mt-1.5 w-full truncate text-text hover:text-pitch-green ${nameClass}`}>
        {p.name}
      </Link>
      <div className={`tabular font-bold text-pitch-green ${medianClass}`}>{p.median.toFixed(1)}</div>
      {tier !== 'bench' && <NextFixture fixtures={run} className="mt-0.5" />}
    </div>
  )
}

/** THE ACTION SQUAD, laid out as the football team it actually is.
 *
 * This deliberately does NOT sort by projected median. An earlier version
 * did, and the result was a row that opened with a defender, put the
 * goalkeeper eleventh, and read as a leaderboard of eleven strangers - the
 * exact failure mode of showing football data without showing football.
 * Position is the real spatial signal here; xP is carried by the number
 * under each shirt, where it belongs.
 *
 * Rows are ordered GK -> DEF -> MID -> FWD and centred, so the shape of the
 * side (and the real formation string derived from the counts) is readable
 * at a glance. Within a row players stay in the backend's own order.
 *
 * If the payload's position data can't support a legitimate shape (no
 * keeper, or only one position group present at all), this falls back to a
 * single centred row and says so - a fabricated 4-4-2 out of unknown
 * positions would be a lie about the team. */
export function PlayerGallery({ block, fixtures }: { block: ActionSquadBlock; fixtures?: FixtureContext }) {
  if (block.starting.length === 0) return null

  const byRow = ROWS.map((r) => ({ ...r, players: block.starting.filter((p) => p.position === r.key) }))
  const outfield = byRow.filter((r) => r.key !== 'GKP')
  const hasKeeper = byRow[0].players.length > 0
  const groupsPresent = byRow.filter((r) => r.players.length > 0).length
  const formationReal = hasKeeper && groupsPresent >= 3
  const formation = outfield.map((r) => r.players.length).join('-')

  return (
    <section className="bg-panel px-10 py-10">
      <div className="mb-6 flex flex-wrap items-baseline gap-3">
        <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">
          {block.action ? `The ${block.action.toLowerCase()} squad` : 'Resulting squad'}
        </span>
        {formationReal ? (
          <span className="font-display text-sm font-bold tracking-[0.2em] text-text-muted">{formation}</span>
        ) : (
          <span className="text-[11px] text-text-faint">position data incomplete &mdash; shown as a flat list, not a formation</span>
        )}
      </div>

      {formationReal ? (
        <div className="pitch-surface relative flex min-h-[30rem] flex-col justify-between px-6 py-10">
          <PitchMarkings />
          {byRow.map((row) =>
            row.players.length === 0 ? null : (
              <div key={row.key} className="flex items-end gap-4">
                <span className="w-9 shrink-0 pb-6 text-right text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">
                  {row.label}
                </span>
                <div className="flex flex-1 flex-wrap items-end justify-center gap-x-6 gap-y-5">
                  {row.players.map((pl) => (
                    <GalleryTile
                      key={pl.player_id}
                      p={pl}
                      captainId={block.captain_id}
                      viceId={block.vice_id}
                      tier={pl.player_id === block.captain_id ? 'captain' : 'normal'}
                      fixtures={fixtures}
                    />
                  ))}
                </div>
                <span className="w-9 shrink-0" />
              </div>
            ),
          )}
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-x-6 gap-y-5">
          {block.starting.map((pl) => (
            <GalleryTile
              key={pl.player_id}
              p={pl}
              captainId={block.captain_id}
              viceId={block.vice_id}
              tier={pl.player_id === block.captain_id ? 'captain' : 'normal'}
              fixtures={fixtures}
            />
          ))}
        </div>
      )}

      {block.bench.length > 0 && (
        <div className="mt-8 flex flex-wrap items-end gap-x-7 gap-y-4 border-t-2 border-divider/60 pt-6">
          <span className="w-9 shrink-0 pb-4 text-right text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">SUB</span>
          <div className="flex flex-wrap items-end gap-x-7 gap-y-4 opacity-60">
            {block.bench.map((pl) => (
              <GalleryTile key={pl.player_id} p={pl} captainId={null} viceId={null} tier="bench" />
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
