import { Link } from 'react-router-dom'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'

/** WHAT THE 10K DID: the cohort's locked picks at the last deadline against the week before - who they bought and sold
 * (wildcards and free hits counted apart), the armband, chips and hits - with your squad marked. */
export interface MoveRow { player_id: number; name: string; photo_code: number | null; team_code: number | null; team_short: string; count: number; share: number | null; owned_share: number; mine: boolean }
export interface WeekMovesData {
  event: number; managers: number; movers: number; transfers_mean: number | null; took_hit: number | null
  chips: Record<string, number>; ins: MoveRow[]; outs: MoveRow[]; captains: MoveRow[]; template_missing: MoveRow[]
}

const CHIP: Record<string, string> = { wildcard: 'Wildcard', freehit: 'Free hit', bboost: 'Bench boost', '3xc': 'Triple captain' }
const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

function Bar({ r, tone, compact }: { r: MoveRow; tone: string; compact?: boolean }) {
  return (
    <Link to={`/player/${r.player_id}`} className="grid grid-cols-[1.9rem_minmax(0,1fr)_5rem_2.6rem] items-center gap-2.5 py-1 hover:bg-raised/50">
      <PlayerPhoto code={r.photo_code} teamCode={r.team_code} className="h-8 w-6" />
      <span className="min-w-0 truncate text-[13.5px]">
        <span className="font-bold text-text">{r.name}</span>
        {!compact && <span className="ml-1.5 text-[11.5px] text-text-faint">{r.team_short}</span>}
        {r.mine && <span className="ml-1.5 bg-ink px-1 font-display text-[10px] font-black uppercase text-paper">yours</span>}
      </span>
      <span className="relative h-4 border-2 border-ink bg-paper">
        <span className={`absolute inset-y-0 left-0 ${tone}`} style={{ width: `${Math.max(3, (r.share ?? 0) * 100)}%` }} />
      </span>
      <span className="tabular text-right font-display text-[15px] font-black text-text">{pct(r.share)}</span>
    </Link>
  )
}

export function WeekMoves({ d, compact = false }: { d: WeekMovesData; compact?: boolean }) {
  const n = compact ? 5 : 8
  const col = 'min-w-0'
  const head = 'mb-1.5 font-display text-[13px] font-black uppercase tracking-[0.08em]'
  return (
    <div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-[12.5px] text-text-muted">
        <span><span className="tabular font-display text-lg font-black text-text">{d.managers}</span> managers at the GW{d.event} deadline</span>
        {d.transfers_mean !== null && <span><span className="tabular font-display text-lg font-black text-text">{d.transfers_mean.toFixed(1)}</span> transfers each</span>}
        {d.took_hit !== null && <span><span className="tabular font-display text-lg font-black text-text">{pct(d.took_hit)}</span> took a hit</span>}
        {Object.entries(d.chips).map(([k, v]) => (
          <span key={k}><span className="tabular font-display text-lg font-black text-spot">{pct(v)}</span> {CHIP[k] ?? k}</span>
        ))}
      </div>
      <div className={`mt-4 grid gap-6 ${compact ? 'grid-cols-1' : 'grid-cols-1 xl:grid-cols-3'}`}>
        <div className={col}>
          <div className={`${head} text-pitch-green`}>Bought</div>
          {d.ins.slice(0, n).map((r) => <Bar key={r.player_id} r={r} tone="bg-pitch-green" compact={compact} />)}
        </div>
        <div className={col}>
          <div className={`${head} text-alert-red`}>Sold</div>
          {d.outs.slice(0, n).map((r) => <Bar key={r.player_id} r={r} tone="bg-alert-red" compact={compact} />)}
        </div>
        {!compact && (
          <div className={col}>
            <div className={`${head} text-broadcast-gold`}>Armband</div>
            {d.captains.map((r) => <Bar key={r.player_id} r={r} tone="bg-broadcast-gold" />)}
            <div className={`${head} mt-4 text-text`}>Their most-owned, not yours</div>
            {d.template_missing.slice(0, 5).map((r) => <Bar key={r.player_id} r={{ ...r, share: r.owned_share }} tone="bg-broadcast-blue" />)}
          </div>
        )}
      </div>
    </div>
  )
}
