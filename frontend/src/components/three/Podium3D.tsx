import * as THREE from 'three'
import { useThreeScene } from '@/lib/three/useThreeScene'

export interface PodiumEntry {
  position: number
  name: string
  points: number
  crestUrl: string | null
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'

/** Real league-table top 3, rendered as an actual 3D podium - block height
 * driven by each club's real points total, not a fixed 1st/2nd/3rd shape.
 * A club a long way clear at the top reads as a taller block, not just a
 * bigger number next to an identical box. Crests are real, loaded as
 * textures on the block face - never a flat sticker pasted over a 2D card. */
export function Podium3D({ entries }: { entries: PodiumEntry[] }) {
  const canvasRef = useThreeScene((_canvas, renderer) => {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100)
    // Framed to fit the tallest possible block (1.1 + 3.2 = 4.3) plus its
    // crest plane above it (~+1.25 more) with real margin - a real bug
    // caught live: the first framing clipped every crest above the visible
    // canvas because it only accounted for the podium blocks, not the
    // crest planes sitting on top of them.
    camera.position.set(0, 4.6, 10.5)
    camera.lookAt(0, 2.4, 0)

    const ambient = new THREE.AmbientLight(0xffffff, 0.65)
    const key = new THREE.DirectionalLight(0xffffff, 1.1)
    key.position.set(3, 6, 5)
    scene.add(ambient, key)

    const maxPoints = Math.max(...entries.map((e) => e.points), 1)
    const colors = [cssVar('--broadcast-gold'), cssVar('--text-muted'), cssVar('--broadcast-blue')]
    const group = new THREE.Group()
    const loader = new THREE.TextureLoader()
    loader.setCrossOrigin('anonymous')

    // Classic podium order left-to-right: 2nd, 1st, 3rd - but height always
    // reflects the real points gap, not a fixed 4/3/2 shape.
    const order = [1, 0, 2].filter((i) => i < entries.length)
    const slotX = [-2.4, 0, 2.4]
    order.forEach((entryIdx, slot) => {
      const e = entries[entryIdx]
      const height = 1.1 + (e.points / maxPoints) * 3.2
      const geo = new THREE.BoxGeometry(1.9, height, 1.9)
      const mat = new THREE.MeshStandardMaterial({ color: colors[entryIdx] ?? '#888', roughness: 0.55, metalness: 0.08 })
      const box = new THREE.Mesh(geo, mat)
      box.position.set(slotX[slot], height / 2, 0)
      group.add(box)

      if (e.crestUrl) {
        loader.load(e.crestUrl, (tex) => {
          tex.colorSpace = THREE.SRGBColorSpace
          const size = 1.1
          const plane = new THREE.Mesh(
            new THREE.PlaneGeometry(size, size),
            new THREE.MeshBasicMaterial({ map: tex, transparent: true }),
          )
          plane.position.set(slotX[slot], height + size / 2 + 0.15, 0)
          group.add(plane)
        })
      }
    })
    scene.add(group)

    return {
      render: (width, height) => {
        camera.aspect = width / height
        camera.updateProjectionMatrix()
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
  }, [entries])

  return <canvas ref={canvasRef} className="h-full w-full" aria-label="Top 3 league table podium, block height reflects real points" />
}
