import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { clubColors } from '@/lib/clubs'

/** THE STADIUM - the eleven under floodlights, in three dimensions. A night match: a mown pitch with its markings, four
 * floodlight towers casting shadows, stands lit by the crowd, and the eleven in their clubs' colours where the formation
 * puts them, each with a name plate carrying his projection; the captain stands in a turning gold ring. The camera flies
 * in from above the stand, then drifts; drag to orbit, scroll to zoom, click a player to open his file. */

export interface StadiumPlayer { player_id: number; name: string; position: string; team_code: number | null; xp: number; captain: boolean; vice: boolean }

const LENGTH = 105
const WIDTH = 68
const DEPTH: Record<string, number> = { GKP: 46, DEF: 30, MID: 8, FWD: -18 }
const SCALE = 2.6

function pitchTexture(): THREE.CanvasTexture {
  const c = document.createElement('canvas')
  c.width = 2048
  c.height = 1328
  const g = c.getContext('2d')!
  const bands = 18
  for (let i = 0; i < bands; i++) {
    g.fillStyle = i % 2 ? '#2f7d3a' : '#378a43'
    g.fillRect(0, (i * c.height) / bands, c.width, c.height / bands + 1)
  }
  const sx = c.width / WIDTH, sy = c.height / LENGTH
  g.strokeStyle = 'rgba(255,255,255,0.92)'
  g.lineWidth = 7
  const rect = (x: number, y: number, w: number, h: number) => g.strokeRect(x * sx, y * sy, w * sx, h * sy)
  rect(1, 1, WIDTH - 2, LENGTH - 2)
  g.beginPath(); g.moveTo(sx, (LENGTH / 2) * sy); g.lineTo((WIDTH - 1) * sx, (LENGTH / 2) * sy); g.stroke()
  g.beginPath(); g.arc((WIDTH / 2) * sx, (LENGTH / 2) * sy, 9.15 * sx, 0, Math.PI * 2); g.stroke()
  for (const top of [true, false]) {
    const y0 = top ? 1 : LENGTH - 1
    const dir = top ? 1 : -1
    rect((WIDTH - 40.3) / 2, top ? 1 : LENGTH - 1 - 16.5, 40.3, 16.5)
    rect((WIDTH - 18.3) / 2, top ? 1 : LENGTH - 1 - 5.5, 18.3, 5.5)
    g.beginPath(); g.arc((WIDTH / 2) * sx, (y0 + dir * 11) * sy, 9.15 * sx, top ? 0.2 * Math.PI : 1.2 * Math.PI, top ? 0.8 * Math.PI : 1.8 * Math.PI); g.stroke()
  }
  const t = new THREE.CanvasTexture(c)
  t.anisotropy = 8
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

function plate(name: string, xp: number, captain: boolean): THREE.Sprite {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 128
  const g = c.getContext('2d')!
  g.fillStyle = '#17130e'
  g.fillRect(0, 16, 380, 96)
  g.fillStyle = '#0b7d40'
  g.fillRect(380, 16, 132, 96)
  if (captain) { g.fillStyle = '#e8a800'; g.fillRect(0, 16, 14, 96) }
  g.fillStyle = '#f6f0e2'
  g.font = '900 54px "Big Shoulders Display", Impact, sans-serif'
  g.textBaseline = 'middle'
  g.fillText(name.toUpperCase().slice(0, 13), captain ? 30 : 20, 66)
  g.font = '900 58px "Big Shoulders Display", Impact, sans-serif'
  g.fillText(xp.toFixed(1), 396, 66)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }))
  s.scale.set(12, 3, 1)
  s.renderOrder = 10
  return s
}

function figure(primary: string, accent: string, keeper: boolean): THREE.Group {
  const g = new THREE.Group()
  const shirt = new THREE.MeshStandardMaterial({ color: keeper ? '#d1ff3c' : primary, roughness: 0.55 })
  const shorts = new THREE.MeshStandardMaterial({ color: accent, roughness: 0.6 })
  const skin = new THREE.MeshStandardMaterial({ color: '#c99a73', roughness: 0.7 })
  const boot = new THREE.MeshStandardMaterial({ color: '#111111', roughness: 0.4 })
  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.28, 0.55, 6, 12), shirt)
  torso.position.y = 1.25
  const hips = new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.25, 0.3, 12), shorts)
  hips.position.y = 0.82
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.17, 16, 12), skin)
  head.position.y = 1.78
  for (const side of [-1, 1]) {
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.08, 0.7, 8), skin)
    leg.position.set(0.12 * side, 0.38, 0)
    const shoe = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.08, 0.26), boot)
    shoe.position.set(0.12 * side, 0.04, 0.05)
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.07, 0.45, 4, 8), shirt)
    arm.position.set(0.36 * side, 1.25, 0)
    arm.rotation.z = side * 0.18
    g.add(leg, shoe, arm)
  }
  g.add(torso, hips, head)
  g.traverse((o) => { if ((o as THREE.Mesh).isMesh) { o.castShadow = true } })
  g.scale.setScalar(SCALE)
  return g
}

