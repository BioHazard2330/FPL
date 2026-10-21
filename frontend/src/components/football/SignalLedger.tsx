import { fetchSignalsPayload } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import type { SignalMetric, StreakRow } from '@/lib/types'

/** HOW MUCH TO TRUST A FOOTBALL SIGNAL.
 *
 * Every finding on this screen describes something that happened once. Whether
 * it matters depends on whether it repeats, and that is a number, not a
 * feeling. Top: how well each match-level signal carries into the next match
 * (correlation of a side's or player's prior average with its next match, with a
 * 90% interval; the whisker is that interval and the gold line is the 0.10 a
 * signal must clear). Bottom: what a two-match hot or cold streak is worth next
 * match against a flat season rate, the figure the qualitative adjustment is
 * sized from. */

const VERDICT_STYLE: Record<string, string> = {
  persistent: 'bg-pitch-green/15 text-pitch-green',
  unclear: 'bg-broadcast-gold/15 text-broadcast-gold',
  none: 'bg-alert-red/15 text-alert-red',
  'too few': 'bg-raised text-text-faint',
}

const AX_MIN = -0.3
const AX_MAX = 0.7
const pos = (v: number) => `${((Math.max(AX_MIN, Math.min(AX_MAX, v)) - AX_MIN) / (AX_MAX - AX_MIN)) * 100}%`

function Whisker({ m }: { m: SignalMetric }) {
  return (
    <div className="relative h-6 w-full">
      <div className="absolute inset-x-0 top-1/2 h-px bg-divider" />
      <div className="absolute top-1 h-4 w-px bg-text-faint" style={{ left: pos(0) }} />
      <div className="absolute top-0 h-6 w-px bg-broadcast-gold" style={{ left: pos(0.1) }} title="the 0.10 line a signal must clear" />
      {m.ci && m.r !== null && (
        <>
          <div className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-text-muted" style={{ left: pos(m.ci[0]), width: `calc(${pos(m.ci[1])} - ${pos(m.ci[0])})` }} />
          <div
            className={`absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 ${m.verdict === 'persistent' ? 'bg-pitch-green' : m.verdict === 'none' ? 'bg-alert-red' : 'bg-broadcast-gold'}`}
            style={{ left: pos(m.r) }}
          />
        </>
      )}
    </div>
  )
}

function Ratio({ row }: { row: StreakRow }) {
  const MIN = 0.6
  const MAX = 1.4
  const p = (v: number) => `${((Math.max(MIN, Math.min(MAX, v)) - MIN) / (MAX - MIN)) * 100}%`
  return (
    <div className="relative h-6 w-full">
      <div className="absolute inset-x-0 top-1/2 h-px bg-divider" />
      <div className="absolute top-0 h-6 w-px bg-text-faint" style={{ left: p(1) }} title="1.00: the baseline already knew" />
      {row.ci && row.ratio !== null && (
        <>
          <div className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-text-muted" style={{ left: p(row.ci[0]), width: `calc(${p(row.ci[1])} - ${p(row.ci[0])})` }} />
          <div className={`absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 ${row.ratio >= 1 ? 'bg-pitch-green' : 'bg-alert-red'}`} style={{ left: p(row.ratio) }} />
        </>
      )}
    </div>
  )
}

