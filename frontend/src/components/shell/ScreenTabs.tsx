import { useState } from 'react'

/** A screen split into a few named tabs, each saying in one line what it is for (2026-11-27, the manager: "info arranged
 * in a haphazard way"). The chosen tab is remembered per screen for the session. */
export interface ScreenTab<K extends string> { key: K; label: string; note?: string; blurb: string }

export function useScreenTab<K extends string>(screen: string, fallback: K, keys: readonly K[]): [K, (k: K) => void] {
  const read = (): K => {
    try {
      const v = sessionStorage.getItem(`tab:${screen}`) as K | null
      return v && keys.includes(v) ? v : fallback
    } catch {
      return fallback
    }
  }
  const [tab, setTab] = useState<K>(read)
  const set = (k: K) => {
    setTab(k)
    try { sessionStorage.setItem(`tab:${screen}`, k) } catch { /* storage unavailable */ }
  }
  return [tab, set]
}

export function ScreenTabs<K extends string>({ tabs, active, onChange }: { tabs: ScreenTab<K>[]; active: K; onChange: (k: K) => void }) {
  return (
    <>
      <nav className="bare -mb-4 flex flex-wrap items-end gap-2 border-b-[3px] border-ink" aria-label="Sections">
        {tabs.map((t, i) => (
          <button key={t.key} type="button" onClick={() => onChange(t.key)}
            className={`relative -mb-[3px] border-[3px] border-b-0 px-6 pb-2.5 pt-2 text-left transition-transform ${
              active === t.key ? 'border-ink bg-ink text-paper' : 'border-ink/25 bg-paper text-text-muted hover:-translate-y-1 hover:border-ink hover:text-ink'}`}>
            <span className={`absolute -top-3 left-3 font-display text-[13px] font-black ${active === t.key ? 'text-spot' : 'text-text-faint'}`}>{String(i + 1).padStart(2, '0')}</span>
            <span className="block font-display text-[1.6rem] font-black uppercase leading-none">{t.label}</span>
            {t.note && <span className={`voice block text-[15px] ${active === t.key ? 'text-paper/70' : 'text-text-faint'}`}>{t.note}</span>}
          </button>
        ))}
      </nav>
      <p className="bare voice -mt-3 px-1 text-[16px] text-text-muted">{tabs.find((t) => t.key === active)?.blurb}</p>
    </>
  )
}
