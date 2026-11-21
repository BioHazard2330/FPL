import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** The role engine on the Dugout (`models/roles.py`): the league's changes, players FPL lists deeper than they play, and
 * for one club the depth chart on a pitch and who takes the set pieces. */
interface Person { player_id: number; name: string; status: string | null; start_percent: number | null; starts_here: number; recent_here: number; photo_code?: number | null }
interface Slot { x: number; y: number; role: string; slot: string; starter: Person; cover: Person[] }
interface Depth { formation: string | null; matches: number; eleven: Slot[] }
interface Taker { player_id: number; name: string; count: number }
interface SetPieces { corners: Taker[]; corners_last3: Taker[]; penalties: Taker[]; free_kicks: Taker[]; new_corner_taker: { name: string; recent: number; previous: string } | null }
interface Change { kind: string; player_id: number; name: string; team: string; text: string }
interface Oop { player_id: number; name: string; team: string; fpl_position: string; plays_as: string; share: string; recent: string[]; price_tenths: number | null; photo_code?: number | null; per90: Record<string, number | null> }

const ROLE_NAME: Record<string, string> = {
  GK: 'Goalkeeper', CB: 'Centre-back', 'FB-L': 'Left-back', 'FB-R': 'Right-back', 'WB-L': 'Left wing-back', 'WB-R': 'Right wing-back', DM: 'Holding midfield',
  CM: 'Central midfield', AM: 'Number 10', 'W-L': 'Left wing', 'W-R': 'Right wing', ST: 'Striker',
}
const KIND: Record<string, { label: string; cls: string }> = {
  role: { label: 'New role', cls: 'bg-spot text-ink' },
  corner_taker: { label: 'Corners', cls: 'bg-pitch-green text-paper' },
  into_eleven: { label: 'Into the XI', cls: 'bg-ink text-paper' },
  out_of_eleven: { label: 'Dropped', cls: 'bg-alert-red text-paper' },
}

