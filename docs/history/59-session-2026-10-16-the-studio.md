# Session 2026-10-16 (second part) — the studio: news desk, match previews, plan alternatives

User, verbatim: *"upgrade every single thing to the maximum ... my own insane fpl and football studio but insanely well developed, creative, impressive in accuracy and precision."*

## What was built

**The desk (`/desk`, `/api/desk`).** `ingestion/media_source.py` pulls four YouTube channels (Premier League, Sky Sports PL, FPL Harry, Let's Talk FPL) through their public Atom feeds and r/FantasyPL through its Atom feed (the JSON endpoint answers 403 to a script). Channel ids were resolved from each channel's own page and each feed fetched before it was listed - two ids written from memory belonged to other channels. News items now carry an image (`news_items.image_url`, migration 0046) and The Guardian's Premier League RSS joined the wire. `monitoring/api/desk_payload.py` reads stored rows only (about 0.1s): an item is *yours* if it names a squad player, a *plan target* if it names a player the stored week plan buys or declined, otherwise newest first; duplicate headlines across feeds are shown once. Also: official FPL injury notes, a price board (FPL's own changes plus the existing transfer-momentum lean, labelled uncalibrated), a video studio with click-to-load `youtube-nocookie` embeds (nothing loads from YouTube until clicked), community posts. COMMAND carries a small "from the desk" strip when a story touches the squad or the plan.

**Match previews (`/previews`, `/api/previews`).** Per next-gameweek fixture: the same odds-blended Dixon-Coles goals every projection uses, a Poisson score grid (0-8 goals) with the DC low-score correction at the fitted rho, win/draw/loss, clean sheets, most likely score, the de-vigged bookmaker 1X2 beside it (never blended), last five results, official FDR, the three highest-projected players per side with yours marked, flagged absentees. Built once per ten minutes in a refresh thread (one DC fit, about 160 player projections, 5-7s).

**Plan alternatives and captain ladder (`optimization/week_plan.py`).** For each recommended move the best two other ways to spend the same transfer if that player is unavailable: the planner re-solved with him removed from the pool, every other move forced, priced against the best plan that makes the other moves and never buys him (without that last clause the base plan still bought him next week and every alternative looked negative). An alternative worth nothing is not listed. The armband ladder is the top three projections per gameweek for the post-move squad. Adds about 15s to a plan build (45-50s total).

## Defects found on the way
- A first-name player matched another person's surname: "Enzo Maresca" tagged Chelsea's Enzo. `news_source._is_someone_else` now rejects a first-name or nickname web_name followed by a capitalised surname the player does not have. 83 recent articles/videos were relinked.
- The desk's price lean called `classify_price_change` for every player (1.9s); one SQL join does the same arithmetic in 0.1s.
- Vite's Tailwind scan does not see a screen file created after the dev server started: new classes silently do nothing until it is restarted.

## Assumptions and limits to keep disclosing
- Previews: probabilities assume the DC rho from the latest fit and a 0-8 goal grid; the market column is a cross-check on goals the blend already uses where odds exist, not an independent model. Key players are the top three by projection among each club's nine most regular starters.
- Alternatives are priced by the same horizon xP as the moves; their gains are small because the chosen target was the best option, which is the point.
- Ladder is ranked by projection alone; the armband rule can prefer a close second this week.
- Reddit posts carry no vote counts (feed has none), so none are shown.
- Guardian items have no pictures in the feed; they get a typographic tile.

## Later the same day: the odds fix, headshots, compare, stories, checklist

- **Market-implied goals were biased and the blend weight was wrong** (see the `CLAUDE.md` blockers entry for the numbers). Found by noticing Man City at 3.15 expected goals against a market that gave them 74%: the old split gave a heavy favourite 88% of the goals. Fixed with a joint Poisson fit, then the blend weight was measured instead of assumed. City's GW7 clean-sheet chance fell from 55% to 41%. The GW7 plan changed in one move (Gvardiol to Van Hecke instead of Guehi) and the gains of the other two fell by about a point and a quarter.
- **Headshots** (official PL CDN, keyed by player code) on transfers, the captain battle, injury notes, previews and the player file; shirts stay on the formation tiles.
- **Compare** (`/compare`), **projection band** on the player file, **stories** (articles, videos, posts) on player and club files, **deadline checklist** on COMMAND.
- Name matching: a name preceded by another player's first name ("Scott Allan") or a bare surname without the club ("Fernandez ... Rangers") no longer links to a squad player.
- **More channels**: Fantasy Football Hub, FPL Focal, FPL Raptor and FPL Mate joined the video feeds (found by resolving each channel page's canonical id and checking the feed's newest entry; Fantasy Football Scout's feed holds only 2010 uploads, FPL General's last upload was July, the official FPL channel's feed is empty, so those three were left out). The desk shelf caps each channel at five so the busiest cannot fill it, with channel tabs.
- **Run of fixtures** (on PREVIEWS): six gameweeks x twenty clubs from the team model, attack (expected goals) or defence (clean-sheet chance), coloured by rank across all cells rather than by the official difficulty number; a dot marks fixtures where stored odds fed the goals.
- **MY TEAM** uses headshots for the top-projected player and the player sheet.
- Checked and left alone: the clean-sheet probability exp(-opponent goals) is calibrated within a few points on 3,840 team-matches (0.262 predicted against 0.250 actual); it runs 9 points high above 50% (106 matches, about 2 standard errors), not enough to justify a correction yet.
