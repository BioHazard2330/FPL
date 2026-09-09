/** The real FPL 1-5 fixture-difficulty scale, in one place.
 *
 * Every screen that shows a fixture must colour it identically - a fixture
 * that reads "easy green" on the Football ticker and neutral grey on the
 * pitch is the same defect as two screens disagreeing on a number. The
 * values are the backend's own `difficulty` field (`models/fixtures.py::
 * team_fixture_ticker`, FPL's own official FDR convention: the opponent's
 * overall strength at the venue they are playing), never a re-derivation.
 */
export const FDR_FILL: Record<number, string> = {
  1: 'bg-pitch-green text-pitch-green-ink',
  2: 'bg-pitch-green/70 text-pitch-green-ink',
  3: 'bg-raised text-text-muted',
  4: 'bg-alert-red/70 text-alert-red-ink',
  5: 'bg-alert-red text-alert-red-ink',
}

/** Text-only variant, for places where a filled block would be too loud
 * (inside a dense table row, under a player's name on the pitch). */
export const FDR_INK: Record<number, string> = {
  1: 'text-pitch-green',
  2: 'text-pitch-green',
  3: 'text-text-muted',
  4: 'text-alert-red',
  5: 'text-alert-red',
}

export const FDR_EDGE: Record<number, string> = {
  1: 'border-pitch-green',
  2: 'border-pitch-green/70',
  3: 'border-divider',
  4: 'border-alert-red/70',
  5: 'border-alert-red',
}

export function fdrFill(d: number | null | undefined): string {
  return d ? (FDR_FILL[d] ?? 'bg-raised text-text-muted') : 'bg-raised text-text-muted'
}

export function fdrInk(d: number | null | undefined): string {
  return d ? (FDR_INK[d] ?? 'text-text-muted') : 'text-text-muted'
}

/** Mean difficulty across a real run of fixtures. Arithmetic over values
 * the reader can already see on screen, never a new model output. `null`
 * for an empty run rather than a fabricated neutral 3. */
export function runPressure(fixtures: { difficulty: number }[]): number | null {
  if (fixtures.length === 0) return null
  return fixtures.reduce((a, f) => a + f.difficulty, 0) / fixtures.length
}

export function pressureInk(p: number | null): string {
  if (p === null) return 'text-text-faint'
  return p <= 2.4 ? 'text-pitch-green' : p >= 3.6 ? 'text-alert-red' : 'text-text-muted'
}
