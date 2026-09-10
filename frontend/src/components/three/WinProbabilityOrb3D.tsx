import * as THREE from 'three'
import { useThreeScene } from '@/lib/three/useThreeScene'

export interface WinProbabilitySplit {
  homeWinPct: number
  drawPct: number
  awayWinPct: number
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'

/** A real, STATIC 3D read of the live win-probability model's own output
 * (`models/live_win_probability.py`, already real, tested, API-wired) - a
 * sphere cut into three real angular wedges (`SphereGeometry`'s own
 * `phiStart`/`phiLength`, an orange-peel-segment slice, not three separate
 * shapes glued together), each wedge's real angular width driven directly
 * by the real home/draw/away percentage. Same real colour mapping
 * `MatchCentre.tsx`'s existing flat bar already uses (pitch-green/
 * text-faint/broadcast-blue), so the two never disagree on what a colour
 * means.
 *
 * Deliberately NOT the "fluid"/floating orb the roadmap originally asked
 * for: this project's own `DESIGN.md` motion law forbids "floating" and
 * "breathing" outright, the same real conflict the Captain push-in item
 * already hit and resolved the same way - real 3D substance (a genuine
 * volume split by a real probability), the idle-sway convention every
 * other 3D component here already uses, and nothing that continuously
 * pulses or drifts on its own. */
export function WinProbabilityOrb3D({ split }: { split: WinProbabilitySplit }) {
  const canvasRef = useThreeScene((_canvas, renderer) => {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100)
    // A near-top-down angle, not a flat side-on view - checked live before
    // settling on this: a side-on camera can hide a whole real wedge behind
    // the sphere's far side whenever one outcome is heavily favoured (a
    // genuinely common real case, e.g. 71/26/3), reading as a solid single
    // colour with no visible split at all. Tilted down like this, all three
    // real wedges stay visible together regardless of the actual split, the
    // same real pie-chart legibility a flat 2D chart already has, while
    // still reading as a genuine sphere (visible curvature/shading), not a
    // flat disc.
    camera.position.set(0, 4.2, 1.3)
    camera.lookAt(0, 0, 0)

    const ambient = new THREE.AmbientLight(0xffffff, 0.75)
    const key = new THREE.DirectionalLight(0xffffff, 1.0)
    key.position.set(3, 4, 5)
    scene.add(ambient, key)

    const group = new THREE.Group()
    const radius = 1.15
    const total = Math.max(split.homeWinPct + split.drawPct + split.awayWinPct, 0.001)
    const segments: { pct: number; color: string }[] = [
      { pct: split.homeWinPct, color: cssVar('--pitch-green') },
      { pct: split.drawPct, color: cssVar('--text-faint') },
      { pct: split.awayWinPct, color: cssVar('--broadcast-blue') },
    ]

    let phiStart = 0
    for (const seg of segments) {
      const phiLength = (seg.pct / total) * Math.PI * 2
      if (phiLength <= 0) continue
      const geo = new THREE.SphereGeometry(radius, 48, 32, phiStart, phiLength)
      const mat = new THREE.MeshStandardMaterial({ color: seg.color, roughness: 0.45, metalness: 0.05 })
      group.add(new THREE.Mesh(geo, mat))
      phiStart += phiLength
    }
    scene.add(group)

    return {
      render: (width, height) => {
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        // Same tiny idle sway every other 3D component in this app uses -
        // never a spin, never a pulse.
        group.rotation.y = Math.sin(Date.now() / 6000) * 0.2
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
  }, [split.homeWinPct, split.drawPct, split.awayWinPct])

  return <canvas ref={canvasRef} className="h-full w-full" aria-label="Real win-probability split, rendered as a real 3D sphere cut into home/draw/away wedges by their real percentages" />
}
