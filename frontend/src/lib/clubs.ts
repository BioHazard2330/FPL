/** Club colours, keyed by FPL team code. `primary` is the kit colour; `accent` is the version that reads on this app's dark
 * canvas (a navy or black kit would otherwise vanish). Used to give players and fixtures a club identity: a wash behind a face,
 * a rule under a name, a bar for a team's xG. */
const CLUBS: Record<number, { primary: string; accent: string }> = {
  3: { primary: '#EF0107', accent: '#FF4B52' }, // Arsenal
  7: { primary: '#7B003C', accent: '#95BFE5' }, // Aston Villa
  36: { primary: '#0057B8', accent: '#4F9BEA' }, // Brighton
  91: { primary: '#DA291C', accent: '#FF5A4D' }, // Bournemouth
  94: { primary: '#E30613', accent: '#FF4A55' }, // Brentford
  8: { primary: '#034694', accent: '#4A8FE0' }, // Chelsea
  9: { primary: '#59CBE8', accent: '#59CBE8' }, // Coventry
  31: { primary: '#1B458F', accent: '#E0476B' }, // Crystal Palace
  11: { primary: '#003399', accent: '#5C8CF0' }, // Everton
  54: { primary: '#DDDDDD', accent: '#E8E8E8' }, // Fulham
  88: { primary: '#F5A12D', accent: '#F5A12D' }, // Hull
  40: { primary: '#3A64A3', accent: '#6C9BE0' }, // Ipswich
  2: { primary: '#FFCD00', accent: '#FFCD00' }, // Leeds
  14: { primary: '#C8102E', accent: '#FF4D68' }, // Liverpool
  43: { primary: '#6CABDD', accent: '#6CABDD' }, // Man City
  1: { primary: '#DA291C', accent: '#FF5A4D' }, // Man Utd
  4: { primary: '#6F7378', accent: '#C9CDD2' }, // Newcastle
  17: { primary: '#DD0000', accent: '#FF4D4D' }, // Forest
  56: { primary: '#EB172B', accent: '#FF5C6B' }, // Sunderland
  6: { primary: '#132257', accent: '#8FA3D9' }, // Spurs
}

const FALLBACK = { primary: '#3A4352', accent: '#8892A2' }

export const clubColors = (teamCode: number | null | undefined) => (teamCode != null ? (CLUBS[teamCode] ?? FALLBACK) : FALLBACK)
