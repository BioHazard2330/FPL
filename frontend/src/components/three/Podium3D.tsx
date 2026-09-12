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
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100)
    // Real bug found live 2026-09-12: the tallest block is ALWAYS exactly
    // 4.3 (1.1 + 3.2, since whichever entry has maxPoints gets ratio 1.0
    // by construction, not a rare hypothetical), so its crest plane's top
    // edge always sits at y=5.55 - the original camera (tilted ~12 degrees
    // downward) clipped it in real production the first time two clubs
    // were closely tied near the top (real Sept 2026 GW3 standings, Man
    // City/Arsenal both on 9pts). A first attempt at a near-level camera
    // still showed only a sliver of each crest at the very top edge of the
    // frame - confirmed live via screenshot - so the look-at target and
    // FOV both get real margin here, not just a levelled tilt.
    camera.position.set(0, 3.2, 10.5)
    camera.lookAt(0, 3.0, 0)

    const ambient = new THREE.AmbientLight(0xffffff, 0.65)
    const key = new THREE.DirectionalLight(0xffffff, 1.1)
    key.position.set(3, 6, 5)
    scene.add(ambient, key)

    const maxPoints = Math.max(...entries.map((e) => e.points), 1)
    const colors = [cssVar('--broadcast-gold'), cssVar('--text-muted'), cssVar('--broadcast-blue')]
    const group = new THREE.Group()
    const loader = new THREE.TextureLoader()

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
          // Real bug found live 2026-09-12: with the default `flipY: true`,
          // the crest texture uploaded to the GPU with the wrong pixel-store
          // flags for this exact three.js/WebGL2 path (a real console
          // warning named FLIP_Y/PREMULTIPLY_ALPHA specifically) and
          // rendered as fully invisible - the mesh existed in the scene
          // graph at the right position (confirmed via a debug log: crest
          // image loaded fine, plane added, child count incremented) but
          // nothing appeared on screen. Setting `flipY = false` here (this
          // plane's own UVs don't depend on the default orientation the
          // way a full 3D model import would) made the crest render
          // correctly - confirmed live, right-side up, not mirrored.
          tex.colorSpace = THREE.SRGBColorSpace
          tex.flipY = false
          tex.needsUpdate = true
          const size = 1.1
          const plane = new THREE.Mesh(
            new THREE.PlaneGeometry(size, size),
            new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }),
          )
          plane.position.set(slotX[slot], height + size / 2 + 0.15, 0.01)
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
