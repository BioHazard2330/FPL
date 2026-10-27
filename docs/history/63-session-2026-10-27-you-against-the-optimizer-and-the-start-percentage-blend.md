# Session 2026-10-27 — you against the optimizer, how weak the projections still are, the start-percentage blend

User: *"check how i did vs whatever the optimizer suggested and figure out how weak it still is. Run whatever analysis etc is left as well."* Six pending match analyses (Chelsea-Spurs, Hull-Brentford, Man Utd-Bournemouth, Liverpool-Brighton, Palace-Newcastle, Sunderland-Leeds) were filed from the analyst's drafts first.

## How you did (entry 7378572, GW1-8)

526 points against 461 for the average manager (+65), rank 4.09m to 1.02m, above the average in 7 of 8 gameweeks (GW5, the wildcard week, 35 against 48, is the exception). Split by `luck_audit` (goals, assists, clean sheets and goals conceded against xG/xA/xGC, weighted by the armband multiplier): about **54 of the 65 was luck** (GW4 +30, GW6 +23, GW2 +18, GW7 +14; GW3 -16, GW5 -12), so the deserved total is about 472, +11 on the average. Groß, João Pedro, Gvardiol and Verbruggen alone are +57 over their own xG/xA/xGC. The rank climb is real and mostly not repeatable.

## You against the optimizer

- **Wildcard (GW5):** followed. The squad you built scored 86 more (best eleven and armband in hindsight, same method for both) over GW5-8 than the pre-wildcard squad would have (292 against 206); the plan had claimed +83.8 over eight gameweeks against rolling. The strongest single piece of evidence the optimizer helps.
- **Transfers GW6-8:** none made, all recommended moves ignored. Realised, in minus out: GW7 Gibbs-White -> Cherki -2, Palmer -> Saka +2 (net 0); GW8 Gibbs-White -> Rudoni 0, Gvardiol -> Gabriel +16 (Gabriel's 17-point match). Free transfers were banked at the cap of 5 and none cost a hit, so ignoring them cost little to date and nothing was lost to a wrong call; a transfer sits unused beyond five.
- **Lineup:** the plan's best eleven from your own squad realised 70 against the 59 you set in GW7 and 50 against 46 in GW8 (n 2). Same armband every week (Haaland); across eight gameweeks the best-eleven-and-armband you could have set with hindsight was 94 points better in total, 82 points sat on the bench (GW5: 22).
- **Armband:** Haaland every gameweek but GW4 (Palmer); the best hindsight armband from your own squad was another player in six of eight (Joao Pedro three times). Unforeseeable week to week, and the model also picked Haaland.

## How weak the projections still are (GW8, 474 settled predictions, model calibrated-v3)

- Overall MAE 1.50 against 2.08 for a season-average baseline; Spearman 0.62 across everyone (mostly who plays and in what position).
- Among players projected at 2+ points (n 186), the ones decisions are about: MAE 2.47 against 2.65 for the baseline (7% better), Spearman **0.175** (baseline 0.078). The model's top 20 averaged 3.35 realised points, no better than the average of those 186 (3.46); the best 20 in hindsight averaged 10.65. Position: goalkeepers and defenders were under-predicted (GKP +1.2, DEF +0.7 points), midfielders over (-0.3). Mean +0.34 a player: still running cool.
- Walk-forward 2025-26 (`fpl backtest`, 12 rounds, 6,907 predictions): MAE 1.137 against 1.213 naive (6%).
- Read together: one gameweek's player-level order is mostly noise at this ceiling of the sport, the model is a few percent better than naive, and the edge that shows up is structural (who plays, the wildcard, not holding injured players), not a ranking of stars.

## The thing found and fixed: the start-percentage rule was discount-only and wrong

`fpl start-calibration` now has 216 readings. The old pairing dropped players outside the squad (the ones the feed gets wrong) and read too kind; it now counts them as not having started. Readings are close to honest (10-30%: 9.5% started; 30-50%: 39%; 50-70%: 59%; 70-85%: 80%; 85-100%: 86%). But the **discount-only rule predicted 60+ minutes 46% of the time against 57% realised** and scored worse (Brier 0.1864) than the player's own record (0.1786). The reading as a probability 0.1791, a 50/50 blend **0.1675**, closest in every band. `apply_start_probability` is now that blend (`START_BLEND_WEIGHT` 0.5, faded by gameweek), lifting a player the record undersells (Kudus 80% on the feed, 47% in his record: GW9 xP 2.5 to 3.1; Solanke 3.0 to 3.8, closer to Solio's 5.1) and never past what his availability allows. A bench seat last match is no longer capped (the blend already predicts 30% against 32% realised); only a regular left out of the squad is (0.8x, 16 cases). Plan rebuilt: Joao Pedro -> Barry, Calafiori -> Gabriel (+4.45; Calafiori now carries a hip knock, 75%).

## Assumptions and open items

- The blend is fitted on one gameweek's readings; readings days ahead of kickoff are weaker than readings on the day, which the gameweek fade only approximates.
- Luck here is goals/assists/clean sheets/conceded against xG/xA/xGC; bonus is not split, so the deserved total is approximate.
- The wildcard comparison uses best-eleven hindsight for both squads, not the points you would actually have collected with the old squad.
- GW8 is the only gameweek with a full stored cross-section of calibrated-v3 predictions; re-run the cross-section each gameweek (`prediction_outcomes`).
