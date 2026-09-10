import * as THREE from 'three'
import { useThreeScene } from '@/lib/three/useThreeScene'
import { STADIUMS } from '@/lib/stadiums'
import { crestUrl } from '@/lib/api'

export interface TravelLeg {
  fromTeamCode: number
  toTeamCode: number
  fromShort: string
  toShort: string
  event: number
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'

// Real English Premier League ground coordinates cluster within about 5
// degrees of latitude/longitude of each other - a rotating globe (the
// first version of this component) is the wrong metaphor entirely for a
// single domestic country: the sphere's curvature is imperceptible at this
// scale, so it just reads as an abstract grid ball, and spinning it drifts
// the view away from the one region that actually matters. This version
// drops the planet metaphor and renders a flat, tilted tactical board
// instead - the same visual language this app already uses for a pitch or
// a scouting board - with real club positions placed via a simple local
// flat projection (negligible distortion over ~5 degrees, no need for a
// real map projection library).
const CENTER_LAT = 52.8
const CENTER_LNG = -1.6
const SCALE = 9
const COS_CENTER_LAT = Math.cos((CENTER_LAT * Math.PI) / 180)

function boardPosition(lat: number, lng: number): [number, number] {
  const x = (lng - CENTER_LNG) * COS_CENTER_LAT * SCALE
  const z = -(lat - CENTER_LAT) * SCALE
  return [x, z]
}

export function TravelGlobe({ legs }: { legs: TravelLeg[] }) {
  const canvasRef = useThreeScene((_canvas, renderer) => {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 200)
    // A real, fixed war-room-table angle - looking down and across the
    // board, never rotating. The only motion on this whole board is a
    // small marker actually flying each real route (meaning "this club is
    // travelling here"), not a decorative spin of the board itself.
    camera.position.set(0, 16, 15)
    camera.lookAt(0, 0, 0)

    scene.add(new THREE.AmbientLight(0xffffff, 0.8))
    const key = new THREE.DirectionalLight(0xffffff, 0.9)
    key.position.set(-6, 14, 8)
    scene.add(key)

    const codes = [...new Set(legs.flatMap((l) => [l.fromTeamCode, l.toTeamCode]))].filter((c) => STADIUMS[c])
    const positions = new Map(codes.map((c) => [c, boardPosition(STADIUMS[c].lat, STADIUMS[c].lng)]))
    const xs = codes.map((c) => positions.get(c)![0])
    const zs = codes.map((c) => positions.get(c)![1])
    const boardW = Math.max(...xs) - Math.min(...xs) + 6
    const boardH = Math.max(...zs) - Math.min(...zs) + 6

    const group = new THREE.Group()

    const board = new THREE.Mesh(
      new THREE.BoxGeometry(boardW, 0.3, boardH),
      new THREE.MeshStandardMaterial({ color: cssVar('--panel'), roughness: 0.95 }),
    )
    board.position.y = -0.2
    group.add(board)

    // Real hairline grid on the board face - the same flat, no-photo
    // reference-marks convention `PitchMarkings.tsx` already uses for a
    // pitch, applied here instead of a photographic earth texture.
    const grid = new THREE.GridHelper(Math.max(boardW, boardH), 10, cssVar('--divider'), cssVar('--divider'))
    grid.position.y = -0.04
    group.add(grid)

    const loader = new THREE.TextureLoader()
    for (const code of codes) {
      const [x, z] = positions.get(code)!
      const isEndpointOnly = !legs.some((l) => l.fromTeamCode === code) // an opponent ground, never a squad club's own
      const peg = new THREE.Mesh(
        new THREE.CylinderGeometry(0.18, 0.18, 0.5, 12),
        new THREE.MeshStandardMaterial({ color: isEndpointOnly ? cssVar('--broadcast-blue') : cssVar('--broadcast-gold') }),
      )
      peg.position.set(x, 0.25, z)
      group.add(peg)

      const crest = crestUrl(code)
      if (crest) {
        loader.load(crest, (tex) => {
          tex.colorSpace = THREE.SRGBColorSpace
          const plane = new THREE.Mesh(
            new THREE.PlaneGeometry(0.9, 0.9),
            new THREE.MeshBasicMaterial({ map: tex, transparent: true }),
          )
          plane.position.set(x, 1.1, z)
          plane.rotation.x = -Math.PI / 5
          group.add(plane)
        })
      }
    }

    // Each real travel leg gets a static path line plus one small marker
    // that actually flies the route, looping - real, meaningful motion
    // ("this club is travelling here"), not a decorative spin of the board.
    const travellers: { curve: THREE.QuadraticBezierCurve3; mesh: THREE.Mesh; speed: number }[] = []
    for (const leg of legs) {
      const from = positions.get(leg.fromTeamCode)
      const to = positions.get(leg.toTeamCode)
      if (!from || !to) continue
      const dist = Math.hypot(to[0] - from[0], to[1] - from[1])
      const mid = new THREE.Vector3((from[0] + to[0]) / 2, Math.max(0.6, dist * 0.22), (from[1] + to[1]) / 2)
      const curve = new THREE.QuadraticBezierCurve3(
        new THREE.Vector3(from[0], 0.15, from[1]),
        mid,
        new THREE.Vector3(to[0], 0.15, to[1]),
      )
      const geo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(32))
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: cssVar('--pitch-green'), transparent: true, opacity: 0.55 }))
      group.add(line)

      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(0.09, 8, 8),
        new THREE.MeshStandardMaterial({ color: cssVar('--pitch-green') }),
      )
      group.add(marker)
      travellers.push({ curve, mesh: marker, speed: 0.15 + Math.random() * 0.08 })
    }

    scene.add(group)

    let t = 0
    return {
      render: (width, height) => {
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        t += 0.01
        for (const trav of travellers) {
          const progress = (t * trav.speed) % 1
          trav.curve.getPointAt(progress, trav.mesh.position)
        }
        renderer.render(scene, camera)
      },
      dispose: () => {
        group.traverse((obj) => {
          if (obj instanceof THREE.Mesh || obj instanceof THREE.Line) {
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
  return <canvas ref={canvasRef} className="h-full w-full" aria-label="Squad clubs' real upcoming away trips on a tactical board" />
}
