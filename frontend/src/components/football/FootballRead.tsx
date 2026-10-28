import type { FootballReadData, FootballReadLine } from '@/lib/types'

/** THE FOOTBALL READ: a scout's account of the player, line by line, each marked by whether that kind of evidence has
 * held up from one match to the next in the stored history (`models/football_read.py`). A lean is shown only where the
 * line has one; a line that does not carry never leans. */

const WEIGHT: Record<FootballReadLine['weight'], { label: string; tone: string; hint: string }> = {
  carries: { label: 'holds up', tone: 'border-pitch-green/40 text-pitch-green', hint: 'Measured to carry into the next match.' },
  context: { label: 'context', tone: 'border-divider text-text-faint', hint: 'True now; how much it carries is not measured.' },
  noise: { label: "doesn't carry", tone: 'border-broadcast-gold/40 text-broadcast-gold', hint: 'Measured not to carry into the next match.' },
}

const VERDICT_TONE: Record<FootballReadData['verdict']['label'], string> = {
  'backs him': 'text-pitch-green',
  'against him': 'text-alert-red',
  mixed: 'text-broadcast-gold',
}

function Lean({ lean }: { lean: number }) {
  if (lean > 0) return <span className="text-pitch-green" aria-label="for him">▲</span>
  if (lean < 0) return <span className="text-alert-red" aria-label="against him">▼</span>
  return <span className="text-text-faint/60" aria-label="neither">·</span>
}

function Row({ l, dense }: { l: FootballReadLine; dense?: boolean }) {
  const w = WEIGHT[l.weight]
  return (
    <li className={`grid grid-cols-[1rem_minmax(0,1fr)] gap-2 ${dense ? 'py-1' : 'py-2'}`}>
      <span className={`${dense ? 'text-[12px]' : 'text-[13px]'} leading-snug`}><Lean lean={l.lean} /></span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className={`font-semibold text-text ${dense ? 'text-[12.5px]' : 'text-[14px]'}`}>{l.topic}</span>
          <span className={`rounded-full border px-1.5 text-[10.5px] font-semibold ${w.tone}`} title={w.hint}>{w.label}</span>
        </div>
        <p className={`text-text-muted ${dense ? 'text-[12px] leading-snug' : 'text-[13.5px] leading-relaxed'}`}>{l.text}</p>
      </div>
    </li>
  )
}

export function FootballRead({ r }: { r: FootballReadData }) {
  return (
    <div className="border-b border-divider px-10 py-8">
      <div className="mb-1 flex flex-wrap items-baseline gap-3">
        <span className="font-display text-2xl font-bold text-text">The football read</span>
        <span className="text-[13px] text-text-faint">what the stored evidence says about him, and which of it has held up from match to match</span>
      </div>
      <p className={`mb-4 mt-3 text-[16px] font-semibold ${VERDICT_TONE[r.verdict.label]}`}>{r.verdict.text}</p>
      <ul className="grid gap-x-10 divide-y divide-divider/60 md:grid-cols-2 md:divide-y-0">
        {r.lines.map((l) => <Row key={l.topic} l={l} />)}
      </ul>
      <p className="mt-4 text-[12px] text-text-faint">
        A read beside the projection, not part of it. "Holds up": chance volume, minutes and fixtures, measured to carry into the next match.
        "Doesn't carry": finishing above or below the chances and hot or cold spells, measured not to.
      </p>
    </div>
  )
}

/** One line on a transfer card, with the full read a click away. */
export function FootballReadInline({ r, open }: { r: FootballReadData; open?: boolean }) {
  return (
    <details className="group mt-3 rounded-md bg-void/40 px-3 py-2" open={open}>
      <summary className="cursor-pointer list-none text-[12.5px] leading-snug">
        <span className="mr-1.5 text-text-faint group-open:hidden">▸</span>
        <span className="mr-1.5 hidden text-text-faint group-open:inline">▾</span>
        <span className={`font-semibold ${VERDICT_TONE[r.verdict.label]}`}>{r.verdict.text}</span>
      </summary>
      <ul className="mt-1.5">
        {r.lines.map((l) => <Row key={l.topic} l={l} dense />)}
      </ul>
    </details>
  )
}
