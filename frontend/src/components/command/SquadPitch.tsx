import { Link } from 'react-router-dom'
import { crestUrl, shirtUrl } from '@/lib/api'
import { NextFixture } from '@/components/football/FixtureRun'
import { PitchMarkings } from '@/components/football/PitchMarkings'
import type { ActionSquadBlock, ActionSquadPlayer, FixtureContext } from '@/lib/types'

const ROWS = ['GKP', 'DEF', 'MID', 'FWD'] as const

function Tile({ p, block, fixtures, bench = false }: { p: ActionSquadPlayer; block: ActionSquadBlock; fixtures?: FixtureContext; bench?: boolean }) {
  const run = p.team_code !== null ? fixtures?.[String(p.team_code)] : undefined
  const shirt = shirtUrl(p.team_code, p.position === 'GKP', bench ? 64 : 112)
  const crest = crestUrl(p.team_code)
  const size = bench ? 'size-10' : 'size-14'
  return (
    <div className={`relative flex flex-col items-center text-center ${bench ? 'w-[4.5rem]' : 'w-[5.5rem]'}`}>
      {p.is_new && <span className="absolute -left-0.5 top-0 z-10 rounded bg-pitch-green px-1 text-[12px] font-bold leading-4 text-pitch-green-ink">new</span>}
      {p.player_id === block.captain_id && (
        <span className="absolute right-1 top-0 z-10 flex size-5 items-center justify-center rounded-full bg-broadcast-gold text-[12px] font-bold text-broadcast-gold-ink">C</span>
      )}
      {p.player_id === block.vice_id && (
        <span className="absolute right-1 top-0 z-10 flex size-5 items-center justify-center rounded-full bg-raised text-[12px] font-bold text-text ring-1 ring-divider">V</span>
      )}
      <div className={`relative ${size}`}>
        {shirt ? <img src={shirt} alt="" className={`${size} object-contain`} /> : <div className={`${size} rounded bg-raised`} />}
        {crest && <img src={crest} alt="" className="absolute -bottom-0.5 -right-1 size-4 rounded-full bg-void ring-2 ring-void" />}
      </div>
      <Link to={`/player/${p.player_id}`} className="mt-1.5 w-full truncate text-[13px] font-semibold text-text hover:text-pitch-green">
        {p.name}
      </Link>
      <div className="tabular text-[13px] font-semibold text-pitch-green">{p.median.toFixed(1)}</div>
      {!bench && <NextFixture fixtures={run} className="mt-0.5 rounded-sm" />}
    </div>
  )
}

/** The squad as a team on a pitch: goalkeeper at the top, the shape of the eleven readable at a glance, expected points under
 * each shirt and the next opponent coloured by difficulty. Rows never wrap and have fixed breathing room, so a long run of
 * names cannot ride into the row below. */
export function SquadPitch({ block, fixtures, title, sub }: { block: ActionSquadBlock; fixtures?: FixtureContext; title: string; sub?: string }) {
  if (block.starting.length === 0) return null
  const rows = ROWS.map((k) => block.starting.filter((p) => p.position === k))
  const formation = rows.slice(1).map((r) => r.length).join('-')
  const total = block.starting.reduce((s, p) => s + p.median, 0)

  return (
    <section className="slab">
      <header className="flex flex-wrap items-baseline justify-between gap-2 px-6 pb-3 pt-5">
        <div>
          <h2 className="font-display text-xl font-semibold leading-tight text-text">{title}</h2>
          {sub && <p className="mt-1 text-[14px] text-text-muted">{sub}</p>}
        </div>
        <div className="tabular text-[13px] text-text-faint">
          {formation} &middot; <span className="font-semibold text-text">{total.toFixed(1)}</span> xP from the eleven
        </div>
      </header>
      <div className="px-6 pb-6">
        <div className="pitch-surface relative flex flex-col gap-9 px-4 py-9">
          <PitchMarkings />
          {rows.map((players, i) =>
            players.length === 0 ? null : (
              <div key={ROWS[i]} className="relative flex items-start justify-center gap-5">
                {players.map((p) => (
                  <Tile key={p.player_id} p={p} block={block} fixtures={fixtures} />
                ))}
              </div>
            ),
          )}
        </div>
        {block.bench.length > 0 && (
          <div className="mt-4 flex items-start gap-5">
            <span className="w-14 shrink-0 pt-2 text-[13px] text-text-faint">Bench</span>
            <div className="flex items-start gap-5 opacity-70">
              {block.bench.map((p) => (
                <Tile key={p.player_id} p={p} block={block} bench />
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
