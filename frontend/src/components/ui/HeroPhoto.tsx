import { useState } from 'react'
import { playerPhotoUrl, shirtUrl } from '@/lib/api'

/** A player cut-out at poster size: the 500px Premier League image where it exists, the 110px one scaled up where it
 * does not (not every player has the large file), and the club shirt as the last resort. */
export function HeroPhoto({ code, teamCode, isGkp = false, className = '' }: { code?: number | null; teamCode: number | null; isGkp?: boolean; className?: string }) {
  const [step, setStep] = useState(0)
  const sources = [
    code ? playerPhotoUrl(code, 'hero') : null,
    code ? playerPhotoUrl(code, 'large') : null,
    shirtUrl(teamCode, isGkp, 220),
  ].filter((s): s is string => Boolean(s))
  const src = sources[step]
  if (!src) return null
  return (
    <img
      src={src}
      alt=""
      referrerPolicy="no-referrer"
      onError={() => setStep((s) => s + 1)}
      className={`object-contain object-bottom ${className}`}
    />
  )
}
