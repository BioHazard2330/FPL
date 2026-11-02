import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import isles from '@/assets/geo/isles.geo.json'
import { Masthead } from '@/components/shell/Masthead'
import { ScreenError } from '@/components/shell/ScreenStates'
import { WeatherIcon, WEATHER_LABEL, weatherKind } from '@/components/ui/Weather'
import { crestUrl, getJson } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'

/** THE MAP - the gameweek on a map of England: every ground with its crest, each tie drawn as the away side's journey to
 * the home ground (animated, orange where your players are in it), a match badge on the home ground with kickoff or
 * score and the weather, and the ties in kickoff order down the side. Hovering a tie lights its journey. */

interface Club { team_id: number; short: string; name: string; code: number; stadium: string; city: string; lat: number; lon: number; capacity: number | null }
interface Fixture {
  fixture_id: number; kickoff: string | null; home: number; away: number; score: [number, number] | null; started: boolean; finished: boolean
  km: number | null; weather: { forecast_temp: number | null; forecast_precip_prob: number | null; forecast_wind: number | null; forecast_code: number | null } | null
  referee: string | null; ref_yellows_pm: number | null; yours: { player_id: number; name: string; photo_code: number; xp: number | null }[]
}
interface MapPayload { status: string; event: number; events: number[]; clubs: Club[]; fixtures: Fixture[] }

function arc(a: L.LatLng, b: L.LatLng, bend = 0.22, steps = 40): L.LatLng[] {
  const mx = (a.lat + b.lat) / 2, my = (a.lng + b.lng) / 2
  const dx = b.lat - a.lat, dy = b.lng - a.lng
  const cx = mx - dy * bend, cy = my + dx * bend
  const out: L.LatLng[] = []
  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    out.push(L.latLng((1 - t) ** 2 * a.lat + 2 * (1 - t) * t * cx + t * t * b.lat, (1 - t) ** 2 * a.lng + 2 * (1 - t) * t * cy + t * t * b.lng))
  }
  return out
}

const kickLabel = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) : 'TBC')

