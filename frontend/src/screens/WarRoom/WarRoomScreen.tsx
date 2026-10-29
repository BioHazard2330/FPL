import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, ScreenError } from '@/components/shell/ScreenStates'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { crestUrl, fetchComparePayload, fetchExplorerPayload, fetchWhatIf } from '@/lib/api'
import { clubColors } from '@/lib/clubs'
import { useFetch } from '@/lib/useFetch'
import type { ComparePayload, ExplorerPlayer, WhatIfPayload } from '@/lib/types'

/** THE WAR ROOM - transfers by hand. Drag a player from the market onto one of yours (or click one, then the other) and the
 * deal is priced at once by the same engine the plan uses (`/api/whatif`): legality and bank, points for each of the next
 * five gameweeks before and after, the hit, the league odds, and both players' football reads side by side, so the numbers
 * and the eye are on one ticket. Up to three moves. Nothing is sent to FPL. */

const POS = ['GKP', 'DEF', 'MID', 'FWD'] as const
const signed = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`
const STAMP: Record<string, string> = { 'backs him': 'bg-pitch-green text-pitch-green-ink', mixed: 'bg-broadcast-gold text-ink', 'against him': 'bg-alert-red text-alert-red-ink' }
const FDR = (d: number | null) => (d === null ? 'bg-raised' : d <= 2 ? 'bg-pitch-green text-paper' : d >= 4 ? 'bg-alert-red text-paper' : 'bg-raised text-text')

function MarketCard({ p, picked, onPick }: { p: ExplorerPlayer; picked: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      draggable
      onDragStart={(e) => { e.dataTransfer.setData('text/plain', String(p.player_id)); e.dataTransfer.effectAllowed = 'move' }}
      onClick={onPick}
      className={`grid w-full grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-2 border-2 bg-paper px-2 py-1.5 text-left transition-transform hover:-translate-y-0.5 ${picked ? 'border-spot shadow-[3px_3px_0_var(--spot)]' : 'border-ink shadow-[3px_3px_0_var(--ink)]'} cursor-grab active:cursor-grabbing`}
    >
      <PlayerPhoto code={p.photo_code} teamCode={p.team_code} isGkp={p.position === 'GKP'} className="h-11 w-9" />
      <span className="min-w-0">
        <span className="block truncate font-display text-[15px] font-black uppercase leading-tight text-text">{p.name}</span>
        <span className="flex items-center gap-1 text-[11px] text-text-faint">
          {p.team_short} · £{p.price?.toFixed(1)}m
          {p.fixtures.slice(0, 3).map((f, i) => (
            <span key={i} className={`px-0.5 text-[9.5px] font-bold uppercase ${FDR(f.difficulty)}`}>{f.opponent}{f.home ? '' : '·a'}</span>
          ))}
        </span>
      </span>
      <span className="text-right">
        <span className="tabular block font-display text-xl font-black leading-none text-pitch-green">{p.xp_five.toFixed(1)}</span>
        <span className="text-[9.5px] font-bold uppercase text-text-faint">xP 5</span>
      </span>
    </button>
  )
}

function SquadCard({ p, incoming, onDrop, onClick, armed }: {
  p: ExplorerPlayer; incoming: ExplorerPlayer | undefined; onDrop: (id: number) => void; onClick: () => void; armed: boolean
}) {
  const [over, setOver] = useState(false)
  const shown = incoming ?? p
  const club = clubColors(shown.team_code)
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onDrop(Number(e.dataTransfer.getData('text/plain'))) }}
      onClick={onClick}
      className={`relative w-[7.25rem] cursor-pointer border-[3px] bg-paper transition-transform ${over ? 'scale-105 border-spot shadow-[5px_5px_0_var(--spot)]' : armed ? 'border-spot shadow-[4px_4px_0_var(--ink)]' : 'border-ink shadow-[4px_4px_0_var(--ink)]'}`}
    >
      <div className="relative h-[5.5rem] overflow-hidden" style={{ background: `linear-gradient(150deg, ${club.primary}, color-mix(in srgb, ${club.primary} 60%, #17130e))` }}>
        {crestUrl(shown.team_code) && <img src={crestUrl(shown.team_code)!} alt="" className="absolute -right-3 -top-3 size-14 opacity-25 mix-blend-multiply" />}
        <PlayerPhoto code={shown.photo_code} teamCode={shown.team_code} isGkp={shown.position === 'GKP'} className="mx-auto h-[5.5rem] w-[4.5rem]" />
        {incoming && <span className="absolute left-0 top-0 bg-pitch-green px-1 font-display text-[11px] font-black uppercase text-paper">in</span>}
        {incoming && (
          <span className="absolute bottom-0 left-0 max-w-full truncate bg-alert-red px-1 text-[10px] font-bold uppercase text-paper line-through">{p.name}</span>
        )}
      </div>
      <div className="flex items-stretch border-t-[3px] border-ink">
        <span className="min-w-0 flex-1 truncate bg-ink px-1 py-0.5 font-display text-[12.5px] font-black uppercase text-paper">{shown.name}</span>
        <span className="tabular bg-pitch-green px-1 py-0.5 font-display text-[13px] font-black text-paper">{shown.xp_five.toFixed(1)}</span>
      </div>
    </div>
  )
}

