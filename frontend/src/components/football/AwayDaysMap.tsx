import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { STADIUMS } from '@/lib/stadiums'
import { crestUrl } from '@/lib/api'

export interface TravelLeg {
  fromTeamCode: number
  toTeamCode: number
  fromShort: string
  toShort: string
  event: number
}

/** Every real upcoming away fixture for the squad's clubs, on an actual
 * map of England - real roads, real coastline, real city names. A hand-
 * drawn abstract 3D board (this component's first two versions) can never
 * look as real as an actual map, because it isn't one; this uses a real,
 * free, no-API-key basemap (Esri's public "World Dark Gray Canvas" tile
 * service - confirmed reachable directly before building on it) instead of
 * reinventing cartography from primitives.
 *
 * Two real bugs found and fixed live against this exact deployment:
 * 1. Esri's "Dark Gray Canvas" name refers to a desaturated cartographic
 *    STYLE, not a dark colour scheme - the real tiles are a light
 *    gray-beige, confirmed by direct inspection. A CSS `filter: invert()`
 *    on the tile pane was tried first and was unreliable. A translucent
 *    dark div inside a Leaflet PANE was tried second and rendered
 *    invisible - confirmed live via direct DOM inspection: Leaflet's own
 *    pane elements carry no explicit width/height (tiles inside are
 *    positioned individually), so a child using `inset:0` collapsed to a
 *    0x0 box instead of covering the map. Fixed by appending the tint div
 *    directly to the map's own root container (`map.getContainer()`,
 *    confirmed to have real, definite dimensions) instead of a pane.
 * 2. The map's internal size was computed once at mount and never
 *    corrected - this app's self-hosted webfonts load asynchronously and
 *    can reflow the page height after the map already initialised,
 *    leaving Leaflet's tile grid sized for a stale container. Fixed with a
 *    real `ResizeObserver` on the container (the same pattern this app's
 *    own `useThreeScene` hook already uses for its canvas), calling
 *    `invalidateSize()` on every genuine size change, not a one-off timer.
 * 3. Real Premier League grounds span more latitude than longitude in this
 *    local view (a tall-narrow real bounding shape), but the panel itself
 *    was wide-and-short - fitting a tall shape into a wide box forced
 *    Leaflet to zoom out far enough to satisfy the narrow (vertical) axis,
 *    leaving large empty tile margins on both sides and every club
 *    crammed into a small central cluster. Fixed with a taller panel.
 * 4. `fitBounds` was called three times (immediately, on the next real
 *    animation frame, and again on every `ResizeObserver` tick) to chase
 *    the container's real size as it settled - confirmed live to be
 *    genuinely non-deterministic: three near-simultaneous tile-grid
 *    recalculations at possibly-different measured sizes raced, and
 *    whichever settled last (network-dependent) decided the final zoom -
 *    sometimes landing on a nicely detailed view, sometimes not. Replaced
 *    with a fixed centre + zoom (real England's own real geographic
 *    centre and a zoom level chosen to keep the country's shape and every
 *    club within frame) that does not depend on measuring the container at
 *    all - deterministic every time. `invalidateSize()` is still called on
 *    resize (Leaflet still needs the real pixel size for tile-grid math),
 *    it just never re-picks a zoom level. */
