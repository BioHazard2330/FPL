import { ComparisonGraphic } from './ComparisonGraphic'
import type { AlternativeBlock, CheckpointBlock, WhyLine } from '@/lib/types'

interface DecisionHeroProps {
  gwLabel: string
  actionWord: string
  alternative: AlternativeBlock | null
  why: WhyLine[]
  freeTransfersValue: string
  bankM: number
  chipsAvailable: string[]
  checkpoint: CheckpointBlock | null
}

/** THE DECISION HERO - one composition, not a 3-column card row (art-
 * direction pass v4, "Command visual composition rebuild"). The gameweek
 * is a real structural layer (a huge ghost numeral behind everything),
 * the verdict is a flat angled broadcast flag, the comparison is a real
 * stat graphic underneath it - all one vertical read, the way a half-time
 * graphics package stacks a headline over its supporting numbers. Flat
 * colour only - no gradient wash, no glow shadow behind the verdict block
 * (DESIGN.md's own "no glow" rule, previously violated here by an
 * `atmosphere-blue` radial-gradient wash and a colored drop-shadow on the
 * verdict block - both removed). */
export function DecisionHero({
  gwLabel, actionWord, alternative, why, freeTransfersValue, bankM, chipsAvailable, checkpoint,
}: DecisionHeroProps) {
  return (
    <section className="relative overflow-hidden bg-void px-10 pb-14 pt-10">
      {/* the gameweek as real typographic architecture, not a corner sticker -
          bleeds off the right edge, sits BEHIND every other layer here */}
      <span className="ghost-watermark pointer-events-none absolute -right-10 -top-6 select-none font-display text-[22rem] font-bold uppercase leading-none">
        {gwLabel}
      </span>

      <div className="relative">
        <div className="font-mono text-[11px] uppercase tracking-[0.25em] text-text-faint">{gwLabel} &middot; The decision</div>

        <div className="verdict-block mt-5 inline-block bg-pitch-green py-5 pl-7 pr-16">
          <h1 className="font-display text-6xl font-bold uppercase leading-[0.88] text-pitch-green-ink md:text-7xl">{actionWord}</h1>
        </div>

        {alternative && (
          <div className="mt-3 text-2xl font-semibold normal-case text-text-faint md:text-3xl">
            not {alternative.label.replace(/^PLAY /i, '').toLowerCase()}
          </div>
        )}

        {why.length > 0 && (
          <div className="mt-6 max-w-xl space-y-2 border-l-2 border-pitch-green/40 pl-4">
            {why.map((w, i) => (
              <p key={i} className="text-sm leading-relaxed text-text-muted">
                {w.tag && <span className={`mr-2 font-bold ${w.tag === 'FRAGILE' ? 'text-broadcast-gold' : 'text-pitch-green'}`}>{w.tag}</span>}
                {w.text}
              </p>
            ))}
          </div>
        )}

        {checkpoint && checkpoint.horizons.length > 0 && (
          <div className="mt-10">
            <ComparisonGraphic checkpoint={checkpoint} />
          </div>
        )}

        <div className="mt-10 flex flex-wrap gap-x-7 gap-y-1.5 border-t-2 border-divider pt-5 font-mono text-[11px] uppercase tracking-wide text-text-faint">
          <span>{freeTransfersValue} free transfer{freeTransfersValue === '1' ? '' : 's'}</span>
          <span>£{bankM.toFixed(1)}m bank</span>
          {chipsAvailable.length > 0 && <span className="text-broadcast-gold">{chipsAvailable.join(' · ')}</span>}
        </div>
      </div>
    </section>
  )
}
