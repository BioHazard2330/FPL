import ThreeGlobe from 'three-globe'
import * as THREE from 'three'
import { useThreeScene } from '@/lib/three/useThreeScene'
import { STADIUMS } from '@/lib/stadiums'

export interface TravelLeg {
  fromTeamCode: number
  toTeamCode: number
  fromShort: string
  toShort: string
  event: number
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'

/** Every real upcoming away fixture for the squad's clubs, as real flight
 * arcs between real stadium coordinates on an actual 3D globe. Every
 * Premier League ground sits within a few hundred kilometres of every
 * other - a full-earth view would show 20 indistinguishable dots, so the
 * camera frames England specifically rather than the whole planet. No
 * texture image: the globe material is one flat colour from this app's own
 * palette plus real lat/long graticule lines, matching the flat/no-glow
 * design system rather than a photorealistic earth. */
export function TravelGlobe({ legs }: { legs: TravelLeg[] }) {
  const canvasRef = useThreeScene((_canvas, renderer) => {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 2000)

    const globe = new ThreeGlobe()
      .showGlobe(true)
      .showGraticules(true)
      .globeMaterial(
        new THREE.MeshStandardMaterial({
          color: cssVar('--panel'), transparent: true, opacity: 0.92, roughness: 0.9,
        }),
      )
      .showAtmosphere(true)
      .atmosphereColor(cssVar('--pitch-green'))
      .atmosphereAltitude(0.12)
      .arcsData(legs)
      .arcStartLat((d: object) => STADIUMS[(d as TravelLeg).fromTeamCode]?.lat ?? 0)
      .arcStartLng((d: object) => STADIUMS[(d as TravelLeg).fromTeamCode]?.lng ?? 0)
      .arcEndLat((d: object) => STADIUMS[(d as TravelLeg).toTeamCode]?.lat ?? 0)
      .arcEndLng((d: object) => STADIUMS[(d as TravelLeg).toTeamCode]?.lng ?? 0)
      .arcColor(() => cssVar('--broadcast-gold'))
      .arcStroke(0.35)
      .arcAltitude(0.15)
      .arcDashLength(0.4)
      .arcDashGap(0.2)
      .arcDashAnimateTime(2200)
      .pointsData(
        // Real stadium markers - only the ones this squad's actual travel
        // legs touch, never every ground in the league.
        [...new Set(legs.flatMap((l) => [l.fromTeamCode, l.toTeamCode]))]
          .filter((code) => STADIUMS[code])
          .map((code) => ({ code })),
      )
      .pointLat((d: object) => STADIUMS[(d as { code: number }).code]?.lat ?? 0)
      .pointLng((d: object) => STADIUMS[(d as { code: number }).code]?.lng ?? 0)
      .pointColor(() => cssVar('--broadcast-blue'))
      .pointAltitude(0.01)
      .pointRadius(0.35)

    scene.add(globe)
    scene.add(new THREE.AmbientLight(0xffffff, 0.9))
    const key = new THREE.DirectionalLight(0xffffff, 0.6)
    key.position.set(1, 1, 1)
    scene.add(key)

    // Frame England specifically, tightly - real PL grounds span barely 5
    // degrees of lat/long, so even a "zoomed to England" framing at a
    // normal globe-viewing distance still renders every ground as one
    // indistinguishable point. Real bug caught live: the first pass used
    // altitude 2.05 (a normal "here's the country" distance) and every arc
    // collapsed into a single dot - pulled in to 1.12 (close enough that
    // the real curvature of individual arcs between neighbouring cities is
    // actually visible) at the cost of the globe itself filling most of the
    // frame, which is the honest tradeoff for a league whose whole
    // footprint is one small island.
    const englandLat = 52.8
    const englandLng = -1.5
    const cam = globe.getCoords(englandLat, englandLng, 1.12)
    camera.position.set(cam.x, cam.y, cam.z)
    camera.lookAt(0, 0, 0)

    return {
      render: (width, height) => {
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        globe.rotation.y += 0.0006
        renderer.render(scene, camera)
      },
      dispose: () => {
        scene.traverse((obj) => {
          if (obj instanceof THREE.Mesh) {
            obj.geometry?.dispose()
            const mat = obj.material as THREE.Material | THREE.Material[]
            if (Array.isArray(mat)) mat.forEach((m) => m.dispose())
            else mat?.dispose()
          }
        })
      },
    }
  }, [legs])

  if (legs.length === 0) return null
  return <canvas ref={canvasRef} className="h-full w-full" aria-label="Squad clubs' real upcoming away trips, shown as flight paths on a globe" />
}
