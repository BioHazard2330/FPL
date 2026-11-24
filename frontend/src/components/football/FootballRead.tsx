import type { FootballReadData, FootballReadLine } from '@/lib/types'
import { Note } from '@/components/ui/Info'

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

function Tile({ l }: { l: FootballReadLine }) {
  const w = WEIGHT[l.weight]
  const edge = l.lean > 0 ? 'bg-pitch-green' : l.lean < 0 ? 'bg-alert-red' : 'bg-text-faint/40'
  return (
    <li className="group relative flex min-w-0 flex-col border-2 border-ink bg-paper" title={l.text}>
      <span className={`h-1.5 ${edge}`} />
      <div className="flex items-center justify-between gap-2 px-3 pt-2">
        <span className="flex min-w-0 items-center gap-1.5 font-display text-[15px] font-black uppercase leading-none text-text">
          <Lean lean={l.lean} /><span className="truncate">{l.topic}</span>
        </span>
        <span className={`shrink-0 border px-1.5 text-[10px] font-black uppercase ${w.tone}`} title={w.hint}>{w.label}</span>
      </div>
      <div className="px-3 pb-2.5 pt-1"><p className="line-clamp-3 text-[12.5px] leading-snug text-text-muted group-hover:line-clamp-none">{l.text}</p></div>
    </li>
  )
}

export function FootballRead({ r }: { r: FootballReadData }) {
  const forHim = r.lines.filter((l) => l.lean > 0).length
  const against = r.lines.filter((l) => l.lean < 0).length
  const held = r.lines.filter((l) => l.weight === 'carries')
  const heldFor = held.filter((l) => l.lean > 0).length, heldAgainst = held.filter((l) => l.lean < 0).length
  return (
    <div className="border-b border-divider px-10 py-8">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-display text-2xl font-bold text-text">The football read</h2>
          <p className={`voice mt-1 text-[18px] ${VERDICT_TONE[r.verdict.label]}`}>{r.verdict.text}</p>
        </div>
        <div className="flex border-2 border-ink text-center">
          <div className="bg-ink px-4 py-1.5 text-paper">
            <div className="font-display text-[11px] font-black uppercase tracking-[0.14em] text-paper/60">Read</div>
            <div className={`font-display text-xl font-black uppercase leading-none ${r.verdict.label === 'backs him' ? 'text-pitch-green' : r.verdict.label === 'against him' ? 'text-alert-red' : 'text-broadcast-gold'}`}>{r.verdict.label}</div>
          </div>
          <div className="border-l-2 border-ink px-4 py-1.5">
            <div className="text-[11px] font-black uppercase tracking-[0.14em] text-text-faint">For / against</div>
            <div className="tabular font-display text-xl font-black leading-none"><span className="text-pitch-green">{forHim}</span> <span className="text-text-faint">/</span> <span className="text-alert-red">{against}</span></div>
          </div>
          <div className="border-l-2 border-ink px-4 py-1.5" title="Only lines measured to carry into the next match">
            <div className="text-[11px] font-black uppercase tracking-[0.14em] text-text-faint">That hold up</div>
            <div className="tabular font-display text-xl font-black leading-none"><span className="text-pitch-green">{heldFor}</span> <span className="text-text-faint">/</span> <span className="text-alert-red">{heldAgainst}</span></div>
          </div>
        </div>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {r.lines.map((l) => <Tile key={l.topic} l={l} />)}
      </ul>
      <Note>
        A read beside the projection, not part of it. "Holds up": chance volume, minutes and fixtures, measured to carry into the next match.
        "Doesn't carry": finishing above or below the chances and hot or cold spells, measured not to. Hover a tile for its full line.
      </Note>
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
