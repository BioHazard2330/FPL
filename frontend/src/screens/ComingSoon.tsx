/** Real, honest placeholder (2026-09-08, Phase 8.2 staged rollout) - this
 * screen's own JSON payload builder + React composition hasn't been built
 * yet (see docs/FRONTEND_MIGRATION_PLAN.md's staged rollout table). The old
 * Python-generated dashboard stays the real, working fallback for it until
 * then - linked here rather than showing a fake/empty screen. */
export function ComingSoon({ name, oldAnchor }: { name: string; oldAnchor: string }) {
  return (
    <div className="p-6">
      <h1 className="font-display text-2xl font-bold text-text">{name}</h1>
      <p className="mt-2 text-text-muted">Not built yet. The old dashboard still has the working version.</p>
      <a
        className="mt-4 inline-block bg-pitch-green px-4 py-2 font-semibold text-pitch-green-ink"
        href={`/dashboard.html#${oldAnchor}`}
      >
        Open {name} on the old dashboard
      </a>
    </div>
  )
}
