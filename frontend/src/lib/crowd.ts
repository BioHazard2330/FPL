import { useEffect, useRef, useState } from 'react'
import type { LiveMatchEvent } from '@/lib/types'

/** THE CROWD - a stadium synthesised in the browser with the Web Audio API (no recordings): a low murmur while the
 * sound is on, a roar that swells and falls when one of your players scores or assists (bigger for the armband), and a
 * groan for a red card. Off by default; the switch is the user gesture browsers require before audio may play. */

let ctx: AudioContext | null = null
let murmur: { gain: GainNode; src: AudioBufferSourceNode } | null = null

function noise(ac: AudioContext, seconds: number): AudioBuffer {
  const buf = ac.createBuffer(2, ac.sampleRate * seconds, ac.sampleRate)
  for (let c = 0; c < 2; c++) {
    const d = buf.getChannelData(c)
    let last = 0
    for (let i = 0; i < d.length; i++) {
      last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02
      d[i] = last * 3.5
    }
  }
  return buf
}

function crowdVoice(ac: AudioContext, centre: number, q: number): { input: AudioBufferSourceNode; out: GainNode } {
  const src = ac.createBufferSource()
  src.buffer = noise(ac, 4)
  src.loop = true
  const band = ac.createBiquadFilter()
  band.type = 'bandpass'
  band.frequency.value = centre
  band.Q.value = q
  const out = ac.createGain()
  src.connect(band).connect(out).connect(ac.destination)
  return { input: src, out }
}

export function roar(size = 1, groan = false) {
  if (!ctx) return
  const ac = ctx
  const t = ac.currentTime
  const layers = groan ? [[180, 1.2], [320, 1.6]] : [[420, 0.9], [900, 1.1], [1700, 1.4]]
  for (const [f, q] of layers) {
    const { input, out } = crowdVoice(ac, f, q)
    const peak = (groan ? 0.5 : 0.9) * size
    out.gain.setValueAtTime(0.0001, t)
    out.gain.exponentialRampToValueAtTime(peak, t + (groan ? 0.5 : 0.35))
    out.gain.setValueAtTime(peak, t + (groan ? 0.9 : 1.6) * size)
    out.gain.exponentialRampToValueAtTime(0.0001, t + (groan ? 2.2 : 4.2) * size)
    input.start(t)
    input.stop(t + 4.5 * size)
  }
  if (!groan) {
    const horn = ac.createOscillator()
    horn.type = 'sawtooth'
    horn.frequency.setValueAtTime(233, t + 0.2)
    const hg = ac.createGain()
    const lp = ac.createBiquadFilter()
    lp.type = 'lowpass'
    lp.frequency.value = 900
    hg.gain.setValueAtTime(0.0001, t)
    hg.gain.exponentialRampToValueAtTime(0.08 * size, t + 0.3)
    hg.gain.exponentialRampToValueAtTime(0.0001, t + 1.4)
    horn.connect(lp).connect(hg).connect(ac.destination)
    horn.start(t + 0.2)
    horn.stop(t + 1.5)
  }
}

function setOn(on: boolean) {
  if (on) {
    ctx = ctx ?? new AudioContext()
    void ctx.resume()
    if (!murmur) {
      const { input, out } = crowdVoice(ctx, 500, 0.7)
      out.gain.value = 0.06
      input.start()
      murmur = { gain: out, src: input }
    }
  } else if (murmur) {
    murmur.src.stop()
    murmur = null
  }
}

/** The switch, and the roar for each new goal, assist or red card among your players since the last poll. */
export function useCrowd(events: LiveMatchEvent[], captainId: number | null) {
  const [on, setState] = useState(false)
  const seen = useRef<Map<string, number> | null>(null)

  useEffect(() => {
    const now = new Map(events.map((e) => [`${e.player_id}:${e.kind}`, e.count]))
    if (seen.current && on) {
      let best: { size: number; groan: boolean } | null = null
      for (const e of events) {
        const before = seen.current.get(`${e.player_id}:${e.kind}`) ?? 0
        if (e.count <= before) continue
        const groan = e.kind === 'red_card'
        const size = groan ? 1 : (e.kind === 'goal' ? 1 : 0.7) * (e.player_id === captainId ? 1.25 : 1)
        if (!best || size > best.size) best = { size, groan }
      }
      if (best) roar(best.size, best.groan)
    }
    seen.current = now
  }, [events, captainId, on])

  useEffect(() => () => setOn(false), [])

  const toggle = () => {
    const next = !on
    setOn(next)
    setState(next)
    if (next) roar(0.6)
  }
  return { on, toggle }
}
