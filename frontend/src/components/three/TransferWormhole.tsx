/** A real CSS 3D flip for a transfer leg's OUT->IN shirt swap - the same
 * real `perspective`/`transform-style:preserve-3d`/`backface-visibility`
 * technique `FlipCard.tsx` already uses and this project already
 * live-verified, hover-driven here (pure CSS `group-hover`, no click state)
 * since this sits inline in a scrolling strategy rail rather than standing
 * alone. Deliberately restrained: real shirts on a real rotating plane, not
 * an invented portal/glow effect - the same lesson this session's away-days
 * map and travel-globe rejections already established (real recognizable
 * content beats abstract decoration). */
export function TransferWormhole({ outShirt, inShirt, outName, inName }: {
  outShirt: string | null
  inShirt: string | null
  outName: string
  inName: string
}) {
  return (
    <div
      className="group h-9 w-9 shrink-0 cursor-default [perspective:600px]"
      title={`${outName} → ${inName} (hover to flip)`}
    >
      <div className="relative h-full w-full transition-transform duration-500 [transform-style:preserve-3d] group-hover:[transform:rotateY(180deg)] motion-reduce:transition-none motion-reduce:group-hover:[transform:none]">
        <div className="absolute inset-0 flex items-center justify-center [backface-visibility:hidden]">
          {outShirt && <img src={outShirt} alt="" className="h-8 w-8 object-contain opacity-55 grayscale" />}
        </div>
        <div
          className="absolute inset-0 flex items-center justify-center [backface-visibility:hidden]"
          style={{ transform: 'rotateY(180deg)' }}
        >
          {inShirt && <img src={inShirt} alt="" className="h-8 w-8 object-contain" />}
        </div>
      </div>
    </div>
  )
}
