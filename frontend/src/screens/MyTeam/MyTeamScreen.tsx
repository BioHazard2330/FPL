import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { Masthead } from '@/components/shell/Masthead'
import { crestUrl, fetchMyTeamPayload, shirtUrl } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { Skel, SkelMasthead, SkelRail, ScreenError } from '@/components/shell/ScreenStates'
import { FixtureRun, NextFixture } from '@/components/football/FixtureRun'
import { pressureInk, runPressure } from '@/lib/fdr'
import { PitchMarkings } from '@/components/football/PitchMarkings'
import { Pitch3D, type Pitch3DPlayer } from '@/components/three/Pitch3D'
import type { FixtureContext, SquadPlayer } from '@/lib/types'

const TIER_DOT: Record<string, string> = {
  CORE: 'bg-broadcast-gold',
  WEAK_LINK: 'bg-alert-red',
  MINUTES_RISK: 'bg-broadcast-blue',
}
const TIER_TITLE: Record<string, string> = {
  CORE: 'Top projected starter this GW',
  WEAK_LINK: 'Real low-output starter (below 3.0 xP)',
  MINUTES_RISK: 'Starting, but under 60 expected minutes',
}
const CONFIDENCE_COLOR: Record<string, string> = {
  HIGH: 'text-pitch-green', MEDIUM: 'text-broadcast-gold', LOW: 'text-alert-red', VERY_LOW: 'text-alert-red',
}

