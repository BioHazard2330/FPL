-- Real, proper per-player devig for anytime-goalscorer odds (2026-09-13,
-- "make the optimizer smarter" research pass). the-odds-api's own real
-- player_goal_scorer_anytime market payload already carries a real "No"
-- price alongside "Yes" for the same player (confirmed via this project's
-- own existing test fixture) - parse_anytime_scorer_outcomes only ever
-- kept "Yes" before this, so `implied_probability_raw` (bare 1/price) still
-- carries the real bookmaker overround baked in. anytime_no_scorer_price
-- lets a real two-outcome devig be computed per player (this player's own
-- Yes vs No is a genuine complementary pair, unlike normalizing across
-- many players' own Yes prices, which are NOT mutually exclusive events).
ALTER TABLE player_odds_live ADD COLUMN anytime_no_scorer_price REAL;
ALTER TABLE player_odds_live ADD COLUMN implied_probability_devigged REAL;
