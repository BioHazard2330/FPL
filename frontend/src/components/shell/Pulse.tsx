import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** THE PULSE (`/api/pulse`, every 15 seconds): what the system has taken in or changed its mind about, newest first. In
 * the header the latest line scrolls through with a beating dot; click for the full day. Every line is a row some part
 * of the system wrote - a flag, a price, a lineup, a headline it read, a cycle it ran, a plan it rebuilt, a size it
 * refitted. */
interface Item { at: string; kind: string; text: string; player_id: number | null; yours: boolean; high: boolean }
interface Payload { status: string; items: Item[]; last_cycle: string | null; tuning: Record<string, number | string | null> | null; counts: { day: number; yours: number } }

const KIND_TONE: Record<string, string> = {
  plan: 'bg-ink text-paper', learned: 'bg-pitch-green text-pitch-green-ink', fitness: 'bg-alert-red text-alert-red-ink',
  'team news': 'bg-broadcast-blue text-broadcast-blue-ink', price: 'bg-broadcast-gold text-broadcast-gold-ink', read: 'bg-raised text-text',
  cycle: 'bg-raised text-text-faint', 'deadline watch': 'bg-spot text-ink',
}

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 90) return `${Math.round(s)}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  return `${Math.round(s / 3600)}h`
}

export function Pulse() {
  const st = useFetch(() => getJson<Payload>('/api/pulse'), [], 15000)
  const [open, setOpen] = useState(false)
  const [i, setI] = useState(0)
  const [, tick] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => { setI((x) => x + 1); tick((x) => x + 1) }, 5000)
    return () => window.clearInterval(t)
  }, [])
  if (st.status !== 'ready' || st.data.status !== 'ok' || !st.data.items.length) return null
  const d = st.data
  const lead = d.items.filter((x) => x.kind !== 'cycle').slice(0, 8)
  const cur = lead.length ? lead[i % lead.length] : d.items[0]
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title="Everything the system took in or changed in the last day"
        className="hidden max-w-[30rem] items-center gap-2 border-2 border-ink bg-paper px-2 py-1 text-left hover:bg-raised xl:flex">
        <span className="relative flex size-2.5 shrink-0">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-pitch-green opacity-60" />
          <span className="relative inline-flex size-2.5 rounded-full bg-pitch-green" />
        </span>
        <span className="font-display text-[12px] font-black uppercase tracking-[0.1em] text-text">Pulse</span>
        <span key={cur.at + cur.text} className="data-in min-w-0 truncate text-[12.5px] text-text-muted">
          <span className="font-bold text-text-faint">{ago(cur.at)}</span> · {cur.text}
        </span>
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="border-l-2 border-ink bg-paper p-0 sm:max-w-lg">
          <SheetHeader className="border-b-2 border-ink p-5">
            <SheetTitle className="font-display text-3xl font-black uppercase">The pulse</SheetTitle>
            <p className="voice text-[15px] text-text-muted">
              {d.counts.day} things in the last day, {d.counts.yours} about your players.
              {d.last_cycle && <> Last background cycle {ago(d.last_cycle)} ago.</>}
            </p>
            {d.tuning && (
              <div className="mt-2 grid grid-cols-5 border-2 border-ink text-center">
                {([['track', 'Track'], ['rot', 'Rotation'], ['form', 'Form'], ['eye', 'Your eye'], ['evidence_k', 'Thin record']] as const).map(([k, l]) => (
                  <div key={k} className="border-r border-ink/20 px-1 py-1 last:border-0">
                    <div className="text-[10px] font-bold uppercase tracking-[0.1em] text-text-faint">{l}</div>
                    <div className="tabular font-display text-lg font-black">{d.tuning?.[k] ?? '–'}</div>
                  </div>
                ))}
              </div>
            )}
            {d.tuning && <div className="text-[11.5px] text-text-faint">The sizes the model chose itself from this season's results{d.tuning.fitted_at ? `, refitted ${ago(String(d.tuning.fitted_at))} ago` : ''}.</div>}
          </SheetHeader>
          <div className="h-[calc(100vh-15rem)] overflow-y-auto px-5 py-3">
            {d.items.map((x, k) => (
              <div key={k} className={`grid grid-cols-[3rem_6.5rem_minmax(0,1fr)] items-start gap-2 border-b border-divider py-2 text-[13px] ${x.yours ? 'bg-spot/[0.06]' : ''}`}>
                <span className="tabular pt-0.5 text-text-faint">{ago(x.at)}</span>
                <span className={`truncate px-1.5 py-0.5 text-center text-[10.5px] font-black uppercase ${KIND_TONE[x.kind] ?? 'bg-raised text-text-muted'}`}>{x.kind}</span>
                <span className={`${x.high ? 'font-bold text-text' : 'text-text-muted'}`}>
                  {x.player_id ? <Link to={`/player/${x.player_id}`} onClick={() => setOpen(false)} className="hover:underline">{x.text}</Link> : x.text}
                  {x.yours && <span className="ml-1 text-[11px] font-black text-spot">YOURS</span>}
                </span>
              </div>
            ))}
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
