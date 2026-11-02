/** Weather for a kickoff, from a WMO weather code (Open-Meteo): a small drawn icon and a plain label. */

export type WeatherKind = 'clear' | 'partly' | 'cloud' | 'fog' | 'drizzle' | 'rain' | 'snow' | 'storm'

export function weatherKind(code: number | null | undefined): WeatherKind | null {
  if (code === null || code === undefined) return null
  if (code === 0) return 'clear'
  if (code <= 2) return 'partly'
  if (code === 3) return 'cloud'
  if (code === 45 || code === 48) return 'fog'
  if (code >= 51 && code <= 57) return 'drizzle'
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return 'rain'
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return 'snow'
  if (code >= 95) return 'storm'
  return 'cloud'
}

export const WEATHER_LABEL: Record<WeatherKind, string> = {
  clear: 'Clear', partly: 'Partly cloudy', cloud: 'Overcast', fog: 'Fog', drizzle: 'Drizzle', rain: 'Rain', snow: 'Snow', storm: 'Thunderstorm',
}

export function WeatherIcon({ code, className = 'size-6' }: { code: number | null | undefined; className?: string }) {
  const kind = weatherKind(code)
  if (!kind) return null
  const sun = <g><circle cx="10" cy="10" r="4.2" fill="var(--broadcast-gold)" stroke="var(--ink)" strokeWidth="1.4" />{[0, 45, 90, 135, 180, 225, 270, 315].map((a) => <line key={a} x1="10" y1="2.2" x2="10" y2="4" stroke="var(--ink)" strokeWidth="1.4" strokeLinecap="round" transform={`rotate(${a} 10 10)`} />)}</g>
  const cloud = (dx = 0, dy = 0, fill = 'var(--paper)') => (
    <path transform={`translate(${dx} ${dy})`} d="M7 19h11a4 4 0 0 0 .4-8 5.5 5.5 0 0 0-10.6 1.4A3.4 3.4 0 0 0 7 19Z" fill={fill} stroke="var(--ink)" strokeWidth="1.4" strokeLinejoin="round" />
  )
  const drops = (n: number, color = 'var(--broadcast-blue)') => Array.from({ length: n }, (_, i) => (
    <line key={i} x1={9 + i * 4} y1="20.5" x2={8 + i * 4} y2="23" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
  ))
  return (
    <svg viewBox="0 0 26 26" className={className} role="img" aria-label={WEATHER_LABEL[kind]}>
      {kind === 'clear' && <g transform="translate(3 3)">{sun}</g>}
      {kind === 'partly' && <>{sun}{cloud(1, 1)}</>}
      {(kind === 'cloud' || kind === 'fog') && cloud(0, 0, 'var(--raised)')}
      {kind === 'fog' && [21, 24].map((y) => <line key={y} x1="6" y1={y} x2="20" y2={y} stroke="var(--ink)" strokeWidth="1.3" strokeDasharray="2 2" />)}
      {kind === 'drizzle' && <>{cloud(0, -2, 'var(--raised)')}{drops(2)}</>}
      {kind === 'rain' && <>{cloud(0, -2, 'var(--raised)')}{drops(3)}</>}
      {kind === 'snow' && <>{cloud(0, -2, 'var(--raised)')}{[9, 13, 17].map((x) => <circle key={x} cx={x} cy="22" r="1.2" fill="var(--ink)" />)}</>}
      {kind === 'storm' && <>{cloud(0, -2, 'var(--text-faint)')}<path d="M13 17l-2.5 4h3l-2 4" fill="none" stroke="var(--broadcast-gold)" strokeWidth="1.8" strokeLinejoin="round" /></>}
    </svg>
  )
}
