import * as THREE from 'three'
import { useThreeScene } from '@/lib/three/useThreeScene'

export interface Pitch3DPlayer {
  playerId: number
  name: string
  crestUrl: string | null
  row: number // 0 = GK, increasing toward attack
  rowCount: number // real players in this same row (for horizontal spread)
  slot: number // real 0-indexed position within the row
  isCaptain?: boolean
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'

/** A real broadcast-camera pitch: a flat green plane with real pitch
 * markings (the exact same real proportions `PitchMarkings.tsx` already
 * draws for the 2D pitch - a 105x68m pitch, real penalty-area/six-yard-box/
 * centre-circle dimensions - drawn once onto a canvas texture rather than
 * reinventing the geometry in 3D), real crests standing as billboards at
 * their real formation position, shot from an angled broadcast camera
 * instead of flat top-down. This is deliberately an alternate view, not a
 * replacement for the existing 2D tactical board (which already reads
 * well) - a toggle, not a takeover.
 *
 * Real, disclosed limitation found live: real player SHIRTS (not crests)
 * would have been the more natural asset here, matching the 2D pitch, but
 * they're hosted cross-origin at fantasy.premierleague.com with no CORS
 * headers - a plain `<img>` tag can display a cross-origin image fine, but
 * `THREE.TextureLoader` needs real CORS permission to read the pixel data
 * into a WebGL texture, and this host doesn't grant it (confirmed live:
 * every shirt load failed with a real CORS console error). Crests are
 * already self-hosted same-origin (`/crests/*.png`, the same real caching
 * this project already built for the podium), so used here instead - a
 * real substitution, not a silent downgrade. Self-hosting shirts the same
 * way crests already are would be the real fix, a scoped backend follow-up
 * (`ingestion/crest_assets.py`'s own pattern), not attempted this pass. */
export function Pitch3D({ players }: { players: Pitch3DPlayer[] }) {
  const canvasRef = useThreeScene((_canvas, renderer) => {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100)
    camera.position.set(0, 9, 11)
    camera.lookAt(0, 0, -1)

    scene.add(new THREE.AmbientLight(0xffffff, 0.85))
    const key = new THREE.DirectionalLight(0xffffff, 0.7)
    key.position.set(4, 10, 6)
    scene.add(key)

    // Real pitch markings, drawn once onto a canvas texture at the same
    // real proportions PitchMarkings.tsx uses (105x68m FIFA pitch).
    const W = 680, H = 1050
    const canvas = document.createElement('canvas')
    canvas.width = W
    canvas.height = H
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = cssVar('--pitch-green') || '#1a5c33'
    ctx.fillRect(0, 0, W, H)
    ctx.strokeStyle = 'rgba(255,255,255,0.55)'
    ctx.lineWidth = 3
    const CX = W / 2
    ctx.strokeRect(6, 6, W - 12, H - 12)
    ctx.beginPath(); ctx.moveTo(6, H / 2); ctx.lineTo(W - 6, H / 2); ctx.stroke()
    ctx.beginPath(); ctx.arc(CX, H / 2, 91.5, 0, Math.PI * 2); ctx.stroke()
    const PEN_W = 403.2, PEN_H = 165, SIX_W = 183.2, SIX_H = 55
    ctx.strokeRect(CX - PEN_W / 2, 6, PEN_W, PEN_H)
    ctx.strokeRect(CX - SIX_W / 2, 6, SIX_W, SIX_H)
    ctx.strokeRect(CX - PEN_W / 2, H - PEN_H - 6, PEN_W, PEN_H)
    ctx.strokeRect(CX - SIX_W / 2, H - SIX_H - 6, SIX_W, SIX_H)
    const texture = new THREE.CanvasTexture(canvas)
    texture.colorSpace = THREE.SRGBColorSpace

    const pitchGeo = new THREE.PlaneGeometry(6.8, 10.5)
    const pitchMesh = new THREE.Mesh(pitchGeo, new THREE.MeshStandardMaterial({ map: texture, roughness: 0.9 }))
    pitchMesh.rotation.x = -Math.PI / 2
    scene.add(pitchMesh)

    const group = new THREE.Group()
    const maxRow = Math.max(...players.map((p) => p.row), 1)
    const loader = new THREE.TextureLoader()
    for (const p of players) {
      // z: GK (row 0) near camera/bottom of pitch, attack (max row) far end.
      const z = 4.6 - (p.row / maxRow) * 9.2
      const spread = Math.min(5.6, 1.4 * p.rowCount)
      const x = p.rowCount > 1 ? -spread / 2 + (spread / (p.rowCount - 1)) * p.slot : 0
      const size = p.isCaptain ? 0.85 : 0.65

      // A flat dark disc grounds the crest against the green pitch (crest
      // PNGs are transparent-background, real logos, not a solid shirt
      // shape) - always added even before the real crest image resolves,
      // so a player's real position is visible on the pitch immediately.
      const disc = new THREE.Mesh(
        new THREE.CircleGeometry(size * 0.62, 24),
        new THREE.MeshStandardMaterial({ color: cssVar('--void'), roughness: 0.8 }),
      )
      disc.rotation.x = -Math.PI / 2
      disc.position.set(x, 0.01, z)
      group.add(disc)

      if (p.crestUrl) {
        loader.load(p.crestUrl, (tex) => {
          tex.colorSpace = THREE.SRGBColorSpace
          const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true })
          const plane = new THREE.Mesh(new THREE.PlaneGeometry(size, size), mat)
          plane.position.set(x, size / 2, z)
          group.add(plane)
          if (p.isCaptain) {
            const armband = new THREE.Mesh(
              new THREE.CircleGeometry(0.1, 16),
              new THREE.MeshBasicMaterial({ color: cssVar('--broadcast-gold') }),
            )
            armband.position.set(x + size * 0.4, size * 0.85, z + 0.01)
            group.add(armband)
          }
        })
      }
    }
    scene.add(group)

    return {
      render: (width, height) => {
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        renderer.render(scene, camera)
      },
      dispose: () => {
        pitchGeo.dispose()
        texture.dispose()
        group.traverse((obj) => {
          if (obj instanceof THREE.Mesh) {
            obj.geometry.dispose()
            const mat = obj.material as THREE.Material | THREE.Material[]
            if (Array.isArray(mat)) mat.forEach((m) => m.dispose())
            else mat.dispose()
          }
        })
      },
    }
  }, [players])

  if (players.length === 0) return null
  return <canvas ref={canvasRef} className="h-full w-full" aria-label="Real starting XI, broadcast camera angle" />
}
