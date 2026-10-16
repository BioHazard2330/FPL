import { useState } from 'react'
import { playerPhotoUrl, shirtUrl } from '@/lib/api'

/** The player's official Premier League headshot, keyed by player code (so a
 * transfer never leaves it stale), falling back to the club shirt if the code
 * is missing or the image fails. The headshot is a transparent PNG with the
 * head and shoulders at the top, so it sits bottom-aligned on a flat tile and
 * is cropped by the tile, never stretched. */
export function PlayerPhoto({ code, teamCode, isGkp = false, className = 'h-16 w-14', muted = false }: {
  code?: number | null
  teamCode: number | null
  isGkp?: boolean
  className?: string
  muted?: boolean
}) {
  const [failed, setFailed] = useState(false)
  const photo = code && !failed ? playerPhotoUrl(code) : null
  if (photo) {
    return (
      <div className={`${className} relative shrink-0 overflow-hidden bg-raised ${muted ? 'opacity-80' : ''}`}>
        <img
          src={photo}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="absolute inset-x-0 bottom-0 h-full w-full object-cover object-top"
        />
      </div>
    )
  }
  const shirt = shirtUrl(teamCode, isGkp, 110)
  return shirt ? <img src={shirt} alt="" className={`${className} shrink-0 object-contain`} /> : <div className={`${className} shrink-0 bg-raised`} />
}
