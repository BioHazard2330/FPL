import Chart from 'react-apexcharts'
import { Skeleton } from '@/components/ui/skeleton'
import { Masthead } from '@/components/shell/Masthead'
import { fetchLiveSnapshot } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

function str(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

const CLASS_COLOR: Record<string, string> = {
  FIT: 'text-pitch-green',
  'FIT BUT MONITORED': 'text-broadcast-gold',
  DOUBTFUL: 'text-broadcast-gold',
  'LIKELY UNAVAILABLE': 'text-alert-red',
  'CONFIRMED UNAVAILABLE': 'text-alert-red',
}

export function LiveScreen() {
  const state = useFetch(fetchLiveSnapshot, [])

  if (state.status === 'loading') {
    return (
      <div className="space-y-3 p-10">
        <div className="font-mono text-[11px] uppercase tracking-[0.15em] text-text-faint">Loading live state</div>
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (state.status === 'error') {
    return <div className="bg-alert-red p-6 font-semibold text-alert-red-ink">Can't reach the live-state file ({state.error.message}).</div>
  }

  const p = state.data
  const isLive = p.gw?.state === 'LIVE'
  const matches = p.active_matches ?? []
  const events = p.match_events ?? []
  const changes = p.recent_changes ?? []
  const rank = p.rank as { estimated_rank?: number; precision?: string; is_current?: boolean } | null
  const squad = p.squad ?? []
  const starting = squad.filter((s) => s.slot === 'starting')
  const bench = squad.filter((s) => s.slot === 'bench')
  const squadXp = starting.reduce((sum, s) => sum + (s.xp ?? 0), 0)
  const charts = p.charts

  return (
    <div className="pb-16">
      <Masthead edition={isLive ? 'Live Wire · ● LIVE' : 'Live Wire'} title={`GW${p.event ?? '?'} · ${p.gw?.state ?? 'No live window'}`} />

      {/* status strip - dynamic-island-style, real fields only */}
      <div className="flex flex-wrap items-center gap-6 border-b-2 border-divider px-10 py-5">
        <div className="flex items-center gap-2">
          <span className={`size-2.5 rounded-full ${isLive ? 'animate-pulse-live bg-alert-red' : 'bg-text-faint'}`} />
          <span className="text-sm font-bold uppercase tracking-wide text-text">{isLive ? 'Live' : 'No live window'}</span>
        </div>
        {rank?.estimated_rank && (
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Estimated rank</span>
            <div className={`tabular text-lg font-bold ${rank.is_current ? 'text-pitch-green' : 'text-text-faint'}`}>
              ~{rank.estimated_rank.toLocaleString()}
              {!rank.is_current && <span className="ml-1 text-xs font-normal">(not current)</span>}
            </div>
          </div>
        )}
        {matches.length > 0 && (
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wide text-text-faint">Live matches</span>
            <div className="tabular text-lg font-bold text-alert-red">{matches.length}</div>
          </div>
        )}
      </div>

      {matches.length === 0 && (
        <div className="px-10 pt-8 text-sm text-text-muted">No match is genuinely live right now — the strip above fills in during a live window.</div>
      )}

      {/* LIVE SQUAD IMPACT - real per-player current/projected state, always shown (not gated on a live match) */}
      {squad.length > 0 && (
        <div className="border-t-2 border-divider px-10 py-8">
          <div className="mb-1 flex items-baseline gap-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Live squad impact</span>
            <span className="tabular font-display text-2xl font-bold text-pitch-green">{squadXp.toFixed(1)} xP</span>
            <span className="text-[11px] text-text-faint">starting XI, live-projected</span>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-px bg-divider md:grid-cols-2">
            <div className="bg-void px-0 py-2">
              <div className="px-2 pb-2 text-[10px] font-bold uppercase tracking-wide text-text-faint">Starting XI</div>
              <div className="divide-y divide-divider">
                {starting.map((s) => (
                  <div key={s.player_id} className="flex items-center gap-3 px-2 py-2 text-sm">
                    {s.is_captain && <span className="flex size-4 shrink-0 items-center justify-center bg-broadcast-gold text-[9px] font-bold text-broadcast-gold-ink">C</span>}
                    {s.is_vice && <span className="flex size-4 shrink-0 items-center justify-center bg-raised text-[9px] font-bold text-text">V</span>}
                    <span className="font-bold text-text">{s.web_name}</span>
                    <span className="bg-raised px-1.5 py-0.5 text-[9px] font-bold text-text-muted">{s.position}</span>
                    <span className={`text-[10px] font-bold uppercase ${CLASS_COLOR[s.classification ?? ''] ?? 'text-text-faint'}`}>{s.classification}</span>
                    <span className="tabular ml-auto font-semibold text-pitch-green">{s.xp !== null ? `${s.xp.toFixed(1)} xP` : '—'}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="bg-void px-0 py-2">
              <div className="px-2 pb-2 text-[10px] font-bold uppercase tracking-wide text-text-faint">Bench</div>
              <div className="divide-y divide-divider">
                {bench.map((s) => (
                  <div key={s.player_id} className="flex items-center gap-3 px-2 py-2 text-sm opacity-70">
                    <span className="font-bold text-text">{s.web_name}</span>
                    <span className="bg-raised px-1.5 py-0.5 text-[9px] font-bold text-text-muted">{s.position}</span>
                    <span className={`text-[10px] font-bold uppercase ${CLASS_COLOR[s.classification ?? ''] ?? 'text-text-faint'}`}>{s.classification}</span>
                    <span className="tabular ml-auto font-semibold text-text-muted">{s.xp !== null ? `${s.xp.toFixed(1)} xP` : '—'}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SEASON CHARTS - real rank trajectory + cumulative points, ApexCharts */}
      {charts && (charts.rank.events.length > 1 || charts.cumulative_points.events.length > 1) && (
        <div className="grid grid-cols-1 gap-px bg-divider border-t-2 border-divider lg:grid-cols-2">
          {charts.rank.events.length > 1 && (
            <div className="bg-void px-10 py-8">
              <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Overall rank trajectory</div>
              <Chart
                type="area"
                height={260}
                options={{
                  chart: { type: 'area', toolbar: { show: false }, background: 'transparent', foreColor: 'var(--text-muted)' },
                  stroke: { width: 3, curve: 'smooth' },
                  fill: { type: 'gradient', gradient: { opacityFrom: 0.35, opacityTo: 0 } },
                  colors: ['var(--pitch-green)'],
                  grid: { borderColor: 'var(--divider)' },
                  xaxis: { categories: charts.rank.events.map((e) => `GW${e}`) },
                  yaxis: { reversed: true, labels: { formatter: (v: number) => v >= 1000 ? `${Math.round(v / 1000)}k` : `${Math.round(v)}` } },
                  dataLabels: { enabled: false },
                  tooltip: { theme: 'dark' },
                }}
                series={[{ name: 'Overall rank', data: charts.rank.values }]}
              />
            </div>
          )}
          {charts.cumulative_points.events.length > 1 && (
            <div className="bg-void px-10 py-8">
              <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Cumulative points</div>
              <Chart
                type="area"
                height={260}
                options={{
                  chart: { type: 'area', toolbar: { show: false }, background: 'transparent', foreColor: 'var(--text-muted)' },
                  stroke: { width: 3, curve: 'smooth' },
                  fill: { type: 'gradient', gradient: { opacityFrom: 0.35, opacityTo: 0 } },
                  colors: ['var(--broadcast-blue)'],
                  grid: { borderColor: 'var(--divider)' },
                  xaxis: { categories: charts.cumulative_points.events.map((e) => `GW${e}`) },
                  yaxis: {},
                  dataLabels: { enabled: false },
                  tooltip: { theme: 'dark' },
                }}
                series={[{ name: 'Cumulative points', data: charts.cumulative_points.values }]}
              />
            </div>
          )}
          {charts.captain_contribution.events.length > 1 && (
            <div className="bg-void px-10 py-8 lg:col-span-2">
              <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Captain contribution per GW</div>
              <Chart
                type="bar"
                height={220}
                options={{
                  chart: { type: 'bar', toolbar: { show: false }, background: 'transparent', foreColor: 'var(--text-muted)' },
                  plotOptions: { bar: { columnWidth: '45%', borderRadius: 0 } },
                  colors: ['var(--broadcast-gold)'],
                  grid: { borderColor: 'var(--divider)' },
                  xaxis: { categories: charts.captain_contribution.events.map((e) => `GW${e}`) },
                  dataLabels: { enabled: false },
                  tooltip: { theme: 'dark' },
                }}
                series={[{ name: 'Captain points', data: charts.captain_contribution.values }]}
              />
            </div>
          )}
        </div>
      )}

      {matches.length > 0 && (
        <div className="px-10 pt-6 text-sm text-text-muted">
          {matches.length} real live match{matches.length === 1 ? '' : 'es'} right now - full match-centre
          composition (score/momentum/shot map) not yet ported to this screen; open the{' '}
          <a href="/dashboard.html#screen-live" className="text-broadcast-blue underline">
            old dashboard's Live Match Centre
          </a>{' '}
          for the complete real view.
        </div>
      )}

      {/* real timeline rail - match events + recent changes merged chronologically by feed */}
      <div className="grid grid-cols-1 gap-px bg-divider lg:grid-cols-2">
        {events.length > 0 && (
          <div className="bg-void px-10 py-8">
            <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Match events</div>
            <div className="space-y-0">
              {events.slice(0, 20).map((e, i) => (
                <div key={i} className="flex gap-4 border-l-2 border-divider py-2 pl-4">
                  <span className="tabular w-10 shrink-0 text-xs font-bold text-text-faint">{str(e.minute)}&prime;</span>
                  <div>
                    <div className="text-sm font-bold text-text">{str(e.event_type)}</div>
                    <div className="text-xs text-text-muted">{str(e.description ?? e.web_name)}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {changes.length > 0 && (
          <div className="bg-void px-10 py-8">
            <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">Recent changes</div>
            <div className="space-y-0">
              {changes.slice(0, 15).map((c, i) => (
                <div key={i} className="border-l-2 border-broadcast-gold/40 py-2 pl-4">
                  <div className="text-sm font-bold text-text">{str(c.event_type)}</div>
                  <div className="text-xs text-text-muted">{str(c.old_value)} &rarr; {str(c.new_value)}</div>
                  <div className="text-[10px] text-text-faint">{str(c.detected_at)}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