export function SignalLedger() {
  const state = useFetch(fetchSignalsPayload, [], 600000)
  if (state.status === 'loading') {
    return <div className="mt-10 border-t border-divider px-10 py-8 text-[13px] text-text-faint">Measuring which signals persist&hellip;</div>
  }
  if (state.status === 'error') return null
  const d = state.data
  return (
    <div className="mt-10 border-t border-divider px-10 py-8">
      <div className="mb-1 text-[13px] font-bold uppercase tracking-[0.1em] text-text-faint">How much to trust a football signal</div>
      <p className="mb-6 max-w-3xl text-sm text-text-muted">
        A finding is one match. This is how far each kind of signal has carried into the next match, measured on {d.stories} analysed matches this season and on every
        season in the history. Where a signal does not carry, the analyst marks its findings low confidence.
      </p>

      <div className="grid grid-cols-[minmax(0,15rem)_minmax(0,1fr)_5.5rem_4.5rem] items-end gap-x-5 border-b border-divider pb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">
        <span>Signal</span>
        <span className="relative block h-3">
          {[-0.3, 0, 0.1, 0.3, 0.5, 0.7].map((t) => (
            <span key={t} className={`absolute -translate-x-1/2 ${t === 0.1 ? 'text-broadcast-gold' : ''}`} style={{ left: pos(t) }}>{t}</span>
          ))}
        </span>
        <span className="text-right">r · n</span>
        <span className="text-right">Verdict</span>
      </div>
      {d.metrics.map((m) => (
        <div key={m.key} className="grid grid-cols-[minmax(0,15rem)_minmax(0,1fr)_5.5rem_4.5rem] items-center gap-x-5 border-b border-divider py-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-text">{m.label}</div>
            <div className="truncate text-[11px] text-text-faint">{m.source}</div>
          </div>
          <Whisker m={m} />
          <div className="tabular text-right text-[13px] text-text-muted">
            <div className="font-bold text-text">{m.r !== null ? `${m.r >= 0 ? '+' : ''}${m.r.toFixed(2)}` : '—'}</div>
            <div className="text-[11px] text-text-faint">{m.n.toLocaleString()}</div>
          </div>
          <div className="text-right">
            <span className={`px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] ${VERDICT_STYLE[m.verdict]}`} title={m.implication}>{m.verdict}</span>
          </div>
        </div>
      ))}
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-text-faint">
        <span><span className="mr-1.5 inline-block size-2 rotate-45 bg-pitch-green align-middle" />persistent</span>
        <span><span className="mr-1.5 inline-block size-2 rotate-45 bg-broadcast-gold align-middle" />unclear</span>
        <span><span className="mr-1.5 inline-block size-2 rotate-45 bg-alert-red align-middle" />does not carry</span>
        <span><span className="mr-1.5 inline-block h-3 w-px bg-broadcast-gold align-middle" />the 0.10 line</span>
      </div>

      <div className="mb-1 mt-10 text-[13px] font-bold uppercase tracking-[0.1em] text-text-faint">What a two-match streak is worth</div>
      <p className="mb-4 max-w-3xl text-sm text-text-muted">
        Next-match output against a flat season rate that already contains the streak, over {d.streak_pairs.toLocaleString()} player-matches. 1.00 means the rate already knew.
        The projection adds the share in the last column, down from a flat {Math.round(d.default_fraction * 100)}% before this was measured.
      </p>
      {d.streaks.map((r) => (
        <div key={`${r.signal}-${r.direction}`} className="grid grid-cols-[minmax(0,15rem)_minmax(0,1fr)_5.5rem_5.5rem] items-center gap-x-5 border-b border-divider py-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-text">{r.signal.replace(/_/g, ' ').toLowerCase()} · {r.direction.toLowerCase()}</div>
            <div className="truncate text-[11px] text-text-faint" title={r.streak}>{r.streak}</div>
          </div>
          <Ratio row={r} />
          <div className="tabular text-right text-[13px]">
            <div className="font-bold text-text">{r.ratio !== null ? r.ratio.toFixed(2) : '—'}</div>
            <div className="text-[11px] text-text-faint">{r.ci ? `${r.ci[0].toFixed(2)}-${r.ci[1].toFixed(2)}` : ''} · {r.n.toLocaleString()}</div>
          </div>
          <div className="tabular text-right text-[13px] font-bold text-broadcast-gold">{r.direction === 'NEGATIVE' ? '-' : '+'}{Math.round(r.applied_fraction * 100)}%</div>
        </div>
      ))}
      <p className="mt-4 max-w-3xl text-[12px] leading-relaxed text-text-faint">{d.method}</p>
    </div>
  )
}
