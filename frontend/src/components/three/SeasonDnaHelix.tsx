import * as THREE from 'three'
import { useThreeScene } from '@/lib/three/useThreeScene'

export interface SeasonDnaMatch {
  result: 'W' | 'D' | 'L'
  opponent_short: string
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'

const RADIUS = 1.6
const Y_STEP = 0.62
const POINTS_PER_TURN = 7

/** A real single-strand spiral through the season's real results, oldest
 * match at the base rising to the most recent at the top - deliberately
 * ONE strand, not a literal double helix with a second, invented strand and
 * connecting rungs (a real double helix's base pairs would have to link
 * this club's result to something else's, and no such real second series
 * exists here - inventing one just to complete the DNA picture would be
 * exactly the kind of fabricated relationship this project's own audit
 * (see `docs/FOOTBALL_FEATURES_ROADMAP.md`'s war-room-string-board writeup)
 * already ruled out). What IS real: the coil itself, and the order of
 * results along it - so the strand curves through real Catmull-Rom points,
 * one per real match, colour-coded by the same real W/D/L this app's
 * `ClubScreen`/`MatchweekScreen` already use. */
export function SeasonDnaHelix({ matches }: { matches: SeasonDnaMatch[] }) {
  const canvasRef = useThreeScene((_canvas, renderer) => {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100)

    const ambient = new THREE.AmbientLight(0xffffff, 0.7)
    const key = new THREE.DirectionalLight(0xffffff, 1.0)
    key.position.set(3, 6, 5)
    scene.add(ambient, key)

    const colorByResult: Record<string, string> = {
      W: cssVar('--pitch-green'),
      D: cssVar('--text-muted'),
      L: cssVar('--alert-red'),
    }

    const points = matches.map((_, i) => {
      const angle = (i * Math.PI * 2) / POINTS_PER_TURN
      const y = i * Y_STEP
      return new THREE.Vector3(RADIUS * Math.cos(angle), y, RADIUS * Math.sin(angle))
    })

    const group = new THREE.Group()

    if (points.length >= 2) {
      const curve = new THREE.CatmullRomCurve3(points)
      const tubeGeo = new THREE.TubeGeometry(curve, Math.max(points.length * 8, 32), 0.05, 8, false)
      const tubeMat = new THREE.MeshStandardMaterial({ color: cssVar('--divider'), roughness: 0.7 })
      group.add(new THREE.Mesh(tubeGeo, tubeMat))
    }

    for (let i = 0; i < points.length; i++) {
      const bead = new THREE.Mesh(
        new THREE.SphereGeometry(0.24, 20, 20),
        new THREE.MeshStandardMaterial({ color: colorByResult[matches[i].result] ?? '#888', roughness: 0.5 }),
      )
      bead.position.copy(points[i])
      group.add(bead)
    }
    scene.add(group)

    const totalHeight = Math.max((points.length - 1) * Y_STEP, 1)
    camera.position.set(RADIUS * 3.2, totalHeight * 0.55 + 1, RADIUS * 3.2 + 3)
    camera.lookAt(0, totalHeight / 2, 0)

    return {
      render: (width, height) => {
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        // Same tiny idle sway `Podium3D` already established (max ~8.6
        // degrees) - a living camera, not a spin; kept identical rather
        // than inventing a second motion convention for this component.
        group.rotation.y = Math.sin(Date.now() / 6000) * 0.15
        renderer.render(scene, camera)
      },
      dispose: () => {
        group.traverse((obj) => {
          if (obj instanceof THREE.Mesh) {
            obj.geometry.dispose()
            const mat = obj.material
            if (Array.isArray(mat)) mat.forEach((m) => m.dispose())
            else mat.dispose()
          }
        })
      },
    }
  }, [matches])

  if (matches.length === 0) return null
  return <canvas ref={canvasRef} className="h-full w-full" aria-label="Season results spiral, oldest at the base, coloured by real win/draw/loss" />
}
