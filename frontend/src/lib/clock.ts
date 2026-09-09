import { useEffect, useState } from 'react'

/** THE SEASON CLOCK.
 *
 * FPL is a clock: deadline, lock, live, settle, repeat. Until 2026-09-09 no
 * part of this interface knew what time it was - it rendered identically at
 * 3am on a Tuesday and with six matches live and your captain on the pitch.
 * `events.deadline_time` had been synced since the first week of the project
 * and had never once been read by the frontend.
 *
 * Everything here derives from two real backend values, both on the existing
 * fast-poll channel: `gw.state` (the real `models/gw_lifecycle.py` state
 * machine) and `gw.next_deadline_time` (FPL's own UTC deadline string). No
 * phase is guessed from the wall clock alone - the lifecycle state always
 * wins, and the countdown only refines it.
 */

export type Phase =
  | 'BUILD_UP'
  | 'IMMINENT'
  | 'FINAL_CALL'
  | 'LOCKED'
  | 'LIVE'
  | 'SETTLING'
  | 'REVIEW'
  | 'UNKNOWN'

export interface PhaseInfo {
  phase: Phase
  /** Short broadcast word for the bar. */
  label: string
  /** What this phase means for what the user can actually do. */
  sub: string
  /** Semantic accent. Red = act now or it is happening now. */
  ink: string
  fill: string
  /** True when the squad can still be changed. Drives what Command leads with. */
  actionable: boolean
  /** True when football is being played right now. */
  live: boolean
}

const HOUR = 3600_000

export const PHASES: Record<Phase, Omit<PhaseInfo, 'phase'>> = {
  BUILD_UP: {
    label: 'Build-up',
    sub: 'plan freely - nothing locks yet',
    ink: 'text-text-muted',
    fill: 'bg-raised text-text',
    actionable: true,
    live: false,
  },
  IMMINENT: {
    label: 'Deadline day',
    sub: 'transfers and armband still open',
    ink: 'text-broadcast-gold',
    fill: 'bg-broadcast-gold text-broadcast-gold-ink',
    actionable: true,
    live: false,
  },
  FINAL_CALL: {
    label: 'Final call',
    sub: 'last hours to move - check the XI',
    ink: 'text-alert-red',
    fill: 'bg-alert-red text-alert-red-ink',
    actionable: true,
    live: false,
  },
  LOCKED: {
    label: 'Locked',
    sub: 'squad is set - nothing can change now',
    ink: 'text-text-faint',
    fill: 'bg-raised text-text-muted',
    actionable: false,
    live: false,
  },
  LIVE: {
    label: 'Live',
    sub: 'matches in progress',
    ink: 'text-alert-red',
    fill: 'bg-alert-red text-alert-red-ink',
    actionable: false,
    live: true,
  },
  SETTLING: {
    label: 'Settling',
    sub: 'bonus and DefCon still provisional',
    ink: 'text-broadcast-gold',
    fill: 'bg-broadcast-gold text-broadcast-gold-ink',
    actionable: false,
    live: false,
  },
  REVIEW: {
    label: 'Review',
    sub: 'gameweek closed - next one is open',
    ink: 'text-pitch-green',
    fill: 'bg-pitch-green text-pitch-green-ink',
    actionable: true,
    live: false,
  },
  UNKNOWN: {
    label: 'Unknown',
    sub: 'lifecycle state unavailable',
    ink: 'text-text-faint',
    fill: 'bg-raised text-text-muted',
    actionable: true,
    live: false,
  },
}

/** The real backend lifecycle state decides the phase; the countdown only
 * splits PRE_DEADLINE into how urgent it actually is. A live match overrides
 * everything, because football being played now outranks any cached state. */
export function derivePhase(
  gwState: string | null | undefined,
  msToDeadline: number | null,
  liveMatches: number,
): PhaseInfo {
  let phase: Phase
  if (liveMatches > 0 || gwState === 'LIVE') {
    phase = 'LIVE'
  } else if (gwState === 'LOCKED') {
    phase = 'LOCKED'
  } else if (gwState === 'NEXT_GW_ANALYSIS') {
    phase = 'SETTLING'
  } else if (gwState === 'READY_FOR_NEXT_DEADLINE') {
    phase = 'REVIEW'
  } else if (gwState === 'PRE_DEADLINE') {
    phase = msToDeadline === null ? 'BUILD_UP' : msToDeadline < 3 * HOUR ? 'FINAL_CALL' : msToDeadline < 24 * HOUR ? 'IMMINENT' : 'BUILD_UP'
  } else {
    phase = 'UNKNOWN'
  }
  return { phase, ...PHASES[phase] }
}

export interface Countdown {
  totalMs: number
  days: number
  hours: number
  minutes: number
  seconds: number
  expired: boolean
}

export function splitCountdown(ms: number): Countdown {
  const clamped = Math.max(0, ms)
  const totalSeconds = Math.floor(clamped / 1000)
  return {
    totalMs: ms,
    days: Math.floor(totalSeconds / 86400),
    hours: Math.floor((totalSeconds % 86400) / 3600),
    minutes: Math.floor((totalSeconds % 3600) / 60),
    seconds: totalSeconds % 60,
    expired: ms <= 0,
  }
}

/** Ticks locally once a second against a real backend timestamp. The clock
 * is never fetched - a countdown computed server-side is stale the instant
 * it is serialized. Under the last hour it ticks every second; further out
 * it settles to once a minute, because a day-scale countdown re-rendering
 * 60 times a minute is pure waste. */
export function useCountdown(iso: string | null | undefined): Countdown | null {
  const target = iso ? new Date(iso).getTime() : null
  const valid = target !== null && !Number.isNaN(target)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!valid) return
    const remaining = target - Date.now()
    const interval = remaining < HOUR ? 1000 : 60_000
    const id = setInterval(() => setNow(Date.now()), interval)
    return () => clearInterval(id)
  }, [target, valid])

  if (!valid) return null
  return splitCountdown(target - now)
}

/** Broadcast formatting: the largest two units that still matter. "2d 04h",
 * "6h 12m", "04:31" in the final hour. Never "0d 0h 4m 31s". */
export function formatCountdown(c: Countdown): string {
  if (c.expired) return '00:00'
  if (c.days > 0) return `${c.days}d ${String(c.hours).padStart(2, '0')}h`
  if (c.hours > 0) return `${c.hours}h ${String(c.minutes).padStart(2, '0')}m`
  return `${String(c.minutes).padStart(2, '0')}:${String(c.seconds).padStart(2, '0')}`
}
