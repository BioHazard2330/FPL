import { crestUrl } from '@/lib/api'
import { clubColors } from '@/lib/clubs'
import { PlayerPhoto } from '@/components/ui/PlayerPhoto'

const SIZES = {
  sm: { box: 'h-14 w-11', crest: 'size-4' },
  md: { box: 'h-[4.5rem] w-14', crest: 'size-5' },
  lg: { box: 'h-24 w-[4.75rem]', crest: 'size-6' },
  xl: { box: 'h-32 w-[6.25rem]', crest: 'size-7' },
  '2xl': { box: 'h-44 w-36', crest: 'size-9' },
} as const

/** A player's face on his club's colour: the official headshot over a wash of the kit colour, club crest at the corner, a
 * thin rule in the club's accent underneath. It is what makes a transfer read as two people moving between two clubs rather
 * than two rows of text. `muted` drops the colour for the player going out. */
export function Face({
  code,
  teamCode,
  isGkp = false,
  size = 'md',
  muted = false,
  badge,
}: {
  code?: number | null
  teamCode: number | null
  isGkp?: boolean
  size?: keyof typeof SIZES
  muted?: boolean
  badge?: React.ReactNode
}) {
  const c = clubColors(teamCode)
  const crest = crestUrl(teamCode)
  const s = SIZES[size]
  return (
    <div className={`relative shrink-0 ${muted ? 'opacity-75 grayscale' : ''}`}>
      <div
        className={`${s.box} overflow-hidden rounded-lg`}
        style={{ background: `linear-gradient(165deg, color-mix(in srgb, ${c.primary} 62%, #0b0e13) 0%, color-mix(in srgb, ${c.primary} 16%, #12161d) 100%)` }}
      >
        <PlayerPhoto code={code} teamCode={teamCode} isGkp={isGkp} className={`${s.box} rounded-lg`} bare />
      </div>
      <div className="absolute inset-x-0 -bottom-px h-[3px] rounded-b-lg" style={{ background: c.accent }} />
      {crest && <img src={crest} alt="" className={`absolute -right-1.5 -top-1.5 ${s.crest} rounded-full bg-panel p-px ring-2 ring-panel`} />}
      {badge && <div className="absolute -bottom-2 left-1/2 -translate-x-1/2">{badge}</div>}
    </div>
  )
}