export function LeagueChanges() {
  const state = useFetch(() => getJson<{ changes: Change[]; out_of_position: Oop[] }>('/api/roles'), [])
  if (state.status !== 'ready') return null
  const { changes, out_of_position: oop } = state.data
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="border-2 border-ink bg-paper p-4 shadow-[4px_4px_0_var(--ink)]">
        <div className="font-display text-xl font-black uppercase text-text">What changed in the league</div>
        <div className="text-[12px] text-text/60">From every league match&apos;s line-ups and player records: new roles, new set-piece takers, who came into the eleven and who fell out of it.</div>
        <div className="mt-3 max-h-[26rem] space-y-1.5 overflow-y-auto pr-1">
          {changes.map((c, i) => (
            <div key={i} className="flex items-baseline gap-2 text-[13.5px]">
              <span className={`w-24 shrink-0 px-1.5 py-0.5 text-center text-[10.5px] font-black uppercase ${KIND[c.kind]?.cls ?? ''}`}>{KIND[c.kind]?.label ?? c.kind}</span>
              <span className="w-10 shrink-0 font-display font-black text-text/60">{c.team}</span>
              <Link to={`/player/${c.player_id}`} className="font-display font-black uppercase text-text hover:underline">{c.name}</Link>
              <span className="text-text/75">{c.text.replace(/\b(GK|CB|FB-L|FB-R|WB-L|WB-R|DM|CM|AM|W-L|W-R|ST)\b/g, (m) => ROLE_NAME[m]?.toLowerCase() ?? m)}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="border-2 border-ink bg-ink p-4 text-paper shadow-[4px_4px_0_var(--spot)]">
        <div className="font-display text-xl font-black uppercase">Out of position: FPL scores them wrong</div>
        <div className="text-[12px] text-paper/60">Listed deeper than they play. A defender on the wing gets clean-sheet points with a winger&apos;s chances.</div>
        <div className="mt-3 space-y-2.5">
          {oop.map((o) => (
            <Link key={o.player_id} to={`/player/${o.player_id}`} className="flex items-center gap-3 border-b border-paper/15 pb-2 hover:bg-paper/5">
              <PlayerPhoto code={o.photo_code ?? null} teamCode={null} className="h-11 w-9" bare />
              <div className="min-w-0 flex-1">
                <div className="font-display text-lg font-black uppercase leading-none">{o.name} <span className="text-[12px] text-paper/60">{o.team}</span></div>
                <div className="text-[12.5px]">
                  <b className="text-spot">FPL {o.fpl_position}</b> plays <b>{(ROLE_NAME[o.plays_as] ?? o.plays_as).toLowerCase()}</b> · {o.share}
                </div>
                <div className="tabular text-[11.5px] text-paper/65">
                  {o.per90.touches_opp_box ?? '-'} box touches · {o.per90.chances_created ?? '-'} chances created · {o.per90.cbit ?? '-'} CBIT per 90
                </div>
              </div>
              {o.price_tenths != null && <span className="tabular font-display text-xl font-black">£{(o.price_tenths / 10).toFixed(1)}</span>}
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}

function Chip({ p, main }: { p: Person; main?: boolean }) {
  const flagged = p.status && p.status !== 'a'
  return (
    <Link to={`/player/${p.player_id}`} title={`${p.starts_here} starts here this season${p.start_percent != null ? `, ${p.start_percent}% to start` : ''}`}
      className={`block truncate px-1.5 py-0.5 text-center leading-tight ${main ? 'border-2 border-ink bg-paper font-display text-[13px] font-black uppercase text-ink' : 'text-[11px] font-semibold text-paper'} ${flagged ? 'outline outline-2 outline-alert-red' : ''}`}>
      {p.name}{main && p.start_percent != null ? <span className="ml-1 text-[10px] text-ink/60">{p.start_percent}%</span> : null}
      {!main && <span className="ml-1 text-paper/60">{p.starts_here}</span>}
    </Link>
  )
}

export function ClubRoles({ team }: { team: number }) {
  const state = useFetch(() => getJson<{ depth: Depth | null; set_pieces: SetPieces }>(`/api/roles?team=${team}`), [team])
  if (state.status !== 'ready' || !state.data.depth) return null
  const { depth, set_pieces: sp } = state.data
  const list = (rows: Taker[]) => rows.length ? rows.map((t) => `${t.name} ${t.count}`).join(' · ') : '-'
  return (
    <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <div>
        <div className="mb-2 font-display text-xl font-black uppercase text-text">Depth chart · {depth.formation ?? ''}</div>
        <div className="relative aspect-[105/68] w-full overflow-hidden border-2 border-ink bg-pitch-green">
          <svg viewBox="0 0 105 68" className="absolute inset-0 h-full w-full" preserveAspectRatio="none" aria-hidden="true">
            <g fill="none" stroke="white" strokeOpacity="0.45" strokeWidth="0.4">
              <rect x="1" y="1" width="103" height="66" /><line x1="52.5" y1="1" x2="52.5" y2="67" /><circle cx="52.5" cy="34" r="9.15" />
              <rect x="1" y="13.85" width="16.5" height="40.3" /><rect x="87.5" y="13.85" width="16.5" height="40.3" />
            </g>
          </svg>
          {depth.eleven.map((s) => (
            <div key={s.starter.player_id} className="absolute w-[15%] -translate-x-1/2 -translate-y-1/2" style={{ left: `${s.x * 100}%`, top: `${s.y * 100}%` }}>
              <Chip p={s.starter} main />
              {s.cover.slice(0, 2).map((c) => <Chip key={c.player_id} p={c} />)}
            </div>
          ))}
        </div>
        <div className="mt-1 text-[11.5px] text-text/60">The latest eleven on FotMob&apos;s grid, attacking to the right. Under each starter: who else has started in that slot this season, and how often. A red outline means flagged.</div>
      </div>
      <div className="space-y-3 text-[13.5px]">
        <div className="font-display text-xl font-black uppercase text-text">Set pieces</div>
        {sp.new_corner_taker && (
          <div className="border-2 border-pitch-green bg-pitch-green/10 px-2 py-1 font-semibold text-text">
            New on corners: {sp.new_corner_taker.name}, {sp.new_corner_taker.recent} in the last 3 matches. {sp.new_corner_taker.previous} led the season.
          </div>
        )}
        <div><b className="font-display uppercase">Corners, season:</b> {list(sp.corners)}</div>
        <div><b className="font-display uppercase">Corners, last 3:</b> {list(sp.corners_last3)}</div>
        <div><b className="font-display uppercase">Penalties taken:</b> {list(sp.penalties)}</div>
        <div><b className="font-display uppercase">Direct free kicks shot:</b> {list(sp.free_kicks)}</div>
      </div>
    </div>
  )
}
