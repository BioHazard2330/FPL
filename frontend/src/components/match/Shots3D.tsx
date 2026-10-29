import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { disposeStadium, stadiumRenderer, stadiumScene } from '@/components/command/Stadium3D'
import type { StoryShot } from '@/lib/types'

/** EVERY SHOT, IN THE AIR - the match's shots replayed in minute order in the floodlit ground. Each flies from where it
 * was struck to where it crossed the goal line (FotMob's own goal-mouth point: across and height in metres), the tube's
 * thickness its xG; goals land gold and burst, saves blue, the woodwork white, misses fade to grey. Home attacks the
 * far goal, away the near one, as on the 2D replay. A shot with no goal-line point is left on the turf as a dot. */

const L = 105
const W = 68
const FLIGHT_MS = 900
const GAP_MS = 320

const TONE: Record<string, string> = { Goal: '#ffc400', AttemptSaved: '#4f8bff', Post: '#ffffff', Miss: '#8a8f98' }

function toWorld(side: 'home' | 'away', x: number, y: number): [number, number] {
  const px = side === 'home' ? x : L - x
  const py = side === 'home' ? y : W - y
  return [py - W / 2, -(px - L / 2)]
}

export function Shots3D({ shots, homeShort, awayShort, height = 520 }: { shots: StoryShot[]; homeShort: string; awayShort: string; height?: number }) {
  const mount = useRef<HTMLDivElement>(null)
  const [minute, setMinute] = useState<number | null>(null)
  const [score, setScore] = useState<[number, number]>([0, 0])
  const [run, setRun] = useState(0)

  useEffect(() => {
    const el = mount.current
    if (!el) return
    const usable = shots.filter((s) => s.x !== null && s.y !== null)
    const w = el.clientWidth
    const renderer = stadiumRenderer(el, w, height)
    const { scene, ledTex } = stadiumScene([`${homeShort} v ${awayShort}`, `${usable.length} shots`, `${usable.reduce((a, s) => a + s.xg, 0).toFixed(2)} xG`, 'every shot in the air'])
    const camera = new THREE.PerspectiveCamera(42, w / height, 0.5, 600)
    camera.position.set(-80, 46, 0)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.maxPolarAngle = Math.PI * 0.47
    controls.minDistance = 20
    controls.maxDistance = 190
    controls.target.set(0, 0, 0)

    const flights = usable.map((s) => {
      const [sx, sz] = toWorld(s.side, s.x!, s.y!)
      const hasMouth = s.gy !== null && s.gy !== undefined && s.gz !== null && s.gz !== undefined
      const goalZ = s.side === 'home' ? -L / 2 : L / 2
      const [ex] = hasMouth ? toWorld(s.side, L, s.gy!) : [sx]
      const end = new THREE.Vector3(ex, hasMouth ? Math.max(0.15, s.gz!) : 0.2, goalZ)
      const start = new THREE.Vector3(sx, 0.25, sz)
      const dist = start.distanceTo(end)
      const header = (s.type ?? '').toLowerCase().includes('head')
      const loft = header ? 2.2 : Math.max(end.y * 0.6, 0.4 + dist * 0.035)
      const mid = start.clone().lerp(end, 0.5)
      mid.y = (header ? 2.2 : 0.25) + loft
      const curve = new THREE.QuadraticBezierCurve3(header ? new THREE.Vector3(sx, 2.1, sz) : start, mid, end)
      const tone = TONE[s.o ?? 'Miss'] ?? TONE.Miss
      const goal = s.o === 'Goal'
      const tube = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 48, 0.13 + Math.sqrt(s.xg) * 0.55, 8, false),
        new THREE.MeshStandardMaterial({ color: tone, emissive: tone, emissiveIntensity: goal ? 1.4 : 0.45, transparent: true, opacity: goal ? 0.95 : s.o === 'Miss' ? 0.4 : 0.75 }),
      )
      tube.geometry.setDrawRange(0, 0)
      const spot = new THREE.Mesh(new THREE.CircleGeometry(0.35 + Math.sqrt(s.xg) * 1.6, 24), new THREE.MeshBasicMaterial({ color: tone, transparent: true, opacity: 0 }))
      spot.rotation.x = -Math.PI / 2
      spot.position.set(sx, 0.04, sz)
      scene.add(tube, spot)
      return { s, curve, tube, spot, goal, hasMouth, total: tube.geometry.index!.count }
    })

    const ball = new THREE.Mesh(new THREE.SphereGeometry(0.42, 20, 14), new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: '#ffffff', emissiveIntensity: 0.4 }))
    ball.visible = false
    scene.add(ball)
    const bursts: { pts: THREE.Points; vel: Float32Array; born: number }[] = []
    const burst = (at: THREE.Vector3, now: number) => {
      const n = 160
      const pos = new Float32Array(n * 3)
      const vel = new Float32Array(n * 3)
      for (let i = 0; i < n; i++) {
        pos.set([at.x, at.y, at.z], i * 3)
        const v = new THREE.Vector3(Math.random() - 0.5, Math.random() * 0.9, Math.random() - 0.5).normalize().multiplyScalar(6 + Math.random() * 10)
        vel.set([v.x, v.y, v.z], i * 3)
      }
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
      const pts = new THREE.Points(g, new THREE.PointsMaterial({ color: '#ffd23f', size: 0.5, transparent: true }))
      scene.add(pts)
      bursts.push({ pts, vel, born: now })
    }

    let t0: number | null = null
    let shown = -1
    let home = 0, away = 0
    let raf = 0
    let last = performance.now()
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick)
      const dt = Math.min((now - last) / 1000, 0.05)
      last = now
      if (t0 === null) t0 = now + 600
      const elapsed = now - t0
      const idx = Math.floor(elapsed / (FLIGHT_MS + GAP_MS))
      const k = Math.min(1, (elapsed - idx * (FLIGHT_MS + GAP_MS)) / FLIGHT_MS)
      for (let i = 0; i < flights.length; i++) {
        const f = flights[i]
        if (i < idx) { f.tube.geometry.setDrawRange(0, f.total); (f.spot.material as THREE.MeshBasicMaterial).opacity = 0.55 }
      }
      if (elapsed >= 0 && idx < flights.length) {
        const f = flights[idx]
        if (shown !== idx) {
          shown = idx
          setMinute(f.s.m)
        }
        const e = 1 - Math.pow(1 - k, 2)
        f.tube.geometry.setDrawRange(0, Math.floor((f.total / 3) * e) * 3)
        ;(f.spot.material as THREE.MeshBasicMaterial).opacity = 0.55
        ball.visible = f.hasMouth
        ball.position.copy(f.curve.getPoint(e))
        if (k >= 1 && !f.tube.userData.done) {
          f.tube.userData.done = true
          if (f.goal) {
            burst(f.curve.getPoint(1), now)
            if (f.s.side === 'home') home++
            else away++
            setScore([home, away])
          }
        }
      } else if (idx >= flights.length) {
        ball.visible = false
        controls.autoRotate = true
      }
      for (const b of bursts) {
        const age = (now - b.born) / 1000
        const pos = b.pts.geometry.getAttribute('position') as THREE.BufferAttribute
        for (let i = 0; i < pos.count; i++) {
          b.vel[i * 3 + 1] -= 18 * dt
          pos.setXYZ(i, pos.getX(i) + b.vel[i * 3] * dt, Math.max(0.05, pos.getY(i) + b.vel[i * 3 + 1] * dt), pos.getZ(i) + b.vel[i * 3 + 2] * dt)
        }
        pos.needsUpdate = true
        ;(b.pts.material as THREE.PointsMaterial).opacity = Math.max(0, 1 - age / 2.2)
      }
      ledTex.offset.x = (now / 9000) % 1
      controls.update()
      renderer.render(scene, camera)
    }
    raf = requestAnimationFrame(tick)
    setScore([0, 0])
    setMinute(null)

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
      disposeStadium(renderer, scene)
      el.removeChild(renderer.domElement)
    }
  }, [shots, homeShort, awayShort, height, run])

  return (
    <div className="relative border-2 border-ink shadow-[6px_6px_0_var(--ink)]">
      <div ref={mount} className="w-full overflow-hidden" style={{ height }} />
      <div className="pointer-events-none absolute left-4 top-4 flex items-center gap-0 font-display font-black uppercase">
        <span className="bg-pitch-green px-2.5 py-1 text-[15px] text-paper">{homeShort}</span>
        <span className="bg-paper px-3 py-1 text-[20px] tabular text-ink">{score[0]}–{score[1]}</span>
        <span className="bg-broadcast-blue px-2.5 py-1 text-[15px] text-paper">{awayShort}</span>
        <span className="ml-2 bg-ink px-2.5 py-1 text-[15px] tabular text-[#ffc400]">{minute !== null ? `${minute}'` : 'KO'}</span>
      </div>
      <div className="pointer-events-none absolute bottom-3 left-4 flex gap-3 text-[11px] font-bold uppercase tracking-[0.12em] text-paper/80">
        {Object.entries({ goal: TONE.Goal, saved: TONE.AttemptSaved, woodwork: TONE.Post, miss: TONE.Miss }).map(([k, c]) => (
          <span key={k} className="flex items-center gap-1.5"><span className="inline-block size-2.5" style={{ background: c }} />{k}</span>
        ))}
        <span className="text-paper/55">thickness = xG · drag to orbit</span>
      </div>
      <button type="button" onClick={() => setRun((r) => r + 1)} className="absolute right-4 top-4 border-2 border-ink bg-paper px-3 py-1 font-display text-[13px] font-black uppercase text-ink shadow-[3px_3px_0_var(--ink)] hover:bg-spot">
        Replay
      </button>
    </div>
  )
}
