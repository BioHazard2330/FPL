import { Link } from 'react-router-dom'
import { getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { WeekMoves, type WeekMovesData } from '@/components/field/WeekMoves'

/** The 10k at the last deadline, compact, on Command: what the managers ranked around 10,000 bought and sold. */
export function TenKWeek() {
  const state = useFetch(() => getJson<{ status: string; week?: WeekMovesData | null }>('/api/cohort'), [])
  if (state.status !== 'ready' || !state.data.week) return null
  return (
    <section className="slab px-6 pb-6 pt-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-display text-text">The 10k at the deadline</h2>
        <Link to="/versus" className="text-[12px] font-bold uppercase tracking-[0.12em] text-spot hover:underline">Versus the 10k →</Link>
      </div>
      <div className="mt-3"><WeekMoves d={state.data.week} compact /></div>
    </section>
  )
}
