import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { disposeStadium, stadiumRenderer, stadiumScene } from '@/components/command/Stadium3D'

/** GOAL REPLAY - the goal as FotMob recorded it, in the floodlit ground: struck from its spot (x along the pitch to the
 * goal at 105, y across 0-68), into the net where it crossed the line (across and height in metres). The camera sits
 * behind the shooter and pushes in as the ball flies; the replay loops while the splash is up. */

const L = 105
const W = 68

export function GoalReplay({ x, y, gy, gz, label, width = 720, height = 340 }: {
  x: number; y: number; gy: number | null; gz: number | null; label: string; width?: number; height?: number
}) {
  const mount = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = mount.current
    if (!el) return
    const renderer = stadiumRenderer(el, width, height)
    const { scene, ledTex } = stadiumScene([label, 'GOAL', label, 'GOAL'])
    const camera = new THREE.PerspectiveCamera(38, width / height, 0.3, 500)
    const start = new THREE.Vector3(y - W / 2, 0.3, -(x - L / 2))
    const end = new THREE.Vector3((gy ?? W / 2) - W / 2, Math.max(0.3, Math.min(gz ?? 0.8, 2.3)), -L / 2 - 0.6)
    const mid = start.clone().lerp(end, 0.5)
    mid.y = Math.max(end.y, 0.4) + 0.35 + start.distanceTo(end) * 0.04
    const curve = new THREE.QuadraticBezierCurve3(start, mid, end)
    const ball = new THREE.Mesh(new THREE.SphereGeometry(0.3, 24, 16), new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: '#ffffff', emissiveIntensity: 0.5 }))
    ball.castShadow = true
    const trail = new THREE.Mesh(new THREE.TubeGeometry(curve, 60, 0.07, 8, false), new THREE.MeshBasicMaterial({ color: '#ffc400', transparent: true, opacity: 0.85 }))
    trail.geometry.setDrawRange(0, 0)
    const total = trail.geometry.index!.count
    scene.add(ball, trail)
    const camFrom = start.clone().add(new THREE.Vector3(0, 4.5, 14))
    const camTo = start.clone().lerp(end, 0.55).add(new THREE.Vector3(0, 2.5, 7))
    let raf = 0
    const t0 = performance.now()
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick)
      const cycle = ((now - t0) / 2600) % 1
      const k = Math.min(1, cycle / 0.55)
      const e = 1 - Math.pow(1 - k, 2)
      ball.position.copy(curve.getPoint(e))
      trail.geometry.setDrawRange(0, Math.floor((total / 3) * e) * 3)
      camera.position.lerpVectors(camFrom, camTo, Math.min(1, cycle / 0.75))
      camera.lookAt(end.x, 1.2, end.z)
      ledTex.offset.x = (now / 4000) % 1
      renderer.render(scene, camera)
    }
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      disposeStadium(renderer, scene)
      el.removeChild(renderer.domElement)
    }
  }, [x, y, gy, gz, label, width, height])

  return <div ref={mount} className="overflow-hidden border-2 border-[#ffc400] shadow-[8px_8px_0_#ff4614]" style={{ width, height }} />
}
