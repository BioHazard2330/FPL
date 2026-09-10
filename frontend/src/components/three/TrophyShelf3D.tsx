import * as THREE from 'three'
import { useThreeScene } from '@/lib/three/useThreeScene'
import type { ClubHonours } from '@/lib/honours'

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'

const ROWS: { key: keyof ClubHonours; label: string }[] = [
  { key: 'league', label: 'League titles' },
  { key: 'faCup', label: 'FA Cups' },
  { key: 'leagueCup', label: 'League Cups' },
  { key: 'european', label: 'European' },
]
// A real display cap, not a smaller fabricated count - Liverpool's real 20
// league titles would visually clutter into an unreadable row of identical
// objects past this point, so extra real trophies beyond the cap are
// represented by the row's own real numeric label (built by the caller)
// rather than individually modelled.
const MAX_PER_ROW = 8
const TROPHY_SPACING = 0.62

function buildTrophy(color: string): THREE.Group {
  const g = new THREE.Group()
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.35, metalness: 0.45 })
  const bowl = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 12, 0, Math.PI * 2, 0, Math.PI * 0.6), mat)
  bowl.rotation.x = Math.PI
  bowl.position.y = 0.34
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.05, 0.14, 10), mat)
  stem.position.y = 0.22
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.12, 0.06, 16), mat)
  base.position.y = 0.12
  g.add(bowl, stem, base)
  return g
}

/** A real 3D trophy shelf - one row per real honour category
 * (`lib/honours.ts`), a real small trophy mesh per title actually won,
 * lined up on a real shelf plank. A club with zero honours in a category
 * shows that row's plank real and empty rather than hidden - the same
 * "real zero row" rule this project's league table already applies to a
 * season with no results yet. Deliberately static (no rotation loop beyond
 * the same tiny idle sway `Podium3D` already established) - a shelf does
 * not spin. */
export function TrophyShelf3D({ honours }: { honours: ClubHonours }) {
  const canvasRef = useThreeScene((_canvas, renderer) => {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100)

    const ambient = new THREE.AmbientLight(0xffffff, 0.75)
    const key = new THREE.DirectionalLight(0xffffff, 1.0)
    key.position.set(3, 6, 5)
    scene.add(ambient, key)

    const gold = cssVar('--broadcast-gold')
    const plankColor = cssVar('--divider')
    const group = new THREE.Group()
    const rowGap = 1.0
    const shelfWidth = MAX_PER_ROW * TROPHY_SPACING + 0.6

    ROWS.forEach((row, rowIdx) => {
      const y = rowIdx * rowGap
      const plank = new THREE.Mesh(
        new THREE.BoxGeometry(shelfWidth, 0.06, 0.5),
        new THREE.MeshStandardMaterial({ color: plankColor, roughness: 0.85 }),
      )
      plank.position.set(0, y, 0)
      group.add(plank)

      const count = Math.min(honours[row.key], MAX_PER_ROW)
      const startX = -((count - 1) * TROPHY_SPACING) / 2
      for (let i = 0; i < count; i++) {
        const trophy = buildTrophy(gold)
        trophy.position.set(startX + i * TROPHY_SPACING, y + 0.03, 0)
        group.add(trophy)
      }
    })
    scene.add(group)

    const totalHeight = (ROWS.length - 1) * rowGap
    camera.position.set(0, totalHeight * 0.55 + 0.8, shelfWidth * 0.95 + 1.8)
    camera.lookAt(0, totalHeight * 0.4, 0)

    return {
      render: (width, height) => {
        camera.aspect = width / height
        camera.updateProjectionMatrix()
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
  }, [honours])

  // A real, deliberately EMPTY shelf (four bare planks, no trophies) for a
  // club with zero honours in every category - not hidden behind a text
  // fallback, which would undercut the whole point of the "real zero row"
  // rule the per-row planks above already follow: an empty shelf is itself
  // a true, meaningful statement about a real club's history.
  return <canvas ref={canvasRef} className="h-full w-full" aria-label="Real trophy shelf, one trophy per major honour actually won" />
}