export function MapScreen() {
  const [params, setParams] = useSearchParams()
  const ev = params.get('event')
  const state = useFetch(() => getJson<MapPayload>(`/api/map${ev ? `?event=${ev}` : ''}`), [ev], 60000)
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layers = useRef<Map<number, L.Polyline>>(new Map())
  const [hover, setHover] = useState<number | null>(null)
  const fitted = useRef(false)

  const data = state.status === 'ready' && state.data.status === 'ok' ? state.data : null
  const clubs = useMemo(() => new Map((data?.clubs ?? []).map((c) => [c.team_id, c])), [data])

  useEffect(() => {
    if (!el.current || map.current) return
    const m = L.map(el.current, {
      zoomControl: false, attributionControl: true, scrollWheelZoom: true, minZoom: 5.5, maxZoom: 11, zoomSnap: 0.25,
      maxBounds: L.latLngBounds([48.5, -11], [61, 6]),
    }).setView([52.7, -1.9], 6.75)
    L.control.zoom({ position: 'bottomright' }).addTo(m)
    m.attributionControl.setPrefix(false).addAttribution('Coastline: Natural Earth')
    L.geoJSON(isles as GeoJSON.FeatureCollection, {
      style: (f) => ({
        color: '#17130e', weight: 1.3, fillColor: f?.properties?.name === 'United Kingdom' ? '#fbf6ea' : '#efe7d5', fillOpacity: 1,
      }),
      interactive: false,
    }).addTo(m)
    map.current = m
    return () => { m.remove(); map.current = null }
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m || !data) return
    const group = L.layerGroup().addTo(m)
    layers.current.clear()
    const homeOf = new Map(data.fixtures.map((f) => [f.home, f]))
    for (const f of data.fixtures) {
      const h = clubs.get(f.home), a = clubs.get(f.away)
      if (!h || !a) continue
      const mine = f.yours.length > 0
      const line = L.polyline(arc(L.latLng(a.lat, a.lon), L.latLng(h.lat, h.lon)), {
        color: mine ? '#ff4614' : '#17130e', weight: mine ? 4 : 2.2, opacity: mine ? 0.95 : 0.45,
        dashArray: '10 10', className: 'map-journey', interactive: true,
      }).addTo(group)
      line.bindTooltip(`${a.short} to ${h.short} · ${f.km} km`, { sticky: true, className: 'map-tip' })
      line.on('mouseover', () => setHover(f.fixture_id))
      line.on('mouseout', () => setHover(null))
      layers.current.set(f.fixture_id, line)
    }
    const markers: { c: Club; marker: L.Marker; leader: L.Polyline }[] = []
    for (const c of data.clubs) {
      const f = homeOf.get(c.team_id)
      const crest = crestUrl(c.code)
      const badge = f
        ? `<div class="map-badge ${f.yours.length ? 'mine' : ''}">${f.score && f.started ? `${f.score[0]}–${f.score[1]}${f.finished ? ' FT' : ''}` : kickLabel(f.kickoff)}</div>`
        : ''
      const icon = L.divIcon({
        className: 'map-club',
        html: `<div class="map-crest">${crest ? `<img src="${crest}" alt="" />` : c.short}</div>${badge}`,
        iconSize: [38, 38], iconAnchor: [19, 19],
      })
      L.circleMarker([c.lat, c.lon], { radius: 3, color: '#17130e', weight: 1, fillColor: '#17130e', fillOpacity: 1, interactive: false }).addTo(group)
      const leader = L.polyline([[c.lat, c.lon], [c.lat, c.lon]], { color: '#17130e', weight: 1.2, opacity: 0.7, interactive: false }).addTo(group)
      const marker = L.marker([c.lat, c.lon], { icon }).addTo(group)
      marker.bindTooltip(`<b>${c.stadium}</b><br/>${c.city}${c.capacity ? ` · ${c.capacity.toLocaleString()}` : ''}`, { direction: 'top', offset: [0, -16], className: 'map-tip' })
      markers.push({ c, marker, leader })
    }
    // Grounds closer than a crest's width on screen (London, Merseyside, Manchester) are spread on a ring around their centre
    // with a leader line to the real ground, recomputed at every zoom.
    const layout = () => {
      const pts = markers.map((x) => m.latLngToLayerPoint([x.c.lat, x.c.lon]))
      const used = new Set<number>()
      for (let i = 0; i < markers.length; i++) {
        if (used.has(i)) continue
        const group_ = [i]
        for (let j = i + 1; j < markers.length; j++) {
          if (!used.has(j) && group_.some((k) => pts[k].distanceTo(pts[j]) < 44)) group_.push(j)
        }
        group_.forEach((k) => used.add(k))
        if (group_.length === 1) {
          markers[i].marker.setLatLng([markers[i].c.lat, markers[i].c.lon])
          markers[i].leader.setLatLngs([[markers[i].c.lat, markers[i].c.lon], [markers[i].c.lat, markers[i].c.lon]])
          continue
        }
        const cx = group_.reduce((n, k) => n + pts[k].x, 0) / group_.length
        const cy = group_.reduce((n, k) => n + pts[k].y, 0) / group_.length
        const r = 30 + group_.length * 9
        const order = [...group_].sort((a, b) => Math.atan2(pts[a].y - cy, pts[a].x - cx) - Math.atan2(pts[b].y - cy, pts[b].x - cx))
        order.forEach((k, n) => {
          const ang = (n / order.length) * Math.PI * 2 - Math.PI / 2
          const at = m.layerPointToLatLng(L.point(cx + Math.cos(ang) * r, cy + Math.sin(ang) * r))
          markers[k].marker.setLatLng(at)
          markers[k].leader.setLatLngs([[markers[k].c.lat, markers[k].c.lon], at])
        })
      }
    }
    if (!fitted.current && data.clubs.length) {
      m.fitBounds(L.latLngBounds(data.clubs.map((c) => [c.lat, c.lon] as [number, number])), { paddingTopLeft: [400, 70], paddingBottomRight: [60, 60] })
      fitted.current = true
    }
    layout()
    m.on('zoomend', layout)
    return () => { m.off('zoomend', layout); group.remove() }
  }, [data, clubs])

  useEffect(() => {
    for (const [id, line] of layers.current) {
      const f = data?.fixtures.find((x) => x.fixture_id === id)
      const mine = (f?.yours.length ?? 0) > 0
      line.setStyle(hover === null
        ? { weight: mine ? 4 : 2.2, opacity: mine ? 0.95 : 0.45 }
        : id === hover ? { weight: 6, opacity: 1 } : { weight: 1.5, opacity: 0.15 })
      if (id === hover) line.bringToFront()
    }
  }, [hover, data])

  if (state.status === 'error') return <ScreenError title="Map unavailable" description="The map payload could not be read." message={state.error.message} />
  const totalKm = data ? data.fixtures.reduce((n, f) => n + (f.km ?? 0), 0) : 0
  const longest = data ? [...data.fixtures].sort((a, b) => (b.km ?? 0) - (a.km ?? 0))[0] : undefined

  return (
    <div>
      <Masthead right={data ? (
        <span className="flex items-center gap-2">
          {data.events.filter((e) => Math.abs(e - data.event) <= 3).map((e) => (
            <button key={e} type="button" onClick={() => setParams((s) => { s.set('event', String(e)); return s })}
              className={`border-2 border-ink px-2 py-0.5 font-display text-[13px] font-black ${e === data.event ? 'bg-ink text-paper' : 'bg-paper text-ink hover:bg-spot'}`}>GW{e}</button>
          ))}
        </span>
      ) : undefined} />
      <section className="no-tab !p-0">
        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_25rem]">
          <div className="relative">
            <div ref={el} className="map-paper h-[calc(100vh-11rem)] min-h-[560px] w-full" />
            {data && (
              <div className="pointer-events-none absolute left-5 top-5 z-[500] border-2 border-ink bg-paper px-5 py-4 shadow-[5px_5px_0_var(--ink)]">
                <div className="font-display text-[12px] font-black uppercase tracking-[0.2em] text-spot">The map</div>
                <div className="font-display text-[2.4rem] font-black uppercase leading-none text-text">Gameweek {data.event}</div>
                <div className="mt-1 text-[12.5px] text-text-muted">
                  {data.fixtures.length} ties · <span className="tabular font-semibold text-text">{totalKm.toLocaleString()}</span> km of away travel
                  {longest && longest.km ? <> · longest {clubs.get(longest.away)?.short} to {clubs.get(longest.home)?.short}, {longest.km} km</> : null}
                </div>
                <div className="mt-2 flex items-center gap-3 text-[11.5px] text-text-muted">
                  <span className="flex items-center gap-1.5"><span className="inline-block h-[3px] w-6 bg-spot" />your players' ties</span>
                  <span className="flex items-center gap-1.5"><span className="inline-block h-[2px] w-6 bg-ink/50" />the rest</span>
                </div>
              </div>
            )}
          </div>
          <aside className="max-h-[calc(100vh-11rem)] min-h-[560px] overflow-y-auto border-l-2 border-ink bg-panel">
            {(data?.fixtures ?? []).map((f) => {
              const h = clubs.get(f.home), a = clubs.get(f.away)
              const kind = weatherKind(f.weather?.forecast_code)
              const live = f.started && !f.finished
              return (
                <div key={f.fixture_id} onMouseEnter={() => setHover(f.fixture_id)} onMouseLeave={() => setHover(null)}
                  className={`border-b-2 border-ink/10 px-5 py-3.5 transition-colors ${hover === f.fixture_id ? 'bg-raised' : ''} ${f.yours.length ? 'border-l-4 border-l-spot' : ''}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 font-display text-[17px] font-black uppercase text-text">
                      {h && <img src={crestUrl(h.code) ?? ''} alt="" className="size-5" onError={(e) => { e.currentTarget.style.display = 'none' }} />}
                      {h?.short}
                      <span className={`tabular mx-1 ${live ? 'text-alert-red' : 'text-text-faint'}`}>{f.score && f.started ? `${f.score[0]}–${f.score[1]}` : 'v'}</span>
                      {a?.short}
                      {a && <img src={crestUrl(a.code) ?? ''} alt="" className="size-5" onError={(e) => { e.currentTarget.style.display = 'none' }} />}
                    </span>
                    <span className="flex items-center gap-1 text-[12px] text-text-muted">
                      {kind && <WeatherIcon code={f.weather?.forecast_code} className="size-6" />}
                      {f.weather?.forecast_temp !== null && f.weather?.forecast_temp !== undefined ? `${Math.round(f.weather.forecast_temp)}°` : ''}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[12px] text-text-faint">
                    {live ? <span className="font-bold text-alert-red">live</span> : f.finished ? 'full time' : kickLabel(f.kickoff)}
                    {' · '}{h?.stadium}{f.km ? ` · ${f.km} km trip` : ''}
                    {kind ? ` · ${WEATHER_LABEL[kind].toLowerCase()}, rain ${Math.round(f.weather?.forecast_precip_prob ?? 0)}%` : ''}
                    {f.referee ? ` · ${f.referee} (${f.ref_yellows_pm?.toFixed(1)} yellows)` : ''}
                  </div>
                  {f.yours.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {f.yours.map((p) => (
                        <Link key={p.player_id} to={`/player/${p.player_id}`} className="border-2 border-ink bg-paper px-1.5 py-0.5 text-[12px] font-bold text-text hover:bg-spot">
                          {p.name}{p.xp !== null ? <span className="tabular ml-1 font-display text-pitch-green">{p.xp.toFixed(1)}</span> : null}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </aside>
        </div>
      </section>
    </div>
  )
}
