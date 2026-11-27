/** Numbers said in words (2026-11-27, the manager: "+0.2, -0.6 ... just doesn't make sense when I see it"). Every signed
 * figure on screen should say what it is a difference of and against what. */
const n1 = (v: number) => Math.abs(v).toFixed(1)

/** "0.6 pts ahead of the top 10k" / "0.6 pts behind the top 10k" / "level with the top 10k". */
export function vsTop10k(v: number): string {
  if (Math.abs(v) < 0.05) return 'level with the top 10k'
  return `${n1(v)} pts ${v > 0 ? 'ahead of' : 'behind'} the top 10k`
}

/** The short word for a gain or loss against the top 10k: "ahead" / "behind" / "level". */
export function aheadWord(v: number): string {
  return Math.abs(v) < 0.05 ? 'level' : v > 0 ? 'ahead' : 'behind'
}

/** A signed figure with its unit: "+0.4 pts", "−1.0 pts". */
export function pts(v: number, digits = 1): string {
  return `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(digits)} pts`
}

/** A move's worth: "1.6 pts more than rolling over 5 gameweeks" / "0.4 pts fewer ...". */
export function gainVsRoll(v: number, weeks: number): string {
  if (Math.abs(v) < 0.05) return `the same as rolling over ${weeks} gameweeks`
  return `${n1(v)} pts ${v > 0 ? 'more' : 'fewer'} than rolling over ${weeks} gameweeks`
}
