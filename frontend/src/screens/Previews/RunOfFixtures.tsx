import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { crestUrl } from '@/lib/api'
import type { PreviewsPayload } from '@/lib/types'

type Mode = 'attack' | 'defence'

const BINS = [
  'bg-alert-red text-alert-red-ink',
  'bg-alert-red/60 text-alert-red-ink',
  'bg-raised text-text-muted',
  'bg-pitch-green/70 text-pitch-green-ink',
  'bg-pitch-green text-pitch-green-ink',
]

/** THE RUN OF FIXTURES, as the team model sees it - the official FDR number
 * replaced by what each fixture is expected to produce. Attack: goals the club
 * is expected to score. Defence: the chance it keeps a clean sheet. Cells are
 * coloured by their rank among every cell shown (five equal bands), so colour
 * means "relative to the rest of the league's next six gameweeks", never an
 * absolute grade. Fixtures with stored odds behind them are marked; the rest are
 * the model alone. A blank gameweek is an empty cell, a double has two. */
export function RunOfFixtures({ ticker, mine }: { ticker: NonNullable<PreviewsPayload['ticker']>; mine: Set<number> }) {
  const [mode, setMode] = useState<Mode>('attack')
  const value = (e: { xg_for: number; cs: number }) => (mode === 'attack' ? e.xg_for : e.cs)
  const fmt = (v: number) => (mode === 'attack' ? v.toFixed(1) : `${Math.round(v * 100)}%`)

  const { rows, cuts } = useMemo(() => {
    const all = ticker.rows.flatMap((r) => Object.values(r.events).flatMap((l) => l.map((e) => (mode === 'attack' ? e.xg_for : e.cs))))
    all.sort((a, b) => a - b)
    const q = (p: number) => all[Math.min(all.length - 1, Math.floor(p * all.length))] ?? 0
    const sorted = ticker.rows.slice().sort((a, b) => (mode === 'attack' ? b.xg_for_total - a.xg_for_total : b.cs_total - a.cs_total))
    return { rows: sorted, cuts: [q(0.2), q(0.4), q(0.6), q(0.8)] }
  }, [ticker, mode])
  const bin = (v: number) => cuts.filter((c) => v >= c).length

  return (
    <section className="border-b border-divider px-10 py-7">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl font-bold text-text">The run of fixtures</h2>
          <p className="mt-1 max-w-3xl text-xs text-text-muted">
            The next six gameweeks from the team model, not the official difficulty number.{' '}
            {mode === 'attack' ? 'Goals each club is expected to score.' : 'Chance each club keeps a clean sheet.'} Colour is rank across every cell.
            A dot marks fixtures where stored odds fed the figure; the rest are the model alone.
          </p>
        </div>
        <div className="flex gap-1">
          {(['attack', 'defence'] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`px-2.5 py-1 text-[13px] font-semibold ${mode === m ? 'bg-text text-void' : 'bg-raised text-text-muted hover:text-text'}`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-px bg-divider" style={{ gridTemplateColumns: `13rem repeat(${ticker.events.length}, minmax(0, 1fr)) 4.5rem` }}>
        <div className="bg-void px-2 py-1.5 text-[12px] text-text-faint">Club</div>
        {ticker.events.map((e) => (
          <div key={e} className="bg-void px-2 py-1.5 text-center text-[12px] text-text-faint">GW{e}</div>
        ))}
        <div className="bg-void px-2 py-1.5 text-right text-[12px] text-text-faint">{mode === 'attack' ? 'xG' : 'CS'}</div>
        {rows.map((r) => {
          const crest = crestUrl(r.code)
          return (
            <div key={r.team_id} className="contents">
              <Link to={`/club/${r.team_id}`} className={`flex items-center gap-2 bg-void px-2 py-1 text-sm font-semibold hover:text-pitch-green ${mine.has(r.team_id) ? 'text-text' : 'text-text-muted'}`}>
                {crest && <img src={crest} alt="" className="h-5 w-5" />}
                {r.name}
                {mine.has(r.team_id) && <span className="ml-auto bg-pitch-green px-1 text-[12px] font-bold leading-4 text-pitch-green-ink">yours</span>}
              </Link>
              {ticker.events.map((e) => {
                const list = r.events[String(e)] ?? []
                return (
                  <div key={e} className="flex flex-col gap-px bg-void">
                    {list.length === 0 && <div className="flex h-full min-h-[2rem] items-center justify-center bg-void text-[12px] text-text-faint">blank</div>}
                    {list.map((f, i) => (
                      <div key={i} className={`flex items-center justify-between gap-1 whitespace-nowrap px-1.5 py-1 text-[12px] font-bold ${BINS[bin(value(f))]}`} title={`${f.home ? 'vs' : 'at'} ${f.opponent}: ${f.xg_for.toFixed(2)} for, ${f.xg_against.toFixed(2)} against, clean sheet ${Math.round(f.cs * 100)}%`}>
                        <span className="opacity-80">{f.opponent} {f.home ? 'H' : 'A'}{f.market ? ' ·' : ''}</span>
                        <span className="tabular">{fmt(value(f))}</span>
                      </div>
                    ))}
                  </div>
                )
              })}
              <div className="tabular flex items-center justify-end bg-void px-2 text-sm font-bold text-text">
                {mode === 'attack' ? r.xg_for_total.toFixed(1) : r.cs_total.toFixed(1)}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
