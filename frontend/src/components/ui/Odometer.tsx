/** ODOMETER - a number whose digits roll to their new value like a stadium scoreboard: each digit is a column of 0-9
 * shifted to the right one, so 56 to 62 turns both wheels. Non-digit characters (sign, comma, point) sit still. */
export function Odometer({ value, className = '', duration = 900 }: { value: string | number; className?: string; duration?: number }) {
  const text = String(value)
  return (
    <span className={`odo ${className}`} aria-label={text} role="text">
      {[...text].map((ch, i) => {
        const key = `${text.length - i}`
        if (!/[0-9]/.test(ch)) return <span key={key} className="odo-static">{ch}</span>
        const d = Number(ch)
        return (
          <span key={key} className="odo-cell">
            <span className="odo-strip" style={{ transform: `translateY(-${d * 10}%)`, transitionDuration: `${duration}ms` }}>
              {'0123456789'.split('').map((n) => <span key={n}>{n}</span>)}
            </span>
          </span>
        )
      })}
    </span>
  )
}
