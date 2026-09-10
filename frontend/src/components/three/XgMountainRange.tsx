import * as THREE from 'three'
import { useThreeScene } from '@/lib/three/useThreeScene'

export interface XgMountainMatch {
  xg: number
  xga: number
  opponent_short: string
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'

const BAR_WIDTH = 0.55
const BAR_GAP = 0.35
const MAX_BAR_HEIGHT = 3.2
// A real, fixed scale (not "tallest match this season = full height") - a
// season with one huge 4xG outlier would otherwise squash every other real
// match flat against the axis. 3.5 comfortably covers a real Premier League
// match's own realistic xG range without ever being reached by a
// genuinely typical one.
const XG_SCALE_CAP = 3.5

/** Real per-match xG "for" and "against" as two parallel ridgelines - a
 * real, non-fabricated pairing (both numbers are independently true facts
 * about the SAME real match, unlike the war-room string board's would-be
 * cross-item links), one bar pair per real played fixture in chronological
 * order. Deliberately excludes any match FotMob was never fetched for
 * (both `xg`/`xga` null) rather than rendering a fabricated zero-height
 * bar where "no data" and "a goalless-chance match" would look identical. */
export function XgMountainRange({ matches }: { matches: XgMountainMatch[] }) {
  const canvasRef = useThreeScene((_canvas, renderer) => {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100)

    const ambient = new THREE.AmbientLight(0xffffff, 0.7)
    const key = new THREE.DirectionalLight(0xffffff, 1.0)
    key.position.set(3, 6, 5)
    scene.add(ambient, key)

    const forColor = cssVar('--pitch-green')
    const againstColor = cssVar('--alert-red')
    const group = new THREE.Group()
    const totalWidth = matches.length * (BAR_WIDTH + BAR_GAP)
    const startX = -totalWidth / 2

    matches.forEach((m, i) => {
      const x = startX + i * (BAR_WIDTH + BAR_GAP)
      const forHeight = Math.max((Math.min(m.xg, XG_SCALE_CAP) / XG_SCALE_CAP) * MAX_BAR_HEIGHT, 0.04)
      const againstHeight = Math.max((Math.min(m.xga, XG_SCALE_CAP) / XG_SCALE_CAP) * MAX_BAR_HEIGHT, 0.04)

      const forBar = new THREE.Mesh(
        new THREE.BoxGeometry(BAR_WIDTH, forHeight, BAR_WIDTH),
        new THREE.MeshStandardMaterial({ color: forColor, roughness: 0.6 }),
      )
      forBar.position.set(x, forHeight / 2, 0.4)
      group.add(forBar)

      const againstBar = new THREE.Mesh(
        new THREE.BoxGeometry(BAR_WIDTH, againstHeight, BAR_WIDTH),
        new THREE.MeshStandardMaterial({ color: againstColor, roughness: 0.6 }),
      )
      againstBar.position.set(x, againstHeight / 2, -0.4)
      group.add(againstBar)
    })
    scene.add(group)

    camera.position.set(0, MAX_BAR_HEIGHT * 1.1, totalWidth * 0.85 + 2)
    camera.lookAt(0, MAX_BAR_HEIGHT * 0.35, 0)

    return {
      render: (width, height) => {
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        // Same tiny idle sway `Podium3D`/`SeasonDnaHelix` already use.
        group.rotation.y = Math.sin(Date.now() / 6000) * 0.12
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
  return (
    <canvas
      ref={canvasRef}
      className="h-full w-full"
      aria-label="Real per-match xG for (front row) and against (back row) this season, in chronological order"
    />
  )
}
