/** Real Premier League stadium coordinates, keyed by the same `team_code`
 * every other football-object component already keys off (`crestUrl`,
 * `shirtUrl`, `FixtureEntry.opponent_code`, etc). Static, one-time reference
 * data - not a live source, never re-fetched - used only for the travel
 * globe's real flight-arc endpoints.
 *
 * Sourced 2026-09-10 from Wikipedia's "List of Premier League stadiums"
 * decimal coordinates, cross-checked against each club's own dedicated
 * article. One real error was found and corrected in that process: the
 * summary table's own Everton row gives 53.71417,-3.00778 (verified wrong -
 * that's roughly the latitude of Preston, not Liverpool), while Everton's
 * own Hill Dickinson Stadium article and independent sources agree on
 * 53.4251,-3.0028 (consistent with Anfield's real 53.43083, a few hundred
 * metres away on the same stretch of dock). The corrected value is used
 * here. Every other row matched across both the summary table and a second
 * independent stadium-coordinates dataset without discrepancy. */
export interface StadiumLocation {
  name: string
  lat: number
  lng: number
}

export const STADIUMS: Record<number, StadiumLocation> = {
  3: { name: 'Emirates Stadium', lat: 51.555, lng: -0.10861 }, // Arsenal
  7: { name: 'Villa Park', lat: 52.50917, lng: -1.88472 }, // Aston Villa
  91: { name: 'Dean Court', lat: 50.73528, lng: -1.83833 }, // Bournemouth
  94: { name: 'Brentford Community Stadium', lat: 51.490825, lng: -0.2887 }, // Brentford
  36: { name: 'Falmer Stadium', lat: 50.861822, lng: -0.083278 }, // Brighton
  8: { name: 'Stamford Bridge', lat: 51.48167, lng: -0.19111 }, // Chelsea
  9: { name: 'Coventry Building Society Arena', lat: 52.44806, lng: -1.49556 }, // Coventry City
  31: { name: 'Selhurst Park', lat: 51.39833, lng: -0.08556 }, // Crystal Palace
  11: { name: 'Hill Dickinson Stadium', lat: 53.4251, lng: -3.0028 }, // Everton (corrected, see module docstring)
  54: { name: 'Craven Cottage', lat: 51.475, lng: -0.22167 }, // Fulham
  88: { name: 'MKM Stadium', lat: 53.74611, lng: -0.3675 }, // Hull City
  40: { name: 'Portman Road', lat: 52.055, lng: 1.14472 }, // Ipswich Town
  2: { name: 'Elland Road', lat: 53.77778, lng: -1.57222 }, // Leeds
  14: { name: 'Anfield', lat: 53.43083, lng: -2.96083 }, // Liverpool
  43: { name: 'Etihad Stadium', lat: 53.48306, lng: -2.20028 }, // Man City
  1: { name: 'Old Trafford', lat: 53.46306, lng: -2.29139 }, // Man Utd
  4: { name: "St James' Park", lat: 54.97556, lng: -1.62167 }, // Newcastle
  17: { name: 'City Ground', lat: 52.94, lng: -1.13278 }, // Nott'm Forest
  6: { name: 'Tottenham Hotspur Stadium', lat: 51.60472, lng: -0.06639 }, // Spurs
  56: { name: 'Stadium of Light', lat: 54.91444, lng: -1.38833 }, // Sunderland
}
