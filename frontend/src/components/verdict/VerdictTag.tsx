import { useEffect, useState } from 'react'
import { LABEL_STYLE } from '@/components/verdict/VerdictCard'
import { getJson } from '@/lib/api'

/** A player's verdict as a small score tag anywhere a player is listed. One shared fetch of `/api/verdicts` for the
 * whole page (a list of a hundred players makes one request, not a hundred), refreshed after five minutes. */
interface Row { player_id: number; score: number | null; label: string; notes: string[]; flags?: { level: string; text: string }[] }
let cache: { at: number; promise: Promise<Map<number, Row>> } | null = null

export function useVerdictMap(): Map<number, Row> | null {
  const [map, setMap] = useState<Map<number, Row> | null>(null)
  useEffect(() => {
    if (!cache || Date.now() - cache.at > 300_000) {
      cache = { at: Date.now(), promise: getJson<{ players: Row[] }>('/api/verdicts').then((d) => new Map(d.players.map((p) => [p.player_id, p]))) }
    }
    let alive = true
    cache.promise.then((m) => alive && setMap(m)).catch(() => undefined)
    return () => { alive = false }
  }, [])
  return map
}

export function VerdictTag({ id, withLabel = false }: { id: number; withLabel?: boolean }) {
  const map = useVerdictMap()
  const v = map?.get(id)
  if (!v) return null
  const red = v.flags?.some((f) => f.level === 'red')
  return (
    <span className={`ml-1 inline-block px-1 align-middle text-[10px] font-black uppercase not-italic leading-tight ${LABEL_STYLE[v.label] ?? ''} ${red ? 'outline outline-2 outline-alert-red' : ''}`}
      title={[`Verdict ${v.score} (${v.label})`, ...v.notes, ...(v.flags ?? []).map((f) => f.text)].join(' · ')}>
      {withLabel ? `${v.label} ${v.score}` : v.score}
    </span>
  )
}