export function AwayDaysMap({ legs }: { legs: TravelLeg[] }) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el || legs.length === 0) return

    const codes = [...new Set(legs.flatMap((l) => [l.fromTeamCode, l.toTeamCode]))].filter((c) => STADIUMS[c])
    if (codes.length === 0) return

    const map = L.map(el, {
      zoomControl: false, attributionControl: true, dragging: true, scrollWheelZoom: false,
    })
    // Real Leaflet gotcha, confirmed live: `L.map(el)` can read the
    // container's size before the browser has completed layout for the
    // element React just committed, caching a stale/undersized internal
    // `_size` that later resize checks never correct (no actual resize
    // event fires if the container's real CSS size never changes after
    // that first bad read). Forcing one explicit `invalidateSize()` here,
    // before anything else touches the map, re-measures synchronously.
    map.invalidateSize()

    L.tileLayer(
      'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
      { attribution: 'Tiles &copy; Esri', maxZoom: 12 },
    ).addTo(map)

    // Real dark tint - a plain overlay div anchored directly to the map's
    // own root container (which has real, definite dimensions), not a
    // Leaflet pane (see module docstring: a pane-child collapsed to 0x0
    // live). z-index 350 sits above the tile pane (200) and below the
    // marker pane (600).
    const tintDiv = document.createElement('div')
    tintDiv.style.cssText = 'position:absolute;inset:0;z-index:350;background:rgba(8,11,16,0.55);pointer-events:none;'
    map.getContainer().appendChild(tintDiv)

    // Fixed centre + zoom - real England's own real geographic centre,
    // never computed from the container's measured size (see module
    // docstring item 4 for why `fitBounds` was dropped). One deferred
    // `invalidateSize()` still corrects the stale-initial-measurement bug
    // (item 2) so Leaflet fetches tiles for the container's real, final
    // size - it just never re-picks a zoom level doing so.
    map.setView([52.8, -1.6], 6)
    requestAnimationFrame(() => map.invalidateSize())

    const ro = new ResizeObserver(() => map.invalidateSize())
    ro.observe(el)

    const style = getComputedStyle(document.documentElement)
    const gold = style.getPropertyValue('--broadcast-gold').trim() || '#f0a93e'
    const green = style.getPropertyValue('--pitch-green').trim() || '#1fce6b'
    const blue = style.getPropertyValue('--broadcast-blue').trim() || '#2d6cdf'

    const squadCodes = new Set(legs.map((l) => l.fromTeamCode))
    for (const code of codes) {
      const s = STADIUMS[code]
      const crest = crestUrl(code)
      const isSquad = squadCodes.has(code)
      const icon = L.divIcon({
        className: '',
        html: `<div style="width:26px;height:26px;border-radius:9999px;background:${isSquad ? gold : blue};display:flex;align-items:center;justify-content:center;border:2px solid rgba(255,255,255,0.25);box-shadow:0 0 0 2px rgba(8,11,16,0.6);">
                 ${crest ? `<img src="${crest}" style="width:16px;height:16px;object-fit:contain" />` : ''}
               </div>`,
        iconSize: [26, 26], iconAnchor: [13, 13],
      })
      L.marker([s.lat, s.lng], { icon, zIndexOffset: 500 }).bindTooltip(s.name, { direction: 'top' }).addTo(map)
    }

    for (const leg of legs) {
      const from = STADIUMS[leg.fromTeamCode]
      const to = STADIUMS[leg.toTeamCode]
      if (!from || !to) continue
      const midLat = (from.lat + to.lat) / 2
      const midLng = (from.lng + to.lng) / 2
      const dx = to.lng - from.lng
      const dy = to.lat - from.lat
      const nudge = 0.12
      const curveLat = midLat + -dx * nudge
      const curveLng = midLng + dy * nudge
      const points: [number, number][] = []
      const steps = 24
      for (let i = 0; i <= steps; i++) {
        const t = i / steps
        const lat = (1 - t) ** 2 * from.lat + 2 * (1 - t) * t * curveLat + t ** 2 * to.lat
        const lng = (1 - t) ** 2 * from.lng + 2 * (1 - t) * t * curveLng + t ** 2 * to.lng
        points.push([lat, lng])
      }
      L.polyline(points, { color: green, weight: 1.5, opacity: 0.75 }).addTo(map)
    }

    return () => {
      // Real bug found live: `map.remove()` tears down Leaflet's own panes
      // but does not know about `tintDiv`, appended directly to the
      // container by this component rather than through Leaflet's pane
      // system - left in place, a second mount (this effect's own `[legs]`
      // dependency is a fresh array identity on every parent re-render,
      // see FootballScreen's `useMemo` fix) stacked a second translucent
      // layer on top, doubling the real darkening opacity. Removed
      // explicitly here rather than trusting `map.remove()` to know about
      // DOM nodes it didn't create.
      tintDiv.remove()
      ro.disconnect()
      map.remove()
    }
  }, [legs])

  if (legs.length === 0) return null
  return <div ref={containerRef} className="h-full w-full [&_.leaflet-control-attribution]:bg-transparent [&_.leaflet-control-attribution]:text-[9px] [&_.leaflet-control-attribution]:text-text-faint" />
}