function spots(players: StadiumPlayer[]): Map<number, [number, number]> {
  const out = new Map<number, [number, number]>()
  for (const pos of ['GKP', 'DEF', 'MID', 'FWD']) {
    const row = players.filter((p) => p.position === pos)
    row.forEach((p, i) => {
      const x = row.length === 1 ? 0 : -WIDTH * 0.36 + (i * WIDTH * 0.72) / (row.length - 1)
      const stagger = row.length >= 4 ? (i % 2 ? 4 : -2) : 0
      out.set(p.player_id, [x, DEPTH[pos] + stagger])
    })
  }
  return out
}

export function Stadium3D({ players, ticker, height = 560 }: { players: StadiumPlayer[]; ticker: string[]; height?: number }) {
  const mount = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    const el = mount.current
    if (!el || players.length === 0) return
    const w = el.clientWidth
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(w, height)
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.05
    el.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#0a0d14')
    scene.fog = new THREE.Fog('#0a0d14', 140, 260)
    const camera = new THREE.PerspectiveCamera(40, w / height, 0.5, 600)

    const pitch = new THREE.Mesh(new THREE.PlaneGeometry(WIDTH + 14, LENGTH + 14), new THREE.MeshStandardMaterial({ color: '#2b7436', roughness: 0.95 }))
    pitch.rotation.x = -Math.PI / 2
    pitch.position.y = -0.02
    pitch.receiveShadow = true
    const field = new THREE.Mesh(new THREE.PlaneGeometry(WIDTH, LENGTH), new THREE.MeshStandardMaterial({ map: pitchTexture(), roughness: 0.9 }))
    field.rotation.x = -Math.PI / 2
    field.receiveShadow = true
    scene.add(pitch, field)

    for (const z of [-LENGTH / 2, LENGTH / 2]) {
      const goal = new THREE.Group()
      const post = new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: 0.3 })
      for (const x of [-3.66, 3.66]) {
        const p = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 2.44, 8), post)
        p.position.set(x, 1.22, 0)
        goal.add(p)
      }
      const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 7.32, 8), post)
      bar.rotation.z = Math.PI / 2
      bar.position.y = 2.44
      const net = new THREE.Mesh(new THREE.BoxGeometry(7.32, 2.44, 2), new THREE.MeshStandardMaterial({ color: '#ffffff', transparent: true, opacity: 0.18, wireframe: true }))
      net.position.set(0, 1.22, z > 0 ? 1 : -1)
      goal.add(bar, net)
      goal.position.z = z
      goal.traverse((o) => { o.castShadow = true })
      scene.add(goal)
    }

    const standMat = new THREE.MeshStandardMaterial({ color: '#1a1f2b', roughness: 0.9 })
    const crowd: number[] = []
    const crowdColors: number[] = []
    const palette = [new THREE.Color('#f6f0e2'), new THREE.Color('#ff4614'), new THREE.Color('#1c3fd1'), new THREE.Color('#e8a800'), new THREE.Color('#0b7d40')]
    const stands: [number, number, number, number, number][] = [
      [0, -LENGTH / 2 - 16, WIDTH + 30, 0, 0], [0, LENGTH / 2 + 16, WIDTH + 30, 0, Math.PI],
      [-WIDTH / 2 - 16, 0, LENGTH + 30, 0, Math.PI / 2], [WIDTH / 2 + 16, 0, LENGTH + 30, 0, -Math.PI / 2],
    ]
    for (const [x, z, len, , rot] of stands) {
      const stand = new THREE.Group()
      for (let k = 0; k < 7; k++) {
        const step = new THREE.Mesh(new THREE.BoxGeometry(len, 1.6 + k * 1.7, 2.6), standMat)
        step.position.set(0, (1.6 + k * 1.7) / 2, 8 - k * 2.6)
        step.receiveShadow = true
        stand.add(step)
        for (let i = 0; i < 150; i++) {
          const v = new THREE.Vector3((Math.random() - 0.5) * len, 1.6 + k * 1.7 + 0.4, 8 - k * 2.6 + (Math.random() - 0.5) * 2)
            .applyAxisAngle(new THREE.Vector3(0, 1, 0), rot).add(new THREE.Vector3(x, 0, z))
          crowd.push(v.x, v.y, v.z)
          const col = palette[Math.floor(Math.random() * palette.length)]
          crowdColors.push(col.r, col.g, col.b)
        }
      }
      const roof = new THREE.Mesh(new THREE.BoxGeometry(len, 0.6, 22), new THREE.MeshStandardMaterial({ color: '#9fb4ff', roughness: 0.2, metalness: 0.4, transparent: true, opacity: 0.12, depthWrite: false }))
      roof.position.set(0, 17, -1)
      const lip = new THREE.Mesh(new THREE.BoxGeometry(len, 0.25, 0.25), new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: '#cfe0ff', emissiveIntensity: 1.6 }))
      lip.position.set(0, 16.6, 10)
      stand.add(roof, lip)
      stand.position.set(x, 0, z)
      stand.rotation.y = rot
      scene.add(stand)
    }
    const crowdGeo = new THREE.BufferGeometry()
    crowdGeo.setAttribute('position', new THREE.Float32BufferAttribute(crowd, 3))
    crowdGeo.setAttribute('color', new THREE.Float32BufferAttribute(crowdColors, 3))
    const crowdPts = new THREE.Points(crowdGeo, new THREE.PointsMaterial({ size: 0.7, vertexColors: true, transparent: true, opacity: 0.85 }))
    scene.add(crowdPts)

    const ledCanvas = document.createElement('canvas')
    ledCanvas.width = 2048
    ledCanvas.height = 64
    const lg = ledCanvas.getContext('2d')!
    lg.fillStyle = '#05070b'
    lg.fillRect(0, 0, 2048, 64)
    lg.font = '900 44px "Big Shoulders Display", Impact, sans-serif'
    lg.textBaseline = 'middle'
    let lx = 16
    for (const [i, part] of [...ticker, ...ticker].entries()) {
      lg.fillStyle = i % 2 ? '#ff4614' : '#f6f0e2'
      lg.fillText(part.toUpperCase(), lx, 34)
      lx += lg.measureText(part.toUpperCase()).width + 60
      if (lx > 2048) break
    }
    const ledTex = new THREE.CanvasTexture(ledCanvas)
    ledTex.colorSpace = THREE.SRGBColorSpace
    ledTex.wrapS = THREE.RepeatWrapping
    ledTex.repeat.set(2, 1)
    const leds: THREE.Mesh[] = []
    for (const [x, z, len, rot] of [[0, LENGTH / 2 + 4, WIDTH + 6, Math.PI], [0, -LENGTH / 2 - 4, WIDTH + 6, 0], [-WIDTH / 2 - 4, 0, LENGTH, Math.PI / 2], [WIDTH / 2 + 4, 0, LENGTH, -Math.PI / 2]] as const) {
      const led = new THREE.Mesh(new THREE.BoxGeometry(len, 1.1, 0.3), new THREE.MeshStandardMaterial({ map: ledTex, emissive: '#ffffff', emissiveMap: ledTex, emissiveIntensity: 0.9 }))
      led.position.set(x, 0.55, z)
      led.rotation.y = rot
      leds.push(led)
      scene.add(led)
    }

    scene.add(new THREE.HemisphereLight('#9fb4ff', '#1a120a', 0.35))
    for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]] as const) {
      const tower = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.9, 46, 8), new THREE.MeshStandardMaterial({ color: '#3a3f4a' }))
      const tx = x * (WIDTH / 2 + 22), tz = z * (LENGTH / 2 + 22)
      tower.position.set(tx, 23, tz)
      const panel = new THREE.Mesh(new THREE.BoxGeometry(8, 4, 1), new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: '#fff6d8', emissiveIntensity: 2.5 }))
      panel.position.set(tx, 47, tz)
      panel.lookAt(0, 0, 0)
      const light = new THREE.SpotLight('#fff3dc', 2600, 260, Math.PI / 5, 0.5, 1.4)
      light.position.set(tx, 47, tz)
      light.target.position.set(0, 0, 0)
      light.castShadow = true
      light.shadow.mapSize.set(1024, 1024)
      light.shadow.bias = -0.0004
      scene.add(tower, panel, light, light.target)
    }

    const placed = spots(players)
    const clickable: THREE.Object3D[] = []
    const rings: THREE.Mesh[] = []
    for (const p of players) {
      const at = placed.get(p.player_id)
      if (!at) continue
      const club = clubColors(p.team_code)
      const fig = figure(club.primary, club.accent, p.position === 'GKP')
      fig.position.set(at[0], 0, at[1])
      fig.rotation.y = Math.PI
      fig.userData.player_id = p.player_id
      fig.traverse((o) => { o.userData.player_id = p.player_id })
      clickable.push(fig)
      const tag = plate(p.name, p.xp, p.captain)
      tag.position.set(at[0], 6.6, at[1])
      scene.add(fig, tag)
      if (p.captain || p.vice) {
        const ring = new THREE.Mesh(new THREE.TorusGeometry(2.4, 0.18, 8, 48), new THREE.MeshStandardMaterial({ color: p.captain ? '#e8a800' : '#cfcfcf', emissive: p.captain ? '#e8a800' : '#888888', emissiveIntensity: p.captain ? 1.2 : 0.4, metalness: 0.6, roughness: 0.3 }))
        ring.rotation.x = Math.PI / 2
        ring.position.set(at[0], 0.15, at[1])
        rings.push(ring)
        scene.add(ring)
      }
    }
    const ball = new THREE.Mesh(new THREE.SphereGeometry(0.55, 24, 16), new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: 0.35 }))
    ball.castShadow = true
    scene.add(ball)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.maxPolarAngle = Math.PI * 0.46
    controls.minDistance = 30
    controls.maxDistance = 190
    controls.target.set(0, 0, 8)
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.35

    const from = new THREE.Vector3(-150, 140, -170)
    const to = new THREE.Vector3(0, 52, 108)
    camera.position.copy(from)
    let t0: number | null = null
    let flying = true

    const ray = new THREE.Raycaster()
    const mouse = new THREE.Vector2()
    let downAt = 0
    const onDown = () => { downAt = performance.now() }
    const onUp = (e: PointerEvent) => {
      if (performance.now() - downAt > 250) return
      const r = renderer.domElement.getBoundingClientRect()
      mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
      ray.setFromCamera(mouse, camera)
      const hit = ray.intersectObjects(clickable, true)[0]
      if (hit?.object.userData.player_id) navigate(`/player/${hit.object.userData.player_id}`)
    }
    const onMove = (e: PointerEvent) => {
      const r = renderer.domElement.getBoundingClientRect()
      mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
      ray.setFromCamera(mouse, camera)
      renderer.domElement.style.cursor = ray.intersectObjects(clickable, true).length ? 'pointer' : 'grab'
    }
    renderer.domElement.addEventListener('pointerdown', onDown)
    renderer.domElement.addEventListener('pointerup', onUp)
    renderer.domElement.addEventListener('pointermove', onMove)
    controls.addEventListener('start', () => { flying = false; controls.autoRotate = false })

    let raf = 0
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick)
      if (flying) {
        if (t0 === null) t0 = now
        const k = Math.min((now - t0) / 3200, 1)
        const e = 1 - Math.pow(1 - k, 3)
        camera.position.lerpVectors(from, to, e)
        camera.lookAt(controls.target)
        if (k >= 1) flying = false
      } else {
        controls.update()
      }
      for (const r of rings) r.rotation.z = now / 900
      ledTex.offset.x = (now / 9000) % 1
      ball.position.set(Math.sin(now / 1400) * 1.5, 0.55 + Math.abs(Math.sin(now / 260)) * 1.6, 1.5 + Math.cos(now / 1400) * 1.5)
      renderer.render(scene, camera)
    }
    raf = requestAnimationFrame(tick)

    const onResize = () => {
      const nw = el.clientWidth
      renderer.setSize(nw, height)
      camera.aspect = nw / height
      camera.updateProjectionMatrix()
    }
    window.addEventListener('resize', onResize)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      controls.dispose()
      renderer.dispose()
      scene.traverse((o) => {
        const m = o as THREE.Mesh
        m.geometry?.dispose?.()
        const mat = m.material as THREE.Material | THREE.Material[] | undefined
        if (Array.isArray(mat)) mat.forEach((x) => x.dispose())
        else mat?.dispose?.()
      })
      el.removeChild(renderer.domElement)
    }
  }, [players, ticker, height, navigate])

  return <div ref={mount} className="w-full overflow-hidden" style={{ height }} />
}
