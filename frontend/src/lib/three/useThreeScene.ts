import { useEffect, useRef } from 'react'
import * as THREE from 'three'

/** One shared way to mount a three.js scene inside a React component -
 * before this, each 3D feature would reimplement its own renderer/resize/
 * animation-loop/cleanup boilerplate independently and drift (a missed
 * `dispose()` here, a missed resize observer there). Every 3D component in
 * this app goes through this hook.
 *
 * `setup` runs once against a fresh canvas + renderer + a real
 * `ResizeObserver`-driven size, returns a per-frame `render(size)` callback
 * plus an optional `dispose` for anything the caller allocated beyond what
 * three.js's own renderer/scene disposal already covers. Respects
 * `prefers-reduced-motion`: the animation loop still renders (data must
 * still show), it just skips continuous re-rendering when nothing is
 * animating - callers that need a static scene should render once from
 * `setup` and never call `requestAnimationFrame` again themselves. */
export interface ThreeSetupResult {
  render: (width: number, height: number) => void
  dispose?: () => void
}

export function useThreeScene(
  setup: (canvas: HTMLCanvasElement, renderer: THREE.WebGLRenderer) => ThreeSetupResult,
  deps: React.DependencyList,
) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))

    const result = setup(canvas, renderer)
    let frame = 0
    let stopped = false

    const resize = () => {
      const parent = canvas.parentElement
      if (!parent) return
      const { width, height } = parent.getBoundingClientRect()
      if (width === 0 || height === 0) return
      renderer.setSize(width, height, false)
      result.render(width, height)
    }

    const ro = new ResizeObserver(resize)
    if (canvas.parentElement) ro.observe(canvas.parentElement)
    resize()

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
    const loop = () => {
      if (stopped) return
      if (!reduced) {
        const parent = canvas.parentElement
        if (parent) {
          const { width, height } = parent.getBoundingClientRect()
          if (width > 0 && height > 0) result.render(width, height)
        }
      }
      frame = requestAnimationFrame(loop)
    }
    loop()

    return () => {
      stopped = true
      cancelAnimationFrame(frame)
      ro.disconnect()
      result.dispose?.()
      renderer.dispose()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return canvasRef
}
