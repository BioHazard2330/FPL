import { cn } from "cn"

// Real, confirmed contrast bug (2026-09-08, direct user report - "blue
// screen for a long time"): `bg-muted` resolves to `--panel` (#12171F)
// against this app's `bg-void` page background (#0A0E14) - a ~7-value RGB
// difference, then halved again by `animate-pulse`'s 0.5 opacity trough.
// On a cold cache hit (FOOTBALL's league-wide signal scan can genuinely
// take 30s+ - see `football_payload.py`'s own docstring), that's 30 seconds
// of an all-but-invisible loading state on the near-black canvas - reads as
// a frozen/broken blank screen, not "still loading." `bg-raised` (#1A2029)
// is a real, deliberately more visible step up the same surface ladder.
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-md bg-raised", className)}
      {...props}
    />
  )
}

export { Skeleton }
