import { Disclosure } from '@/components/ui/kit'

const USED: [string, string][] = [
  ['How good each team is', 'Dixon-Coles ratings fitted on five seasons of goals and xG, then set against the bookmakers\' match odds, which carry most of the weight. Every finished match refits it within one sync cycle.'],
  ['Who takes the chances', "A player's share of his team's xG and xA this season, shrunk toward his position, and FPL's own rate of credited assists by position."],
  ['Who is going to play', "His own record of 90s, part-games and absences, the start chance on the lineup feed, official injury and suspension flags, the match-day squad sheet (eleven, bench or neither list) and FotMob's injury and return notes, and the news."],
  ["The lineup feed's start chance", "Blended half and half with the player's own record of 60-minute matches (fitted on 216 finished team matches: the old discount-only rule predicted 46% against 57% realised, the blend is within a few points in every band). It can lift a player the record undersells and cannot undo an injury doubt."],
  ['Left out of the match-day squad', "A regular outside the squad last match plays 60 minutes next match about a quarter of the time (16 cases), so the next match is capped at 0.8x. A bench seat is not capped: the feed's chance already carries it."],
  ['When an injured player is back', "FPL's stated return date, else FotMob's phrase, else how long injuries of this kind have lasted in this database: each match is weighed on its own, not zero for the whole window."],
  ['Yellow-card bans', "Five bookings by a club's 19th league match is a one-match ban (ten by the 32nd, two). Each player's booking rate (this season leaned on his own last season, which forecast bookings better than the position average over four seasons) and remaining fixtures give the chance he serves a ban in each match, and that share of his minutes is taken out before it happens, not after FPL flags it."],
  ['When to play the chips', 'A bench boost or triple captain still in hand is priced in every gameweek left in its window along the squad the plan expects to hold; the best week is the recommendation. A chip that expires unused is worth nothing.'],
  ['What a fixture is worth', 'Goals expected for both sides, correlated in one simulated match: clean sheets, goals conceded, saves, bonus, defensive contributions. Doubles and blanks are summed or zeroed. Replayed over five past seasons, reading how many matches each club plays added 420 points to the same transfer plan, and the opponent on top of that another 58 (ahead in 13 of 20 season runs across four planning horizons).'],
  ['Roles', 'Penalty, corner and free-kick duty from FPL\'s own notes, and role changes the match analyst has seen in two or more matches, at the size measured on 22,000 player-matches.'],
  ['The market', "Tonight's price change from a model fitted on the transfer and price history, and the cost of selling at FPL's half-rise rule."],
]

const TESTED: [string, string][] = [
  ['Planning further ahead', 'Replayed with the plan looking 3, 6, 9 and 15 gameweeks ahead: 6,588, 6,658, 6,688 and 6,811 points over five seasons. Six against nine is inside the noise, and fifteen is further than a projection holds up live, so the decision stays at five gameweeks with an eight-gameweek road ahead.'],
  ['Recent form beating the season rate', 'Weighting recent matches more made the forecast worse at every half-life from 365 days to 30.'],
  ['A dip in the last three matches', 'Realised 0.97 to 1.05 times baseline next match. Only a collapse below a quarter of earlier output has carried.'],
  ['Scoring above or below xG', 'Does not carry from one match to the next (r +0.03). Chance creation does (r +0.48).'],
  ['A teammate missing', "Others' output rose about 7% only when a fifth or more of the team's chances were missing (90% interval +1% to +14%); team goals scored and conceded did not move for one or two absentees."],
  ['A midweek Champions League game', 'Regulars played 87% of their usual minutes the match before one, against 90% otherwise: inside the noise (618 matches). This season regulars started 84% of league matches within four days after a European tie against 81% with no tie (681 player-matches).'],
  ["Re-splitting a team's goals over who plays", "Rescaling every player's share so the expected eleven exactly accounts for the team's chances made the forecast worse in three seasons (1,500 team-matches), at full strength and when only the extreme totals were corrected."],
  ['Key attackers missing, team strength', "A team without regulars who had carried 20-45% of its xG still produced the xG its form predicted (3,238 team-matches, slope +0.02, 95% -0.34 to +0.38)."],
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
