import { Disclosure } from '@/components/ui/kit'

const USED: [string, string][] = [
  ['How good each team is', 'Dixon-Coles ratings fitted on five seasons of goals and xG, then set against the bookmakers\' match odds, which carry most of the weight. Every finished match refits it within one sync cycle.'],
  ['Who takes the chances', "A player's share of his team's xG and xA this season, shrunk toward his position, and FPL's own rate of credited assists by position."],
  ['Who is going to play', 'His own record of 90s, part-games and absences, the start chance on the lineup feed, official injury and suspension flags, confirmed teamsheets, and the news.'],
  ['What a fixture is worth', 'Goals expected for both sides, correlated in one simulated match: clean sheets, goals conceded, saves, bonus, defensive contributions. Doubles and blanks are summed or zeroed.'],
  ['Roles', 'Penalty, corner and free-kick duty from FPL\'s own notes, and role changes the match analyst has seen in two or more matches, at the size measured on 22,000 player-matches.'],
  ['The market', "Tonight's price change from a model fitted on the transfer and price history, and the cost of selling at FPL's half-rise rule."],
]

const TESTED: [string, string][] = [
  ['Recent form beating the season rate', 'Weighting recent matches more made the forecast worse at every half-life from 365 days to 30.'],
  ['A dip in the last three matches', 'Realised 0.97 to 1.05 times baseline next match. Only a collapse below a quarter of earlier output has carried.'],
  ['Scoring above or below xG', 'Does not carry from one match to the next (r +0.03). Chance creation does (r +0.48).'],
  ['A teammate missing', "Others' output rose about 7% only when a fifth or more of the team's chances were missing (90% interval +1% to +14%); team goals scored and conceded did not move for one or two absentees."],
  ['A midweek Champions League game', 'Regulars played 87% of their usual minutes the match before one, against 90% otherwise: inside the noise (618 matches).'],
  ['Short rest, squad rotation indices', 'Real but too small to move a decision.'],
  ['Team-specific home advantage', 'Does not persist from one season to the next (r −0.10 over 68 team-seasons), so one league-wide figure is used.'],
  ['Clean-sheet probability', 'Checked against 2,268 team-matches: 24.1% predicted, 23.1% happened, close at every decile.'],
]

function List({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="divide-y divide-divider">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-1 gap-1 py-2.5 md:grid-cols-[15rem_minmax(0,1fr)] md:gap-6">
          <dt className="text-[14px] font-semibold text-text">{k}</dt>
          <dd className="text-[14px] leading-snug text-text-muted">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

/** WHAT THE MODEL KNOWS ABOUT FOOTBALL - the factors it reads, and the ones that were measured and left out. A factor is only
 * added when the stored history says it carries; the second list is the evidence for what was refused. */
export function Knowledge() {
  return (
    <Disclosure title="What the model knows about football" summary="What it reads, and what was tested and left out">
      <div className="mb-2 text-[13px] font-medium text-text-faint">What it reads</div>
      <List rows={USED} />
      <div className="mb-2 mt-6 text-[13px] font-medium text-text-faint">Tested on the stored history and not used</div>
      <List rows={TESTED} />
    </Disclosure>
  )
}