function Read({ label, title, player }: { label: string; title: string; player: ComparePayload['a'] | undefined }) {
  const r = player?.football_read
  return (
    <div className="min-w-0">
      <div className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-text-faint">{title}</div>
      <div className="flex items-center gap-2">
        <span className="font-display text-lg font-black uppercase text-text">{label}</span>
        {r && <span className={`rotate-[-3deg] border-2 border-ink px-1.5 font-display text-[11px] font-black uppercase ${STAMP[r.verdict.label] ?? 'bg-paper'}`}>{r.verdict.label}</span>}
      </div>
      {r && <p className="mt-0.5 text-[12px] leading-snug text-text-muted">{r.verdict.text}</p>}
    </div>
  )
}

export function WarRoomScreen() {
  const market = useFetch(fetchExplorerPayload, [])
  const [moves, setMoves] = useState<[number, number][]>([])
  const [pickedIn, setPickedIn] = useState<number | null>(null)
  const [pos, setPos] = useState<(typeof POS)[number]>('MID')
  const [q, setQ] = useState('')
  const [deal, setDeal] = useState<WhatIfPayload | null>(null)
  const [reads, setReads] = useState<Record<string, ComparePayload>>({})
  const [busy, setBusy] = useState(false)

  const players = useMemo(() => (market.status === 'ready' ? market.data.players ?? [] : []), [market])
  const byId = useMemo(() => new Map(players.map((p) => [p.player_id, p])), [players])
  const squad = players.filter((p) => p.mine)
  const inIds = new Set(moves.map(([, i]) => i))
  const rail = players
    .filter((p) => !p.mine && !inIds.has(p.player_id) && p.position === pos && p.team_short !== 'MUN')
    .filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase()) || p.team_short.toLowerCase() === q.toLowerCase())
    .sort((a, b) => b.xp_five - a.xp_five)
    .slice(0, 24)

  useEffect(() => {
    if (moves.length === 0) { setDeal(null); return }
    let alive = true
    setBusy(true)
    fetchWhatIf(moves).then((d) => { if (alive) setDeal(d) }).catch(() => {}).finally(() => alive && setBusy(false))
    for (const [o, i] of moves) {
      const key = `${o}-${i}`
      if (!reads[key]) fetchComparePayload(o, i).then((c) => alive && setReads((r) => ({ ...r, [key]: c }))).catch(() => {})
    }
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(moves)])

  const place = (outId: number, inId: number) => {
    const o = byId.get(outId), i = byId.get(inId)
    if (!o || !i || o.position !== i.position || i.mine) return
    setMoves((m) => [...m.filter(([a]) => a !== outId), [outId, inId] as [number, number]].slice(-3))
    setPickedIn(null)
  }

  if (market.status === 'loading') return <div className="animate-pulse px-10 py-8"><Skel className="h-[36rem] w-full" /></div>
  if (market.status === 'error') return <ScreenError title="The war room is unavailable" description="The market could not be loaded." message={market.error.message} />

  const incomingFor = new Map(moves.map(([o, i]) => [o, byId.get(i)]))
  const totals = deal?.totals
  const maxGw = Math.max(1, ...(deal?.per_gw ?? []).flatMap((g) => [g.before, g.after]))

  return (
    <div className="data-in pb-16">
      <Masthead right={<span>drag from the market onto your player · up to three moves · nothing is sent to FPL</span>} />
      <section className="relative overflow-hidden !bg-ink px-10 py-7 text-paper">
        <div className="absolute inset-0 opacity-20 [background-image:radial-gradient(rgba(246,240,226,0.4)_1px,transparent_1.5px)] [background-size:7px_7px]" />
        <div className="relative flex flex-wrap items-end justify-between gap-6">
          <div>
            <div className="voice text-xl text-paper/70">transfers by hand, priced by the plan's own engine</div>
            <div className="font-display text-[5.5rem] font-black uppercase leading-[0.85] [text-shadow:5px_5px_0_var(--spot)]">The war room</div>
          </div>
          <div className="flex gap-[2px] border-2 border-paper/30 bg-paper/30">
            {[
              ['moves', String(moves.length)],
              ['net over 5 GW', totals ? signed(totals.gain_net) : '—'],
              ['bank after', deal?.bank_after_tenths !== undefined ? `£${(deal.bank_after_tenths / 10).toFixed(1)}m` : '—'],
              ['hits', deal?.hits !== undefined ? String(deal.hits) : '—'],
            ].map(([k, v]) => (
              <div key={k} className="bg-ink px-4 py-2">
                <div className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-paper/60">{k}</div>
                <div className={`tabular font-display text-3xl font-black ${k === 'net over 5 GW' && totals ? (totals.gain_net >= 0 ? 'text-[#7fe0a6]' : 'text-[#ff8a7a]') : ''}`}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-8 px-8 py-7 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="pitch-surface relative border-[3px] border-ink px-4 py-6">
          {POS.map((ps) => (
            <div key={ps} className="relative z-10 mb-5 flex flex-wrap justify-center gap-3 last:mb-0">
              {squad.filter((p) => p.position === ps).map((p) => (
                <SquadCard
                  key={p.player_id} p={p} incoming={incomingFor.get(p.player_id)} armed={pickedIn !== null && byId.get(pickedIn)?.position === ps}
                  onDrop={(id) => place(p.player_id, id)}
                  onClick={() => (pickedIn !== null ? place(p.player_id, pickedIn) : incomingFor.has(p.player_id) && setMoves((m) => m.filter(([o]) => o !== p.player_id)))}
                />
              ))}
            </div>
          ))}
          {moves.length > 0 && (
            <button type="button" onClick={() => setMoves([])} className="relative z-10 mx-auto mt-2 block border-2 border-ink bg-paper px-3 py-1 font-display text-[13px] font-black uppercase text-text shadow-[3px_3px_0_var(--ink)]">
              clear the board
            </button>
          )}
        </div>
        <div>
          <div className="flex gap-1">
            {POS.map((ps) => (
              <button key={ps} type="button" onClick={() => setPos(ps)}
                className={`flex-1 border-2 border-ink py-1 font-display text-[14px] font-black ${pos === ps ? 'bg-ink text-paper' : 'bg-paper text-text'}`}>{ps}</button>
            ))}
          </div>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search a name or club code"
            className="mt-2 w-full border-2 border-ink bg-paper px-3 py-2 text-sm shadow-[3px_3px_0_var(--ink)] outline-none" />
          <div className="mt-3 max-h-[38rem] space-y-2 overflow-y-auto pr-1">
            {rail.map((p) => <MarketCard key={p.player_id} p={p} picked={pickedIn === p.player_id} onPick={() => setPickedIn(pickedIn === p.player_id ? null : p.player_id)} />)}
          </div>
        </div>
      </section>

      {moves.length > 0 && (
        <section className="px-10 pb-8 pt-7">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="font-display text-text">The deal</h2>
            {busy && <span className="voice text-text-muted">pricing…</span>}
          </div>
          {deal?.problems && deal.problems.length > 0 && (
            <div className="mt-3 border-2 border-alert-red bg-[color-mix(in_srgb,var(--alert-red)_10%,var(--paper))] px-4 py-2 text-[13.5px] text-alert-red">
              {deal.problems.join(' · ')}
            </div>
          )}
          <div className="mt-4 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <div className="space-y-4">
              {moves.map(([o, i]) => {
                const c = reads[`${o}-${i}`]
                return (
                  <div key={`${o}-${i}`} className="grid grid-cols-2 gap-4 border-2 border-ink bg-paper p-4 shadow-[4px_4px_0_var(--ink)]">
                    <Read title="out" label={byId.get(o)?.name ?? ''} player={c?.a} />
                    <Read title="in" label={byId.get(i)?.name ?? ''} player={c?.b} />
                    {c && (c.a.football_read?.verdict.label === 'backs him' || c.b.football_read?.verdict.label === 'against him') && (
                      <div className="col-span-2 border-2 border-broadcast-gold bg-[color-mix(in_srgb,var(--broadcast-gold)_12%,var(--paper))] px-3 py-1.5 text-[12.5px] text-text">
                        The eye gate: {c.a.football_read?.verdict.label === 'backs him' ? `selling ${c.a.name}, whom the football backs` : `buying ${c.b.name}, whom the football is against`},
                        has to earn 1.5 more than any other move before the plan will make it.
                      </div>
                    )}
                    {c && (
                      <div className="col-span-2 flex flex-wrap gap-x-5 gap-y-1 border-t border-divider pt-2 text-[12.5px] text-text-muted">
                        <span>xP 5: <span className="font-semibold text-text">{c.a.xp_window.toFixed(1)} → {c.b.xp_window.toFixed(1)}</span></span>
                        <Link to={`/compare?a=${o}&b=${i}`} className="font-semibold text-broadcast-blue hover:underline">full comparison →</Link>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            <div className="border-2 border-ink bg-paper p-5 shadow-[5px_5px_0_var(--ink)]">
              <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-text-faint">points by gameweek, before and after</div>
              <div className="mt-3 flex items-end gap-3">
                {(deal?.per_gw ?? []).map((g) => (
                  <div key={g.event} className="flex flex-1 flex-col items-center">
                    <div className="flex h-36 w-full items-end justify-center gap-1">
                      <div className="w-1/3 border-2 border-ink bg-raised" style={{ height: `${(g.before / maxGw) * 100}%` }} title={`before ${g.before.toFixed(1)}`} />
                      <div className={`w-1/3 border-2 border-ink ${g.after >= g.before ? 'bg-pitch-green' : 'bg-alert-red'}`} style={{ height: `${(g.after / maxGw) * 100}%` }} title={`after ${g.after.toFixed(1)}`} />
                    </div>
                    <div className={`tabular mt-1 font-display text-[14px] font-black ${g.after - g.before >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(g.after - g.before)}</div>
                    <div className="font-display text-[12px] font-black text-text-faint">GW{g.event}</div>
                  </div>
                ))}
              </div>
              {totals && (
                <div className="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-1 border-t-2 border-ink pt-3">
                  <span className={`tabular font-display text-5xl font-black ${totals.gain_net >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>{signed(totals.gain_net)}</span>
                  <span className="text-[13px] text-text-muted">over five gameweeks after hits ({signed(totals.gain_gross)} before)</span>
                </div>
              )}
              {deal?.plan && (
                <p className="mt-2 text-[12.5px] text-text-muted">
                  The plan of record: {deal.plan.moves.length ? deal.plan.moves.join(', ') : 'roll'}{deal.plan.gain !== null ? ` (${signed(deal.plan.gain)})` : ''}.
                  {' '}This ticket sets the moves against keeping the squad as it is; the plan weighs them against its whole road,
                  where the same transfers may be worth more a week later with more free transfers banked, and it trusts a short
                  record and an eye-gated move less.
                </p>
              )}
              {(deal?.leagues ?? []).filter((l) => l.full).slice(0, 2).map((l) => (
                <p key={l.id} className="mt-1 text-[12.5px] text-text-muted">
                  {l.name}: chance to lead {Math.round((l.odds.before.p_lead ?? 0) * 100)}% → <span className="font-semibold text-text">{Math.round((l.odds.after.p_lead ?? 0) * 100)}%</span>
                </p>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