function PlayerTile({ p, dim = false, fixtures, onSelect }: {
  p: SquadPlayer
  dim?: boolean
  fixtures?: FixtureContext
  onSelect: (p: SquadPlayer) => void
}) {
  // Real next fixture for this player's own club. The pitch used to show
  // eleven projections with no opponent anywhere on it - the first thing
  // any FPL manager actually reads off a squad.
  const run = p.team_code !== null ? fixtures?.[String(p.team_code)] : undefined
  // Real size hierarchy on the pitch itself (art-direction pass, 2026-09-08 v2)
  // - CORE reads as the tactical focal point, WEAK_LINK/MINUTES_RISK shrink,
  // never a decorative choice, the same tier the dot already encodes.
  const big = p.tier === 'CORE' && !dim
  const small = (p.tier === 'WEAK_LINK' || p.tier === 'MINUTES_RISK') && !dim
  const shirtPx = big ? 150 : small ? 76 : 110
  const shirt = shirtUrl(p.team_code, p.position === 'GKP', shirtPx)
  const crest = crestUrl(p.team_code)
  // Real lineup reveal (2026-09-10): a confirmed starter used to render
  // identically to a merely-predicted one - the one moment that actually
  // matters (the real teamsheet dropping) was invisible. A confirmed OUT
  // already had a badge; a confirmed IN gets the equivalent positive one.
  const confirmedIn = p.lineup?.state === 'CONFIRMED_STARTING'
  const confirmedOut = p.lineup !== null && p.lineup !== undefined
    && (p.lineup.state === 'OUT_UNAVAILABLE' || p.lineup.state === 'CONFIRMED_BENCHED')
  const boxClass = big ? 'h-20 w-20' : small ? 'h-11 w-11' : 'h-14 w-14'
  const ringClass = confirmedIn ? 'ring-2 ring-pitch-green' : confirmedOut ? 'ring-2 ring-alert-red' : ''
  return (
    <HoverCard>
      <HoverCardTrigger
        render={
          <button
            onClick={() => onSelect(p)}
            className={`relative flex flex-col items-center text-center focus:outline-none focus-visible:ring-1 focus-visible:ring-pitch-green ${big ? 'w-28' : 'w-24'} ${dim ? 'opacity-60' : ''}`}
            title={p.lineup?.detail ?? undefined}
          >
            {p.tier && (
              <span
                className={`absolute left-1 top-0 h-2 w-2 ${TIER_DOT[p.tier]}`}
                title={TIER_TITLE[p.tier]}
                aria-hidden="true"
              />
            )}
            {(p.is_captain || p.is_vice) && (
              <span className={`absolute right-1 top-0 flex h-4 w-4 items-center justify-center text-[10px] font-bold ${p.is_captain ? 'bg-broadcast-gold text-broadcast-gold-ink' : 'bg-raised text-text'}`}>
                {p.is_captain ? 'C' : 'V'}
              </span>
            )}
            <div className={`relative ${boxClass} ${ringClass}`}>
              {shirt ? (
                <img src={shirt} alt={`${p.team_short} shirt`} loading="lazy" className={`${boxClass} object-contain`} />
              ) : (
                <div className={`${boxClass} bg-raised`} />
              )}
              {crest && <img src={crest} alt="" loading="lazy" className="absolute -bottom-0.5 -right-0.5 h-4 w-4 rounded-full bg-void ring-2 ring-void" />}
            </div>
            <div className={`mt-1 w-full truncate font-bold text-text ${big ? 'text-sm' : 'text-xs'}`}>{p.name}</div>
            <div className="text-[10px] text-text-faint">
              {p.team_short} &middot; £{p.price_m.toFixed(1)}m
            </div>
            <div className={`tabular font-bold text-pitch-green ${big ? 'text-base' : 'text-sm'}`}>{p.median.toFixed(1)}</div>
            <NextFixture fixtures={run} className="mt-0.5" />
            {confirmedIn && (
              <span className="mt-0.5 bg-pitch-green px-1 py-0.5 text-[9px] font-bold uppercase text-pitch-green-ink">Confirmed</span>
            )}
            {confirmedOut && p.lineup && (
              <span className="mt-0.5 bg-alert-red px-1 py-0.5 text-[9px] font-bold uppercase text-alert-red-ink">{p.lineup.label}</span>
            )}
          </button>
        }
      />
      <HoverCardContent className="w-56 rounded-none border-2 border-divider bg-panel p-0 text-text ring-0">
        <div className="border-b-2 border-divider px-3 py-2">
          <div className="font-display text-sm font-bold text-text">{p.name}</div>
          <div className="text-[10px] text-text-faint">{p.team_short} &middot; {p.position}</div>
          <FixtureRun fixtures={run} max={5} showEvent className="mt-1.5" />
        </div>
        <div className="grid grid-cols-3 gap-px bg-divider">
          <div className="bg-panel px-2 py-2 text-center">
            <div className="text-[9px] font-bold uppercase text-text-faint">Floor</div>
            <div className="tabular text-sm font-bold text-text">{p.floor.toFixed(1)}</div>
          </div>
          <div className="bg-pitch-green px-2 py-2 text-center">
            <div className="text-[9px] font-bold uppercase text-pitch-green-ink opacity-70">Median</div>
            <div className="tabular text-sm font-bold text-pitch-green-ink">{p.median.toFixed(1)}</div>
          </div>
          <div className="bg-panel px-2 py-2 text-center">
            <div className="text-[9px] font-bold uppercase text-text-faint">Ceiling</div>
            <div className="tabular text-sm font-bold text-text">{p.ceiling.toFixed(1)}</div>
          </div>
        </div>
        <div className="space-y-1 px-3 py-2 text-[11px]">
          <div className="flex justify-between">
            <span className="text-text-faint">Confidence</span>
            <span className={`font-bold ${CONFIDENCE_COLOR[p.confidence] ?? 'text-text'}`}>{p.confidence}</span>
          </div>
          {p.expected_minutes !== null && (
            <div className="flex justify-between">
              <span className="text-text-faint">Expected mins</span>
              <span className="tabular font-bold text-text">{p.expected_minutes.toFixed(0)}&prime;</span>
            </div>
          )}
          {p.lineup && (
            <div className="flex justify-between">
              <span className="text-text-faint">Lineup</span>
              <span className="font-bold text-text">{p.lineup.label}</span>
            </div>
          )}
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}

function PlayerDetailSheet({ player, onClose }: { player: SquadPlayer | null; onClose: () => void }) {
  const shirt = player ? shirtUrl(player.team_code, player.position === 'GKP', 220) : null
  const crest = player ? crestUrl(player.team_code) : null
  return (
    <Sheet open={player !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="border-l-2 border-divider bg-void p-0 sm:max-w-md">
        {player && (
          <>
            <SheetHeader className="border-b border-divider p-6">
              <div className="flex items-center gap-4">
                {shirt && <img src={shirt} alt="" className="h-16 w-16 object-contain" />}
                <div>
                  <SheetTitle className="font-display text-2xl font-bold text-text">{player.name}</SheetTitle>
                  <div className="mt-1 flex items-center gap-1.5 text-sm text-text-muted">
                    {crest && <img src={crest} alt="" className="h-4 w-4 rounded-full" />}
                    {player.team_short} &middot; {player.position} &middot; £{player.price_m.toFixed(1)}m
                  </div>
                </div>
              </div>
            </SheetHeader>

            <div className="space-y-6 p-6">
              <div className="grid grid-cols-3 gap-px bg-divider">
                <div className="bg-raised p-3">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Floor</div>
                  <div className="tabular text-xl font-bold text-text">{player.floor.toFixed(1)}</div>
                </div>
                <div className="bg-pitch-green p-3">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-pitch-green-ink opacity-70">Median</div>
                  <div className="tabular text-xl font-bold text-pitch-green-ink">{player.median.toFixed(1)}</div>
                </div>
                <div className="bg-raised p-3">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Ceiling</div>
                  <div className="tabular text-xl font-bold text-text">{player.ceiling.toFixed(1)}</div>
                </div>
              </div>

              <div className="space-y-2 text-sm">
                <div className="flex justify-between border-b border-divider pb-2">
                  <span className="text-text-muted">Confidence</span>
                  <span className={`font-bold ${CONFIDENCE_COLOR[player.confidence] ?? 'text-text'}`}>{player.confidence}</span>
                </div>
                {player.expected_minutes !== null && (
                  <div className="flex justify-between border-b border-divider pb-2">
                    <span className="text-text-muted">Expected minutes</span>
                    <span className="tabular font-bold text-text">{player.expected_minutes.toFixed(0)}&prime;</span>
                  </div>
                )}
                {player.tier && (
                  <div className="flex justify-between border-b border-divider pb-2">
                    <span className="text-text-muted">Tier</span>
                    <span className="font-bold text-text">{TIER_TITLE[player.tier]}</span>
                  </div>
                )}
                {player.lineup && (
                  <div className="flex justify-between border-b border-divider pb-2">
                    <span className="text-text-muted">Lineup</span>
                    <span className="font-bold text-text">{player.lineup.label}{player.lineup.detail ? ` · ${player.lineup.detail}` : ''}</span>
                  </div>
                )}
                {(player.is_captain || player.is_vice) && (
                  <div className="flex justify-between border-b border-divider pb-2">
                    <span className="text-text-muted">Armband</span>
                    <span className="font-bold text-broadcast-gold">{player.is_captain ? 'Captain' : 'Vice-captain'}</span>
                  </div>
                )}
                <Link
                  to={`/player/${player.player_id}`}
                  className="mt-2 block bg-raised px-3 py-2 text-center text-[11px] font-bold uppercase tracking-[0.14em] text-text hover:bg-divider"
                >
                  Open full player file
                </Link>
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}


/** The real clubs this squad spans, each with its own upcoming run and that
 * run's mean FDR. Built from the squad the payload already returned - never
 * a second source, so a club can't appear here that isn't on the pitch. */
function squadClubs(p: { positions?: { players: SquadPlayer[] }[]; bench?: SquadPlayer[]; fixtures?: FixtureContext }) {
  const byCode = new Map<string, string>()
  for (const pl of [...(p.positions?.flatMap((pos) => pos.players) ?? []), ...(p.bench ?? [])]) {
    if (pl.team_code !== null) byCode.set(String(pl.team_code), pl.team_short)
  }
  return [...byCode.entries()]
    .map(([code, short]) => {
      const run = (p.fixtures?.[code] ?? []).slice(0, 5)
      return { code, short, run, pressure: runPressure(run) }
    })
    .filter((c) => c.run.length > 0)
    .sort((a, b) => (a.pressure ?? 99) - (b.pressure ?? 99))
}

export function MyTeamScreen() {
  const state = useFetch(fetchMyTeamPayload, [], 60000)
  // Real id, not the fetched row object (2026-09-08, direct user finding:
  // "I don't want that lag" led to real polling on `useFetch` - a stored
  // object reference would freeze the detail sheet on stale data forever
  // once a poll refresh replaces the squad with new objects).
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [view3D, setView3D] = useState(false)

  if (state.status === 'loading') {
    // Shaped like the tactical board it precedes: fact column beside the
    // star block, then the pitch with four occupied rows, then the rail.
    return (
      <div className="animate-pulse pb-16">
        <SkelMasthead />
        <div className="grid grid-cols-1 gap-8 border-b-2 border-divider px-10 py-8 lg:grid-cols-[auto_1fr]">
          <div className="flex flex-col gap-3 lg:border-r-2 lg:border-divider lg:pr-10">
            {[0, 1, 2, 3, 4].map((i) => <Skel key={i} className="h-6 w-40" />)}
          </div>
          <Skel className="h-32 w-64" />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px]">
          <div className="space-y-6 px-10 py-8">
            {[1, 4, 4, 2].map((count, row) => (
              <div key={row} className="flex justify-center gap-4">
                {Array.from({ length: count }, (_, i) => <Skel key={i} className="h-20 w-16" />)}
              </div>
            ))}
          </div>
          <div className="bg-panel px-7 py-10">
            <Skel className="h-2 w-28" />
            <SkelRail rows={8} className="mt-4" />
          </div>
        </div>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <ScreenError
        title="Squad unavailable"
        description="The squad payload could not be fetched. Your real team is unaffected — this screen simply has nothing current to draw, and is not falling back to an older copy."
        message={state.error.message}
      />
    )
  }

  const p = state.data
  if (!p.has_squad) {
    return <div className="p-10 text-text-muted">{p.error ?? 'No squad to show yet.'}</div>
  }

  const star = p.positions?.flatMap((pos) => pos.players).find((pl) => pl.tier === 'CORE') ?? p.positions?.[0]?.players[0]
  const starShirt = star ? shirtUrl(star.team_code, star.position === 'GKP', 220) : null
  const allSquadPlayers = [...(p.positions?.flatMap((pos) => pos.players) ?? []), ...(p.bench ?? [])]
  const selected = selectedId !== null ? (allSquadPlayers.find((pl) => pl.player_id === selectedId) ?? null) : null
  // Real teamsheet-drop moment: at least one squad player's own match has a
  // real confirmed lineup (`lineup_state.py`'s CONFIRMED_STARTING/BENCHED),
  // not just a pre-match prediction.
  const lineupsConfirmed = allSquadPlayers.some(
    (pl) => pl.lineup?.state === 'CONFIRMED_STARTING' || pl.lineup?.state === 'CONFIRMED_BENCHED',
  )

  return (
    <div className="data-in pb-16">
      <Masthead edition="Squad Report" title={p.bar.pitch_heading ?? 'My Team'} />

      {/* HERO - one unified band, not two stacked sections: a compact facts
          column facing the real star-player moment, a single oversized
          ghost numeral running behind both. */}
      <div className="relative overflow-hidden border-b-2 border-divider">
        <span className="ghost-watermark pointer-events-none absolute -right-6 -top-10 select-none font-display text-[13rem] font-bold uppercase leading-none">
          SQUAD
        </span>
        <div className="relative grid grid-cols-1 gap-8 px-10 py-8 lg:grid-cols-[auto_1fr]">
          <div className="flex flex-wrap gap-x-8 gap-y-4 lg:flex-col lg:flex-nowrap lg:gap-y-5 lg:border-r-2 lg:border-divider lg:pr-8">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Squad value</div>
              <div className="tabular font-display text-2xl font-bold text-text">£{p.bar.squad_value_m.toFixed(1)}m</div>
            </div>
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Bank</div>
              <div className="tabular font-display text-2xl font-bold text-text">£{p.bar.bank_m.toFixed(1)}m</div>
            </div>
            {p.bar.formation && (
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Formation</div>
                <div className="font-display text-2xl font-bold text-text">{p.bar.formation}</div>
              </div>
            )}
            {p.bar.captain_name && (
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Captain</div>
                <div className="font-display text-2xl font-bold text-broadcast-gold">{p.bar.captain_name}</div>
              </div>
            )}
            {p.bar.vice_name && (
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Vice</div>
                <div className="font-display text-2xl font-bold text-text-muted">{p.bar.vice_name}</div>
              </div>
            )}
          </div>

          {star && (
            <div className="flex items-end gap-8">
              {starShirt && (
                <div className="relative h-40 w-40 shrink-0">
                  <img src={starShirt} alt="" className="h-40 w-40 object-contain" />
                </div>
              )}
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Top projected this GW</div>
                <div className="font-display text-5xl font-bold uppercase text-text">{star.name}</div>
                <div className="tabular mt-1 text-3xl font-bold text-pitch-green">{star.median.toFixed(1)} xP</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* TACTICAL BOARD - the pitch (+ bench, real substitutes standing by)
          runs alone in the main column, uninterrupted; every supporting
          fact moves into a real, wide analysis rail alongside it - a true
          left/right split for the whole surface, not sections stacked
          under a full-width pitch. */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px]">
        <div className="border-r-0 border-divider px-8 py-10 lg:border-r-2">
          <div className="mb-3 flex items-center justify-between">
            {lineupsConfirmed ? (
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-pitch-green">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-pitch-green" aria-hidden="true" />
                Lineups confirmed
              </div>
            ) : (
              <span />
            )}
            <button
              type="button"
              onClick={() => setView3D((v) => !v)}
              className={`px-3 py-1.5 text-[10px] font-bold uppercase tracking-wide ${view3D ? 'bg-pitch-green text-pitch-green-ink' : 'bg-raised text-text-muted hover:text-text'}`}
            >
              {view3D ? 'Flat view' : '3D view'}
            </button>
          </div>
          {view3D ? (
            <div className="h-[28rem] w-full border-2 border-divider">
              <Pitch3D
                players={(p.positions ?? []).flatMap((pos, rowIdx) =>
                  pos.players.map((pl, slot): Pitch3DPlayer => ({
                    playerId: pl.player_id, name: pl.name, row: rowIdx, rowCount: pos.players.length, slot,
                    isCaptain: pl.is_captain,
                    crestUrl: crestUrl(pl.team_code),
                  })),
                )}
              />
            </div>
          ) : (
            <div className="pitch-surface relative flex flex-col justify-between gap-7 px-6 py-14">
              <PitchMarkings />
              {p.positions?.map((pos) => (
                <div key={pos.position} className="relative flex items-center gap-4">
                  <span className="w-9 shrink-0 text-right text-[9px] font-bold uppercase tracking-[0.14em] text-text-faint">
                    {pos.label}
                  </span>
                  <div className="flex flex-1 flex-wrap justify-center gap-6">
                    {pos.players.map((pl) => (
                      <PlayerTile key={pl.player_id} p={pl} fixtures={p.fixtures} onSelect={(pl) => setSelectedId(pl.player_id)} />
                    ))}
                  </div>
                  <span className="w-9 shrink-0" />
                </div>
              ))}
            </div>
          )}

          {p.bench && p.bench.length > 0 && (
            <div className="mt-6 flex items-center gap-6 border-t-2 border-divider pt-5">
              <div className="shrink-0 text-[10px] font-bold uppercase tracking-wide text-text-faint">Bench</div>
              <div className="flex flex-1 flex-wrap gap-x-6 gap-y-4 opacity-70">
                {p.bench.map((pl) => (
                  <PlayerTile key={pl.player_id} p={pl} dim fixtures={p.fixtures} onSelect={(pl) => setSelectedId(pl.player_id)} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT: a real analysis rail, not a near-empty margin - carrying,
            pressure, and risk each get their own real visual treatment,
            stacked to run the full height beside the pitch. */}
        <aside className="bg-panel px-7 py-10">
          <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-text-faint">Squad signals</div>

          {p.strong_link && (
            <div className="mt-5 border-t-2 border-divider pt-4">
              <div className="text-[10px] font-bold uppercase tracking-wide text-pitch-green">Carrying</div>
              <div className="mt-1 font-display text-2xl font-bold text-text">{p.strong_link.name}</div>
              <div className="tabular text-sm text-pitch-green">{p.strong_link.median.toFixed(1)} xP &middot; {p.strong_link.team_short}</div>
            </div>
          )}

          {p.weak_links && p.weak_links.length > 0 && (
            <div className="mt-6 border-t-2 border-divider pt-4">
              <div className="text-[10px] font-bold uppercase tracking-wide text-alert-red">Transfer pressure</div>
              <div className="mt-3 divide-y divide-divider">
                {p.weak_links.map((w) => (
                  <div key={w.name} className="flex items-baseline justify-between py-2.5">
                    <span className="text-sm font-semibold text-text">{w.name}</span>
                    <span className="tabular text-xl font-bold text-alert-red">{w.median.toFixed(1)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {p.risks && p.risks.length > 0 && (
            <div className="mt-6 border-t-2 border-divider pt-4">
              <div className="text-[10px] font-bold uppercase tracking-wide text-broadcast-gold">Squad risks</div>
              <div className="mt-3 space-y-3">
                {p.risks.map((r, i) => (
                  <p key={i} className="border-l-2 border-broadcast-gold/50 pl-3 text-sm leading-relaxed text-text-muted">{r}</p>
                ))}
              </div>
            </div>
          )}

          {/* FIXTURE OUTLOOK - the squad's real clubs ranked by the mean FDR
              of the same fixture cells drawn beside them. Arithmetic over
              what is on screen, labelled as such, never a model output. The
              question it answers - "whose run turns bad, and when" - is the
              one a manager asks right after "who is in my team", and this
              rail previously just ended in dead space. */}
          {p.fixtures && Object.keys(p.fixtures).length > 0 && (
            <div className="mt-6 border-t-2 border-divider pt-4">
              <div className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Fixture outlook</div>
              <div className="mt-0.5 text-[10px] text-text-faint">next 5 &middot; my clubs &middot; kindest run first</div>
              <div className="mt-3 space-y-2.5">
                {squadClubs(p).map((c) => (
                  <div key={c.code} className="flex items-center gap-2">
                    {crestUrl(Number(c.code)) && <img src={crestUrl(Number(c.code))!} alt="" className="h-4 w-4 shrink-0" />}
                    <span className="w-10 shrink-0 text-[11px] font-bold text-text">{c.short}</span>
                    <FixtureRun fixtures={c.run} max={5} />
                    <span className={`tabular ml-auto shrink-0 text-sm font-bold ${pressureInk(c.pressure)}`}>
                      {c.pressure?.toFixed(1) ?? '—'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>

      <PlayerDetailSheet player={selected} onClose={() => setSelectedId(null)} />
    </div>
  )
}
