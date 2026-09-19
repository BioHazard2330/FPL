import { useMemo, useState } from 'react'

/** THE MARKET - what ten million other managers have been doing with him.
 *
 * Top: official ownership as it changed, every sample this project took.
 * Bottom: the gameweek transfer counters - transfers in drawn upward in
 * green, transfers out drawn downward in red, each sample where it was
 * taken. FPL resets both counters at every deadline, so each gameweek is
 * its own sawtooth; the shape of one tooth is how the crowd moved on him
 * that week, and the height of it is how many actually did. Deadlines are
 * marked so a spike can be read against the week it belongs to.
 *
 * Sampled, not continuous: a gap between two samples is a gap in this
 * project's own sync, never interpolated. */

type Own = { t: string | null; pct: number | null }
type Mom = { t: string | null; in: number | null; out: number | null }
type Deadline = { event: number; t: string | null }

const VW = 960
const H_OWN = 130
const H_MOM = 170
const PAD = { l: 48, r: 20 }

function ms(iso: string | null) {
  if (!iso) return NaN
  const v = new Date(iso).getTime()
  return Number.isNaN(v) ? NaN : v
}
function fmt(n: number) {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}m` : n >= 1000 ? `${(n / 1000).toFixed(0)}k` : String(n)
}
function shortDate(t: number) {
  const d = new Date(t)
  return `${d.getDate()} ${d.toLocaleString([], { month: 'short' })}`
}

export function MarketPulse({ ownership, momentum, deadlines }: { ownership: Own[]; momentum: Mom[]; deadlines: Deadline[] }) {
  const [hoverT, setHoverT] = useState<number | null>(null)

  const own = useMemo(() => ownership.map((o) => ({ t: ms(o.t), v: o.pct })).filter((o) => !Number.isNaN(o.t) && o.v !== null) as { t: number; v: number }[], [ownership])
  const mom = useMemo(() => momentum.map((m) => ({ t: ms(m.t), i: m.in ?? 0, o: m.out ?? 0 })).filter((m) => !Number.isNaN(m.t)), [momentum])

  const t0 = Math.min(own[0]?.t ?? Infinity, mom[0]?.t ?? Infinity)
  const t1 = Math.max(own[own.length - 1]?.t ?? -Infinity, mom[mom.length - 1]?.t ?? -Infinity)
  if (!Number.isFinite(t0) || !Number.isFinite(t1) || t1 <= t0) return null

  const sx = (t: number) => PAD.l + ((t - t0) / (t1 - t0)) * (VW - PAD.l - PAD.r)
  const dls = deadlines.map((d) => ({ event: d.event, t: ms(d.t) })).filter((d) => d.t >= t0 && d.t <= t1)

  // Ownership panel.
  const ownMin = Math.max(0, Math.min(...own.map((o) => o.v)) - 1)
  const ownMax = Math.max(...own.map((o) => o.v)) + 1
  const oy = (v: number) => 14 + ((ownMax - v) / (ownMax - ownMin)) * (H_OWN - 28)
  const ownPath = own.map((o, k) => `${k === 0 ? 'M' : 'L'} ${sx(o.t).toFixed(1)} ${oy(o.v).toFixed(1)}`).join(' ')

  // Momentum panel, mirrored around a zero line.
  const momPeak = Math.max(1, ...mom.map((m) => Math.max(m.i, m.o)))
  const zero = H_MOM / 2
  const my = (v: number, dir: 1 | -1) => zero - dir * (v / momPeak) * (H_MOM / 2 - 14)
  const inArea = mom.length ? `M ${sx(mom[0].t)} ${zero} ` + mom.map((m) => `L ${sx(m.t).toFixed(1)} ${my(m.i, 1).toFixed(1)}`).join(' ') + ` L ${sx(mom[mom.length - 1].t)} ${zero} Z` : ''
  const outArea = mom.length ? `M ${sx(mom[0].t)} ${zero} ` + mom.map((m) => `L ${sx(m.t).toFixed(1)} ${my(m.o, -1).toFixed(1)}`).join(' ') + ` L ${sx(mom[mom.length - 1].t)} ${zero} Z` : ''

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * VW
    setHoverT(t0 + ((px - PAD.l) / (VW - PAD.l - PAD.r)) * (t1 - t0))
  }
  const nearest = <T extends { t: number }>(arr: T[], t: number | null): T | null => {
    if (t === null || !arr.length) return null
    let best = arr[0]
    for (const a of arr) if (Math.abs(a.t - t) < Math.abs(best.t - t)) best = a
    return best
  }
  const hOwn = nearest(own, hoverT)
  const hMom = nearest(mom, hoverT)

  const nowOwn = own[own.length - 1]
  const nowMom = mom[mom.length - 1]
  const lastDl = dls.filter((d) => d.t <= t1).slice(-1)[0]
  const ownAtDl = lastDl ? nearest(own, lastDl.t) : null

  return (
    <div className="grid grid-cols-[1fr_240px] gap-8">
      <div>
        <svg viewBox={`0 0 ${VW} ${H_OWN}`} className="h-auto w-full select-none" role="img" aria-label="Ownership over time"
             onMouseMove={onMove} onMouseLeave={() => setHoverT(null)}>
          {dls.map((d) => (
            <g key={d.event}>
              <line x1={sx(d.t)} y1={0} x2={sx(d.t)} y2={H_OWN} stroke="var(--divider)" />
              <text x={sx(d.t) + 4} y={10} fontSize={9} fill="var(--text-faint)" fontWeight={700} letterSpacing="1">GW{d.event}</text>
            </g>
          ))}
          {[ownMin, (ownMin + ownMax) / 2, ownMax].map((v) => (
            <text key={v} x={PAD.l - 8} y={oy(v) + 3} textAnchor="end" fontSize={9} fill="var(--text-faint)" className="tabular">{v.toFixed(1)}%</text>
          ))}
          <path d={ownPath} fill="none" stroke="var(--broadcast-gold)" strokeWidth={2} strokeLinejoin="round" />
          {hOwn && (
            <g>
              <line x1={sx(hOwn.t)} y1={0} x2={sx(hOwn.t)} y2={H_OWN} stroke="var(--text)" strokeOpacity={0.4} strokeDasharray="3 3" />
              <circle cx={sx(hOwn.t)} cy={oy(hOwn.v)} r={4} fill="var(--broadcast-gold)" stroke="var(--void)" strokeWidth={1.5} />
            </g>
          )}
          <text x={PAD.l} y={H_OWN - 4} fontSize={9} fill="var(--text-faint)" letterSpacing="1.2" fontWeight={700}>OWNERSHIP</text>
        </svg>

        <svg viewBox={`0 0 ${VW} ${H_MOM}`} className="mt-2 h-auto w-full select-none" role="img" aria-label="Transfers in and out per gameweek"
             onMouseMove={onMove} onMouseLeave={() => setHoverT(null)}>
          {dls.map((d) => (
            <line key={d.event} x1={sx(d.t)} y1={0} x2={sx(d.t)} y2={H_MOM} stroke="var(--divider)" />
          ))}
          <path d={inArea} fill="var(--pitch-green)" fillOpacity={0.55} />
          <path d={outArea} fill="var(--alert-red)" fillOpacity={0.55} />
          <line x1={PAD.l} y1={zero} x2={VW - PAD.r} y2={zero} stroke="var(--text)" strokeOpacity={0.5} />
          <text x={PAD.l - 8} y={my(momPeak, 1) + 3} textAnchor="end" fontSize={9} fill="var(--pitch-green)" className="tabular">{fmt(momPeak)}</text>
          <text x={PAD.l - 8} y={my(momPeak, -1) + 3} textAnchor="end" fontSize={9} fill="var(--alert-red)" className="tabular">{fmt(momPeak)}</text>
          {hMom && (
            <g>
              <line x1={sx(hMom.t)} y1={0} x2={sx(hMom.t)} y2={H_MOM} stroke="var(--text)" strokeOpacity={0.4} strokeDasharray="3 3" />
              <circle cx={sx(hMom.t)} cy={my(hMom.i, 1)} r={3.5} fill="var(--pitch-green)" stroke="var(--void)" strokeWidth={1.5} />
              <circle cx={sx(hMom.t)} cy={my(hMom.o, -1)} r={3.5} fill="var(--alert-red)" stroke="var(--void)" strokeWidth={1.5} />
            </g>
          )}
          <text x={PAD.l} y={12} fontSize={9} fill="var(--pitch-green)" letterSpacing="1.2" fontWeight={700}>TRANSFERS IN, THIS GAMEWEEK</text>
          <text x={PAD.l} y={H_MOM - 4} fontSize={9} fill="var(--alert-red)" letterSpacing="1.2" fontWeight={700}>TRANSFERS OUT</text>
          <text x={VW - PAD.r} y={H_MOM - 4} fontSize={9} fill="var(--text-faint)" textAnchor="end" className="tabular">{shortDate(t0)} – {shortDate(t1)}</text>
        </svg>
      </div>

      <div className="space-y-5">
        {nowOwn && (
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">Owned by</div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="tabular font-display text-4xl font-bold text-broadcast-gold">{nowOwn.v.toFixed(1)}%</span>
              <span className="text-[10px] uppercase tracking-wide text-text-faint">of managers</span>
            </div>
            {ownAtDl && lastDl && (
              <div className={`tabular mt-1 text-xs font-semibold ${nowOwn.v - ownAtDl.v >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
                {nowOwn.v - ownAtDl.v >= 0 ? '+' : ''}{(nowOwn.v - ownAtDl.v).toFixed(1)} <span className="font-normal text-text-faint">since the GW{lastDl.event} deadline</span>
              </div>
            )}
          </div>
        )}
        {nowMom && (
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-faint">This gameweek so far</div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="tabular font-display text-2xl font-bold text-pitch-green">{fmt(nowMom.i)}</span>
              <span className="text-[10px] uppercase tracking-wide text-text-faint">in</span>
              <span className="tabular font-display text-2xl font-bold text-alert-red">{fmt(nowMom.o)}</span>
              <span className="text-[10px] uppercase tracking-wide text-text-faint">out</span>
            </div>
            <div className={`tabular mt-1 text-xs font-semibold ${nowMom.i - nowMom.o >= 0 ? 'text-pitch-green' : 'text-alert-red'}`}>
              net {nowMom.i - nowMom.o >= 0 ? '+' : '−'}{fmt(Math.abs(nowMom.i - nowMom.o))}
            </div>
          </div>
        )}
        <div className="border-t border-divider pt-4">
          {hOwn || hMom ? (
            <div className="tabular text-xs text-text-muted">
              {hMom && <div className="text-sm font-semibold text-text">{new Date(hMom.t).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</div>}
              {hOwn && <div className="mt-1">owned <span className="font-semibold text-broadcast-gold">{hOwn.v.toFixed(1)}%</span></div>}
              {hMom && <div className="mt-0.5"><span className="font-semibold text-pitch-green">{fmt(hMom.i)}</span> in · <span className="font-semibold text-alert-red">{fmt(hMom.o)}</span> out that gameweek, to that point</div>}
            </div>
          ) : (
            <div className="text-[10px] uppercase tracking-wide text-text-faint">hover the market</div>
          )}
        </div>
        <div className="text-[10px] leading-relaxed text-text-faint">
          Sampled by this project's own syncs; a gap is a gap in sampling, never filled in. Counters reset at each deadline.
        </div>
      </div>
    </div>
  )
}
