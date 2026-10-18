// Real TypeScript types mirroring `monitoring/api/*.py`'s own JSON payload
// shapes (2026-09-08, Phase 8.2 Stage 2). Hand-kept in sync with the Python
// side for now - see docs/history/49-frontend-migration-plan.md's "nice to have" note
// on generating these from the Python dataclasses once the shapes settle.

export interface PlayerBrief {
  player_id: number
  photo_code?: number | null
  name: string
  median: number
  floor: number | null
  ceiling: number | null
  team_code: number | null
  position: string | null
}

export interface CaptainBlock {
  verdict: 'KEEP' | 'CHANGE' | 'REVIEW'
  verdict_name: string
  robustness: string | null
  best: PlayerBrief
  second: PlayerBrief | null
  edge: number | null
  edge_driver: { label: string; value: number } | null
  /** Why the armband is not simply on the top projection, when it is not. */
  note?: string | null
}

export interface ContributionRow {
  label: string
  value: number
  unit: string
}

export interface CheckpointBlock {
  horizons: number[]
  chosen: { name: string; totals: number[] }
  alt: { name: string; totals: number[] }
  edge: number[]
  /** Measured materiality bar at the final horizon. An edge inside it is
   *  not distinguishable from zero. Null when it could not be measured. */
  noise_bar?: number | null
}

export interface EdgeBlock {
  value: number
  alt_label: string
  horizon: string
  chosen_total: number
  alt_total: number
}

export interface WhyLine {
  tag: string | null
  text: string
}

export interface AlternativeBlock {
  label: string
  action: string
  is_chip: boolean
  reasons: string[]
  stats: Record<string, string>
}

export interface MonitorRow {
  current: string
  trigger: string
  consequence: string
}

export interface TrajectoryLeg {
  gw: number | null
  action: string
  fragile_dependency: boolean
}

export interface TrajectoryBlock {
  current_squad: { player_id: number; name: string }[]
  now: { gw: number | null; action: string }
  future_legs: TrajectoryLeg[]
}

export interface FreshnessBlock {
  computed_at: string | null
  decision_id: number | null
  model_version: string | null
  age_relative: string | null
  is_stale: boolean
  stale_reason: string | null
}

export interface LineupInfo {
  state: string
  label: string
  detail: string | null
}

export interface SquadPlayer {
  player_id: number
  photo_code?: number | null
  name: string
  position: string
  team_short: string
  team_code: number | null
  price_m: number
  median: number
  floor: number
  ceiling: number
  expected_minutes: number | null
  confidence: string
  is_captain: boolean
  is_vice: boolean
  tier: 'CORE' | 'WEAK_LINK' | 'MINUTES_RISK' | null
  lineup: LineupInfo | null
}

export interface MyTeamPayload {
  has_squad: boolean
  error?: string
  bar: {
    squad_value_m: number
    bank_m: number
    formation?: string
    captain_name?: string
    vice_name?: string
    headline_xp?: number
    xp_summary_label?: string
    actual_points_label?: string
    pitch_heading?: string
  }
  risks?: string[]
  positions?: { position: string; label: string; players: SquadPlayer[] }[]
  bench?: SquadPlayer[]
  fixtures?: FixtureContext
  weak_links?: { name: string; team_short: string; median: number; expected_minutes: number | null }[]
  strong_link?: { name: string; team_short: string; median: number; expected_minutes: number | null } | null
}

export interface TrajectorySeries {
  name: string
  path_idx: number
  role: 'leading' | 'alt'
  points: { x: number; y: number }[]
  events: { x: number; label: string }[]
}

export interface PlanTransferPlayer {
  player_id: number
  name: string
  team_code: number | null
  position: string | null
}

export interface PlanStep {
  event: number
  action: string
  chip_played: string | null
  uses_hit: boolean
  gw_ev: number | null
  player_out_id: number | null
  player_in_id: number | null
  player_out: PlanTransferPlayer | null
  player_in: PlanTransferPlayer | null
  /** Real squad diff for a chip step (wildcard's full rebuild, mainly) -
   * this step's real resulting squad vs the squad going into it. Empty for
   * a step that doesn't change the squad (bench boost/triple captain) or
   * a plain single transfer (already shown via player_out/player_in). */
  players_in: PlanTransferPlayer[]
  players_out: PlanTransferPlayer[]
  is_locked: boolean
}

export interface PlanPath {
  idx: number
  descriptor: string
  score: number | null
  confidence: string
  is_leading: boolean
  sibling_count: number
  sibling_scores: (number | null)[]
  steps: PlanStep[]
  final_free_transfers: number | null
  final_bank_m: number
  horizon_breakdown: Record<string, { path_total: number; delta_vs_roll: number | null; delta_vs_next_best: number | null }> | null
  chip_steps: { event: number; chip: string }[]
}

export interface PlanPayload {
  has_plan: boolean
  reason?: string
  horizon_gw?: number
  leader?: {
    descriptor: string
    already_played_chip: boolean
    tie: string | null
    confidence: string
    score: number | null
    delta_vs_roll: number | null
    roll_total: number | null
  }
  trajectory_series?: TrajectorySeries[]
  paths?: PlanPath[]
  sensitivity?: { label: string; pct: number }[]
  planner_cross_check?: PlannerCrossCheck | null
}

/** Beam search (what PLAN shows) vs the exact MILP optimum over the same
 *  horizon, chips excluded from both. `gap` is how many points the
 *  heuristic left on the table. Absent on plans computed before this
 *  existed, so every consumer must treat it as optional rather than
 *  rendering a zero gap. */
export interface PlannerCrossCheck {
  horizon_gw: number
  start_event: number
  chips_excluded: boolean
  milp_total: number
  milp_proven_optimal: boolean
  milp_status: string
  milp_solve_seconds: number
  milp_pool_size: number
  beam_total: number
  beam_width: number
  gap: number
}

export interface FootballSignal {
  category: string
  entity_id: number
  entity_name: string | null
  team_code: number | null
  evidence: string | null
  interpretation: string | null
  fpl_effect: string | null
  confidence: string
  direction: string
  decision_effect: string
  is_mine: boolean
  expires_at: string | null
}

export interface FootballCategory {
  category: string
  label: string
  count: number
  signals: FootballSignal[]
}

export interface TeamStateRow {
  team_id: number
  team_code: number
  team_name: string
  in_squad: boolean
  attack: { xg: number | null; shots: number | null } | null
  defence: { xga: number | null; conceded: number | null } | null
  formation: string | null
  tactical: string | null
  fpl_implication: string | null
  matches_analyzed: number
}

export interface TeamOddsRow {
  team_id: number
  team_code: number
  team_short: string
  opponent_short: string
  is_home: boolean
  clean_sheet_pct: number
  projected_goals: number
}

export interface ChangeFeedRow {
  category: 'MANAGER' | 'XI' | 'AVAILABILITY'
  event_type: string
  entity_name: string
  team_code: number | null
  old_label: string | null
  new_label: string | null
  dot: 'good' | 'bad' | 'neutral'
  is_mine: boolean
  detected_at: string
}

export interface FixtureTickerEntry {
  event: number
  opponent_short: string
  opponent_code: number | null
  is_home: boolean
  difficulty: number
}

/** One real upcoming fixture for a club, on FPL's own 1-5 FDR scale
 * (`models/fixtures.py::team_fixture_ticker`). A blank gameweek produces no
 * entry rather than a placeholder, so a short run is honest, not an error. */
export interface FixtureEntry {
  event: number
  opponent_short: string
  opponent_code: number | null
  is_home: boolean
  difficulty: number
}

/** Upcoming fixtures keyed by `teams.code` - the identifier every player row
 * in these payloads already carries. Absent for a club with no fixture in
 * the window. */
export type FixtureContext = Record<string, FixtureEntry[]>

export interface FixtureTickerRow {
  team_id: number
  team_code: number | null
  team_short: string
  fixtures: FixtureTickerEntry[]
}

export interface FootballPayload {
  signal_count: number
  squad_signal_count: number
  squad_changes: FootballSignal[]
  change_feed: ChangeFeedRow[]
  fixture_ticker: FixtureTickerRow[]
  categories: FootballCategory[]
  team_state: TeamStateRow[]
  team_odds: TeamOddsRow[]
  fixtures?: FixtureContext
}

export interface ScoutPlayerRow {
  player_id: number
  name: string
  team_short: string
  team_code: number | null
  position: string
  price_m: number | null
  owned_pct: number | null
  total_points: number | null
  form: number | null
  xgi: number | null
  is_mine: boolean
  goals: number | null
  assists: number | null
  minutes: number | null
  bonus: number | null
}

export interface OpportunityRow {
  kind: string
  name: string
  position: string
  price_m: number | null
  ownership_pct: number | null
  key_metric: string
  why_now: string
  confidence: string
  team_code: number | null
  xp: number | null
  expected_minutes: number | null
  risk: string | null
  considered_by_optimizer: boolean | null
  squad_impact: string | null
  what_would_change: string | null
}

export interface FixtureSwingRow {
  team_short: string
  team_code: number
  avg_difficulty: number
  label: string
}

export interface TransferMomentumRow {
  name: string
  team_short: string
  team_code: number
  count: number
}

export interface ScoutOpportunities {
  breakout: OpportunityRow[]
  fixture_swing: FixtureSwingRow[]
  role_change: OpportunityRow[]
  value: OpportunityRow[]
  trap: OpportunityRow[]
  transfers_in: TransferMomentumRow[]
  transfers_out: TransferMomentumRow[]
}

export interface PriceForecastRow {
  player_id: number
  name: string
  team_short: string
  team_code: number | null
  position: string
  price_m: number | null
  net_transfers: number
  direction: 'RISE_LIKELY' | 'FALL_LIKELY' | 'STABLE'
  progress_pct: number
  is_mine: boolean
}

export interface PriceLedgerRow {
  player_id: number
  name: string
  team_short: string
  team_code: number | null
  old_price_m: number
  new_price_m: number
  valid_from: string
}

export interface PriceMovesBlock {
  forecast: PriceForecastRow[]
  ledger: PriceLedgerRow[]
}

export interface TemplateTeamPlayer {
  player_id: number
  name: string
  team_code: number | null
  ownership_pct: number
  eo_percent: number | null
  eo_source: 'sampled' | 'raw'
  margin_of_error_pp: number | null
  is_mine: boolean
}

export interface TemplateTeamPosition {
  position: string
  players: TemplateTeamPlayer[]
}

export interface TemplateTeamOverlap {
  overlap_count: number
  squad_size: number
  differential_name: string | null
  differential_pct: number | null
  missing_top3: { player_id: number; name: string }[]
}

export interface TemplateTeamBlock {
  positions: TemplateTeamPosition[]
  overlap: TemplateTeamOverlap | null
}

export interface ExpectedDataRow {
  player_id: number
  name: string
  team_short: string
  team_code: number | null
  xg: number
  xa: number
  xgi: number
  xg_per90: number
  xa_per90: number
  xgi_per90: number
  minutes: number
  is_mine: boolean
}

export interface ScoutPayload {
  players: ScoutPlayerRow[]
  opportunities: ScoutOpportunities
  price_moves: PriceMovesBlock
  template_team: TemplateTeamBlock
  expected_data: ExpectedDataRow[]
  fixtures?: FixtureContext
}

export interface BenchmarkDivergenceRow {
  player_id: number
  web_name: string
  our_median: number
  solio_pr_points: number
  classification: string
  largest_driver: string | null
}

export interface BenchmarkBlock {
  gameweek: number
  age_hours: number
  divergences: BenchmarkDivergenceRow[]
}

export interface ChipStrategyRow {
  name: string
  start_event: number
  stop_event: number
  value: number | null
  value_as_of: string | null
  best_alternative_event: number | null
  best_alternative_value: number | null
  opportunity_cost: number | null
  confidence: string | null
  season_sim_as_of: string | null
}

/** Real anytime-goalscorer quote for one squad player. `implied_probability_raw`
 * is the bookmaker's own number with the overround NOT removed - a goalscorer
 * market can't be devigged the simple way a 2/3-outcome market can, so this
 * must always be labelled raw in the UI, never shown as a calibrated
 * probability. */
export interface PlayerOddsRow {
  player_id: number
  web_name: string | null
  team_short: string | null
  anytime_scorer_price: number
  implied_probability_raw: number
  retrieved_at: string | null
}

export interface PointsRevisionRow {
  player_id: number
  web_name: string
  team_short: string
  position: string
  category: string
  old_value: number
  new_value: number
  old_points: number
  new_points: number
  detected_gap_hours: number
  is_mine: boolean
}

export interface PointsRevisionsBlock {
  event: number
  locked: boolean
  total_revisions: number
  squad_revisions: number
  rows: PointsRevisionRow[]
}

/** Real adversarial decision audit, read from the cached `fpl decision-audit`
 * journal entry. Expensive and manual, so `created_at` can legitimately be
 * days older than the decision it audits - the UI must disclose that age. */
export interface DecisionAuditBlock {
  /** Set when the audit is too old to say anything about this week; only its age is shipped. */
  stale?: boolean
  age_days?: number
  created_at: string | null
  summary: string | null
  cross_check_note: string | null
  scorecard: {
    final_decision: string | null
    confidence: string | null
    decision_robustness: string | null
    data_quality: string | null
    market_evidence: string | null
    why_trust: string[]
    why_might_not_trust: string[]
  }
  falsifiers: { description: string | null; threshold_note: string | null }[]
  stress_tests: { note: string | null; decision_flips: boolean }[]
  causal_chain: { label: string | null; detail: string | null }[]
  league_wide: {
    breakout_count?: number
    differential_count?: number
    trap_count?: number
    chosen_in_is_trap?: boolean
    top_breakouts?: string[]
    top_differentials?: string[]
  } | null
}

export interface WeekPlanAuditBlock {
  decision_id: number
  computed_at: string
  event: number
  stale_reasons: string[]
  solver: { proven_optimal: boolean; horizon: number; pool_size: number; seconds: number; min_move_gain: number } | null
  moves: {
    out: string
    into: string
    into_id: number
    gain: number
    xp_out: number
    xp_in: number
    solio_in: number | null
    start_percent_out: number | null
    price_trend_in: string
    stress: { gain_with_others: number; gain_if_half: number; breakeven_drop_pct: number | null; survives_half: boolean } | null
  }[]
  min_move_gain: number
  horizon: number
  model_mae: number | null
  assumptions: string[]
}

export interface AdvancedPayload {
  readiness: { name: string; status: string; detail: string }[]
  sources: {
    source_name: string; last_success: string | null; last_failure: string | null
    last_error: string | null; latency_ms: number | null; failure_count: number; active?: boolean
  }[]
  week_plan_audit?: WeekPlanAuditBlock | null
  pipeline: { stage: string; status: string; detail: string }[]
  benchmark: BenchmarkBlock | null
  chips: ChipStrategyRow[]
  player_odds: PlayerOddsRow[]
  points_revisions: PointsRevisionsBlock | null
  decision_audit: DecisionAuditBlock | null
  freshness: { computed_at: string | null; is_stale: boolean | null; stale_reason: string | null } | null
}

export interface LiveSquadPlayer {
  player_id: number
  web_name: string
  position: string
  slot: 'starting' | 'bench'
  is_captain: boolean
  is_vice: boolean
  xp: number | null
  status: string | null
  classification: string | null
  news: string | null
  /** FPL's own real overall ownership% (all managers, not a sampled
   * top-10k subset) - `null` only if the sync genuinely hasn't run yet. */
  ownership_percent: number | null
}

export interface LiveChartSeries {
  events: number[]
  values: number[]
}

export interface IntragameSeries {
  timestamps: string[]
  points: number[]
  captain_points: number[]
  rank: (number | null)[]
}

export interface LiveCharts {
  rank: LiveChartSeries
  cumulative_points: LiveChartSeries
  captain_contribution: LiveChartSeries
  /** Real sub-gameweek points/rank samples, roughly one per real minute of
   * live play (`live_snapshot.py::_maybe_log_intragame_points_sample`) -
   * `null` before the current gameweek has any real samples yet. */
  intragame: IntragameSeries | null
}

/** Real per-team in-match state, exactly the columns `team_match_state`
 * stores (`live_snapshot.py::_active_matches_block`). Every field is
 * nullable because FotMob genuinely omits some of them early in a match -
 * a missing stat renders as an honest gap, never a zero. */
export interface LiveTeamMatchStats {
  possession_pct: number | null
  shots: number | null
  shots_on_target: number | null
  xg: number | null
  corners: number | null
  big_chances: number | null
  big_chances_missed: number | null
  chances_created: number | null
  /** Real FotMob team-level card counts (migration 0042) - not derived from
   * the timeline, an independent FotMob-reported aggregate. */
  yellow_cards: number | null
  red_cards: number | null
  /** Real current formation string ("4-3-3") when FotMob reports one for
   * this match - genuinely sparse (not every fetch carries it), never a
   * guessed default. A single current reading, not a swap-detected diff
   * against an earlier value - a real, disclosed, scoped-down version of
   * the original "formation-swap flag" idea. */
  formation: string | null
}

/** Real FotMob shot. `x`/`y` are FotMob's own 0-100 attacking-direction
 * scale (both teams attack toward x=100 in the raw feed); the away side is
 * mirrored to `100 - x` purely as a display convention so one pitch can
 * show both halves - the same convention the backend's own match-centre
 * renderer established. Values occasionally land slightly outside 0-100 in
 * the real feed and must be clamped. */
export interface LiveShot {
  minute: number | null
  x: number | null
  y: number | null
  xg: number | null
  outcome: string | null
  is_on_target: boolean | null
  team_id: number | null
  player_name: string | null
  /** Real, separate field from xg - confirmed live 2026-09-10. */
  xgot: number | null
  /** Real goal-frame placement for on-target shots specifically - horizontal
   * position and real height in metres (crossbar ~2.44m) - both null for a
   * shot that never reached the goal line. */
  goal_crossed_y: number | null
  goal_crossed_z: number | null
}

/** Real FotMob momentum sample: -100..100, positive = home pressure. */
export interface LiveMomentumPoint {
  minute: number
  value: number
}

export interface LiveMatchPlayer {
  player_id: number
  web_name: string
  started: boolean
  minutes: number | null
  rating: number | null
  goals: number | null
  assists: number | null
  shots: number | null
  xg: number | null
  xa: number | null
  key_passes: number | null
  substituted_on_minute: number | null
  substituted_off_minute: number | null
}

export interface LiveMatch {
  match_id: number
  fotmob_match_id: string | null
  status: string
  home_team_id: number
  away_team_id: number
  home_code: number | null
  away_code: number | null
  home_short: string
  away_short: string
  home_score: number | null
  away_score: number | null
  /** FotMob's own real, already-complete display string ("17'", "HT",
   * "45+2'") - stored and passed through raw (`match_intelligence.live_
   * minute` is a TEXT column), never re-parsed into a bare number that a
   * caller could mistakenly re-suffix with another apostrophe. */
  live_minute: string | null
  is_squad_match: boolean
  team_stats: { home: LiveTeamMatchStats | null; away: LiveTeamMatchStats | null }
  momentum: LiveMomentumPoint[]
  shots: LiveShot[]
  my_players: LiveMatchPlayer[]
  /** Real live win probability (`models/live_win_probability.py`) - `null`
   * when the real Dixon-Coles model can't cover both clubs yet (true for
   * most fixtures early in a season), never a guessed even split. */
  win_probability: { home_win_pct: number; draw_pct: number; away_win_pct: number; basis: string } | null
  retrieved_at: string | null
}

/** Real live bonus + defensive-contribution state for squad players, off
 * the same single `compute_live_bonus` pass the snapshot already runs.
 * `defcon_reached`/`defcon_threshold` are genuinely null for a position
 * the DefCon rule doesn't apply to - never defaulted. */
export interface BonusDefconRow {
  player_id: number
  web_name: string
  minutes: number | null
  provisional_bonus: number | null
  confirmed_bonus: number | null
  defensive_contribution: number | null
  defcon_reached: boolean | null
  defcon_threshold: number | null
}

/** Real cumulative squad match events - NOT a minute-stamped feed. The
 * backend emits `{player_id, web_name, kind, count}` per goal/assist/red;
 * there is no `minute` or `event_type` field, and pretending otherwise
 * printed a column of dashes on this screen until 2026-09-09. */
export interface LiveMatchEvent {
  player_id: number
  web_name: string | null
  kind: 'goal' | 'assist' | 'red_card'
  count: number
}

export interface LiveRecentChange {
  player_id: number | null
  web_name: string | null
  event_type: string | null
  old_value: string | null
  new_value: string | null
  severity: string | null
  detected_at: string | null
}

export interface LivePointsChanges {
  event: number
  locked: boolean
  total_revisions: number
  squad_revisions: number
}

export interface LiveRecommendationState {
  is_stale: boolean | null
  stale_reason: string | null
  stale_detected_at: string | null
  computed_at: string | null
  status: string | null
  recompute_triggered_at: string | null
  last_change: string | null
}

export interface LiveRank {
  estimated_rank: number | null
  precision: string | null
  source: string | null
  event: number | null
  is_current: boolean | null
  retrieved_at: string | null
  /** Real LiveFPL fields (source `"livefpl"` only - `null` for the
   * self-built estimator fallback, never fabricated). */
  old_rank: number | null
  rank_gain: number | null
  change_pct: number | null
  safety_score: number | null
  template_pct: number | null
  chip_played: string | null
  gw_rank: number | null
}

export interface LivePointsByPlayer {
  player_id: number
  points: number
  multiplier: number
  play_state: string
}

export interface LivePoints {
  points: number
  captain_points: number | null
  captain_name: string | null
  captain_play_state: string | null
  played: number
  live: number
  yet_to_play: number
  bench: number
  by_player: LivePointsByPlayer[]
}

export interface LiveThreat {
  player_id: number
  web_name: string
  position: string
  ownership_percent: number
  points: number
}

export interface LiveSnapshot {
  version?: number
  generated_at: string
  event: number | null
  /** The real gameweek clock. `state` is `models/gw_lifecycle.py`'s own
   * state machine; the deadline fields are FPL's own UTC strings, passed
   * through verbatim so the browser can tick them locally. All four are
   * optional because the backend omits the block entirely rather than
   * risking the live poll if the read ever fails. */
  gw: {
    event: number | null
    state: string | null
    next_deadline_event?: number | null
    next_deadline_name?: string | null
    next_deadline_time?: string | null
    last_deadline_time?: string | null
  }
  rank: LiveRank | null
  points: LivePoints | null
  /** Real top-owned players you do NOT own, ranked by their real live
   * points off the same live payload - empty before any match this event
   * has kicked off, never fabricated. */
  threats: LiveThreat[]
  squad: LiveSquadPlayer[]
  active_matches: LiveMatch[]
  bonus_defcon: BonusDefconRow[]
  match_events: LiveMatchEvent[]
  recent_changes: LiveRecentChange[]
  points_changes: LivePointsChanges | null
  recommendation: LiveRecommendationState | null
  source_freshness: SourceFreshnessRow[]
  cadence: LiveCadence
  charts: LiveCharts | null
}

export interface SourceFreshnessRow {
  source: string
  last_success: string | null
  last_failure: string | null
  failure_count: number
  degraded: boolean
}

export interface LiveCadence {
  system: { interval_minutes: number; reason: string; last_sync_at: string | null }
  rank: { last_update_at: string | null; next_due_floor_minutes: number }
}

export interface ActionSquadPlayer {
  player_id: number
  photo_code?: number | null
  name: string
  position: string
  team_code: number | null
  median: number
  /** Bought by the plan: not in the squad as it stands. */
  is_new?: boolean
}

export interface ActionSquadBlock {
  action: string | null
  starting: ActionSquadPlayer[]
  bench: ActionSquadPlayer[]
  captain_id: number | null
  vice_id: number | null
}

export interface CommandPayload {
  gw: { label: string; state: string | null }
  status: { recompute_status: string | null; degraded_sources: string[] }
  bar: {
    squad_value_m: number
    bank_m: number
    free_transfers: { value: string; title: string }
    actual_points: number | null
    chips_available: string[]
  }
  action: { word: string; class: string; is_stale: boolean }
  freshness: FreshnessBlock | null
  edge: EdgeBlock | null
  checkpoint_table: CheckpointBlock | null
  contribution: ContributionRow[]
  trajectory: TrajectoryBlock | null
  why: WhyLine[]
  captain: CaptainBlock | null
  cross_check: { status: string | null; why: string | null } | null
  alternative: AlternativeBlock | null
  monitor: MonitorRow[]
  fixtures?: FixtureContext
  football_context: {
    entity_name: string | null
    category: string
    evidence: string | null
    fpl_effect: string | null
    direction: string
    confidence: string
  }[]
  action_squad: ActionSquadBlock | null
}


/** THE FOOTBALL, not the fantasy game.
 *
 * A real league table computed from real played fixtures (three points a win,
 * ordered by points then goal difference then goals for - the real Premier
 * League tiebreak order), the real fixture calendar with real kickoff times,
 * and the real full-time detail this project already holds for every finished
 * match. `xg_for`/`xg_against` are per-match averages and are genuinely null
 * for a club whose matches were never fetched from FotMob. */
export interface LeagueTableRow {
  position: number
  team_id: number
  code: number
  name: string
  short: string
  played: number
  won: number
  drawn: number
  lost: number
  gf: number
  ga: number
  gd: number
  points: number
  /** Most recent first, at most five. A club that has played twice shows two. */
  form: string[]
  xg_for: number | null
  xg_against: number | null
  in_squad: boolean
}

export interface MatchweekSide {
  team_id: number
  code: number
  name: string
  short: string
  score: number | null
  in_squad: boolean
}

export interface MatchweekFixture {
  fixture_id: number
  /** FPL's own UTC string. Rendered in local time by the browser, which is
   * the only place the viewer's timezone is actually known. */
  kickoff_time: string | null
  finished: boolean
  started: boolean
  home: MatchweekSide
  away: MatchweekSide
  /** Present only when real match intelligence exists for this fixture. */
  match_id: number | null
  match_status: string | null
  has_squad_interest: boolean
}

export interface MatchweekBlock {
  event: number
  fixtures: MatchweekFixture[]
  complete: boolean
  is_next: boolean
}

/** A real season leader. A player with no stat snapshot is excluded from a
 * board rather than ranked as a zero - "we have no record" and "they did
 * nothing" are different statements. */
export interface LeaderRow {
  player_id: number
  name: string
  position: string
  team_short: string | null
  team_code: number | null
  team_id: number
  goals: number | null
  assists: number | null
  points: number | null
  minutes: number | null
  xg: number | null
  xa: number | null
  xgi: number | null
  is_mine: boolean
}

export interface MatchweekPayload {
  table: LeagueTableRow[]
  matchweeks: MatchweekBlock[]
  /** Finished matches in the same shape the live Match Centre renders. */
  results: LiveMatch[]
  leaders: { scorers: LeaderRow[]; assists: LeaderRow[]; underlying: LeaderRow[] }
}


/** A real per-match row from `player_match_stats_history` - 57,200 of these
 * have existed since the project began and none reached the UI until
 * 2026-09-09. Every field is nullable because a match the feed only partly
 * covered is a real state, not an error. */
export interface PlayerMatchRow {
  match_date: string | null
  minutes: number | null
  goals: number | null
  assists: number | null
  shots: number | null
  xg: number | null
  xa: number | null
  key_passes: number | null
  yellow_cards: number | null
  red_cards: number | null
  season: string | null
}

export interface PlayerProfilePayload {
  stories?: Story[]
  player: {
    player_id: number
    photo_code?: number | null
    name: string
    full_name: string
    position: string
    status: string | null
    news: string | null
    team_id: number
    team_name: string
    team_short: string
    team_code: number
    price_m: number | null
    is_mine: boolean
  }
  /** Real recorded season totals, never a projection. */
  season: {
    total_points: number | null
    minutes: number | null
    goals_scored: number | null
    assists: number | null
    clean_sheets: number | null
    bonus: number | null
    bps: number | null
    starts: number | null
    expected_goals: number | null
    expected_assists: number | null
    yellow_cards: number | null
    red_cards: number | null
    saves: number | null
  } | null
  match_log: PlayerMatchRow[]
  /** Oldest first, so a chart reads left to right in time. */
  price_history: { price_m: number; valid_from: string | null }[]
  fixtures: FixtureEntry[]
  /** Every shot FotMob recorded for him this season, Atlas frame (x toward 105). */
  shots: PlayerShot[]
  /** The whole per-match record, oldest first - the xG race is drawn from this. */
  career: CareerMatch[]
  /** Official selected_by_percent as it changed, oldest first. */
  ownership: { t: string | null; pct: number | null }[]
  /** Per-gameweek transfers in/out counters as sampled, thinned to hourly. */
  momentum: { t: string | null; in: number | null; out: number | null }[]
  deadlines: { event: number; t: string | null }[]
}

export interface PlayerShot {
  minute: number | null
  x: number
  y: number
  xg: number | null
  outcome: string
  situation: string | null
  foot: string | null
  match: string | null
  match_id: number | null
  kickoff: string | null
  is_home: boolean
  opponent_short: string | null
  score: string | null
}

export interface CareerMatch {
  season: string
  match_date: string
  minutes: number
  goals: number
  assists: number
  xg: number
  xa: number
  shots: number
}

/** One played match from a club's own point of view. `xg`/`xga` are null for
 * a fixture this project never fetched match intelligence for. */
export interface ClubResultRow {
  fixture_id: number
  event: number | null
  kickoff_time: string | null
  is_home: boolean
  opponent_short: string
  opponent_code: number | null
  gf: number
  ga: number
  result: 'W' | 'D' | 'L'
  match_id: number | null
  xg: number | null
  xga: number | null
}

export interface ClubProfilePayload {
  stories?: Story[]
  club: {
    team_id: number
    code: number
    name: string
    short: string
    strength_home: number | null
    strength_away: number | null
  }
  results: ClubResultRow[]
  fixtures: FixtureEntry[]
  squad: {
    player_id: number
    name: string
    position: string
    status: string | null
    price_m: number | null
    total_points: number | null
    minutes: number | null
    goals: number | null
    assists: number | null
    bonus: number | null
    xg: number | null
    xa: number | null
    is_mine: boolean
  }[]
  owned_count: number
  /** Every shot this club took / faced this season, Atlas frame. */
  shots_for: (AtlasShot & { match_id: number | null })[]
  shots_against: (AtlasShot & { match_id: number | null })[]
}


/** A real match-report timeline entry. Shot events are excluded upstream:
 * a timeline listing every off-target effort is a log, not a story, and the
 * shots are drawn spatially on the shot map instead. */
export interface MatchTimelineRow {
  minute: number | null
  event_type: string
  team_id: number | null
  is_home: boolean
  player_id: number | null
  player_name: string | null
  description: string | null
  is_mine: boolean
}

export interface MatchTeamStats {
  possession_pct: number | null
  shots: number | null
  shots_on_target: number | null
  xg: number | null
  corners: number | null
  big_chances: number | null
  big_chances_missed: number | null
  formation: string | null
  chances_created: number | null
  /** Real fields confirmed live 2026-09-10 - same FotMob stats block, ~11
   * more categories that were fetched every sync and previously discarded.
   * "Accurate passes" was a compound raw string ("361 (86%)") split at
   * parse time into two real fields, never one combined/guessed number. */
  touches_opp_box: number | null
  accurate_passes: number | null
  pass_accuracy_pct: number | null
  tackles: number | null
  interceptions: number | null
  blocks: number | null
  clearances: number | null
  duels_won: number | null
  yellow_cards: number | null
  red_cards: number | null
  distance_covered_m: number | null
  sprints: number | null
}

/** Real FotMob-authored storyline, e.g. "Everton have scored 11 goals in
 * their last 5 matches" - FotMob's own real, ready-to-display sentence,
 * never derived or LLM-authored by this project. */
export interface MatchInsight {
  text: string
  team_id: number | null
  player_id: number | null
  priority: number | null
  color: string | null
}

/** Real FotMob editorial article - the post-match review once a match has
 * finished, or the pre-match preview before kickoff. Real headline/summary/
 * image/publish metadata, read as-is. */
export interface MatchReview {
  kind: 'pre' | 'post'
  title: string | null
  description: string | null
  image_url: string | null
  content_url: string | null
  published_at: string | null
}

export interface MatchLineupRow {
  player_id: number | null
  name: string | null
  position: string | null
  started: boolean
  minutes: number | null
  rating: number | null
  goals: number | null
  assists: number | null
  shots: number | null
  key_passes: number | null
  xg: number | null
  xa: number | null
  substituted_on_minute: number | null
  substituted_off_minute: number | null
  is_mine: boolean
}

export interface MatchSide {
  team_id: number
  name: string
  short: string
  code: number | null
  score: number | null
}

export interface MatchReportPayload {
  match: {
    match_id: number
    status: string
    kickoff_utc: string | null
    live_minute: number | null
    fpl_fixture_id: number | null
    home: MatchSide
    away: MatchSide
    is_squad_match: boolean
  }
  timeline: MatchTimelineRow[]
  team_stats: { home: MatchTeamStats | null; away: MatchTeamStats | null }
  lineups: { home: MatchLineupRow[]; away: MatchLineupRow[] }
  momentum: LiveMomentumPoint[]
  shots: LiveShot[]
  insights: MatchInsight[]
  review: MatchReview | null
}

/** THE RECEIPTS - the optimizer measured against YOUR real decisions.
 *
 *  `optimizer_points` is null for a gameweek where no recommendation was
 *  logged, or where it proposed selling a player who was not in the squad.
 *  Null is NOT zero and must never be rendered as a score. */
export interface LedgerRow {
  event: number
  your_points: number
  your_chip: string | null
  your_chip_label: string | null
  your_transfers: number
  optimizer_points: number | null
  optimizer_action: string | null
  roll_points: number | null
  delta_vs_you: number | null
  followed: boolean | null
  note: string | null
  /** Its recommendation scored no more than doing nothing would have. */
  worthless_vs_roll: boolean
  /** The week plan's own eleven and armband, where one was on file at the deadline. */
  plan_points?: number | null
  plan_action?: string | null
  plan_followed?: boolean | null
}

/** MODEL vs REALITY - one frozen pre-deadline prediction per player per
 *  gameweek, against the points that landed. Nothing recomputed. */
export interface CalibrationPoint {
  player_id: number
  player: string
  event: number
  predicted: number
  floor: number | null
  ceiling: number | null
  confidence: string | null
  actual: number
  minutes: number | null
  inside_band: boolean
}

export interface CalibrationBlock {
  version?: string
  n: number
  mae: number
  bias: number
  error_stdev: number
  band_coverage_pct: number | null
  band_n: number
  points: CalibrationPoint[]
  note: string
}

export interface ReceiptsPayload {
  has_record: boolean
  reason?: string
  calibration?: CalibrationBlock | null
  headline?: {
    your_total: number | null
    your_total_all_events: number
    optimizer_total: number | null
    roll_total: number | null
    delta: number | null
    comparable_events: number
    events: number
    followed_count: number
    recommendations_logged: number
    plan_events?: number
    plan_total?: number | null
    plan_your_total?: number | null
    plan_roll_total?: number | null
    optimizer_ahead: boolean
  }
  ledger?: LedgerRow[]
  flags?: {
    never_recommended_roll: boolean
    missing_recommendations: number
    followed_none: boolean
  }
  internal_consistency?: { kind: string; n: number; win_rate_pct: number; mean_advantage: number | null; thin: boolean }[]
  method?: string
  correction?: string
}

/** THE ATLAS - every real shot this season. FotMob frame: `x` along the
 *  pitch length 0-105 toward the attacked goal, `y` across the width 0-68.
 *  Already attacking-toward-105 for every shot; nothing is mirrored. */
export interface AtlasShot {
  player_id: number | null
  player: string
  team_id: number | null
  team: string | null
  team_code: number | null
  minute: number | null
  x: number
  y: number
  xg: number | null
  outcome: 'Goal' | 'AttemptSaved' | 'Miss' | 'Post' | string
  situation: string | null
  foot: string | null
  match: string | null
  mine: boolean
}

export interface AtlasShooter {
  player_id: number
  player: string
  team: string | null
  team_code: number | null
  shots: number
  goals: number
  xg: number
  on_target: number
  xg_per_shot: number
  goals_minus_xg: number
  mine: boolean
}

export interface AtlasZone {
  col: number
  row: number
  x0: number
  x1: number
  y0: number
  y1: number
  n: number
  mean_xg: number | null
}

export interface AtlasPayload {
  has_shots: boolean
  pitch: { length: number; width: number; half_x: number }
  totals: {
    shots: number; goals: number; xg: number; matches: number
    mine_shots: number; mine_goals: number; mine_xg: number
  }
  situations: [string, number][]
  shots: AtlasShot[]
  players: AtlasShooter[]
  teams: { team_id: number; team: string | null; team_code: number | null; shots: number; goals: number; xg: number; goals_minus_xg: number }[]
  zones: AtlasZone[]
  method: string
}

export interface TableRow {
  position: number
  team_id: number
  code: number
  name: string
  short: string
  played: number
  won: number
  drawn: number
  lost: number
  gf: number
  ga: number
  gd: number
  points: number
  xg: number
  xga: number
  xgd: number
  xg_matches: number
  xg_per_match: number | null
  xga_per_match: number | null
  /** Goals minus xG: positive = scoring more than the chances were worth. */
  finishing: number | null
  /** xG allowed minus goals conceded: positive = conceding less than allowed. */
  keeping: number | null
  form: ('W' | 'D' | 'L')[]
  mine: boolean
}

export interface TablePayload {
  has_table: boolean
  matches: number
  matches_with_xg: number
  through_event: number | null
  rows: TableRow[]
  method: string
}


/** THE WEEK PLAN - this gameweek's transfers as a set, with each move's
 * marginal value, plus the lineup and armband. Produced by
 * `optimization/week_plan.py` and read from the decision journal. */
export interface WeekPlanPlayer {
  player_id: number
  photo_code?: number | null
  luck?: { luck: number; z: number; actual: number; deserved: number }
  name: string
  position: string
  team_short: string
  team_id: number
  team_code: number | null
  price_tenths: number
  xp_next: number
  xp_horizon: number
  start_percent: number | null
  price_trend: 'RISE_LIKELY' | 'FALL_LIKELY' | 'STABLE'
  solio_next: number | null
  /** First-choice set-piece duties: any of penalties, free kicks, corners. */
  duties?: string[]
  /** Expected points the match-analysis signal added to xp_next. Already inside it. */
  match_analysis_xp?: number
}

export interface WeekPlanMove {
  out: WeekPlanPlayer
  into: WeekPlanPlayer
  gain: number
  cost_tenths: number
  /** When to make it: a moving price says early, an open rotation call says wait for team news. */
  timing?: 'early' | 'late' | 'split' | 'any'
  timing_note?: string
  /** The best other ways to spend this transfer if the target is unavailable, each priced against the plan without him. */
  alternatives?: { out: WeekPlanPlayer; into: WeekPlanPlayer; gain: number; cost_tenths: number }[]
}

export interface WeekPlanLineupPlayer {
  player_id: number
  photo_code?: number | null
  name: string
  position: string
  team_short: string
  team_id: number
  team_code: number | null
  xp: number
  start_percent: number | null
  floor: number | null
  ceiling: number | null
}

export interface WeekPlanLineup {
  starting: WeekPlanLineupPlayer[]
  bench: WeekPlanLineupPlayer[]
  captain_id: number | null
  vice_id: number | null
  xp_total: number
  captain_note: string | null
}

export interface LineupChanges {
  bring_in: WeekPlanLineupPlayer[]
  take_out: WeekPlanLineupPlayer[]
  captain_from: WeekPlanLineupPlayer | null
  captain_to: WeekPlanLineupPlayer | null
  vice_from: WeekPlanLineupPlayer | null
  vice_to: WeekPlanLineupPlayer | null
  xp_gain: number
  worth_changing: boolean
}

export interface WeekPlanPayload {
  status: 'none' | 'current' | 'stale'
  stale_reasons?: string[]
  decision_id?: number
  computed_at?: string
  age_hours?: number
  event?: number
  horizon?: number
  free_transfers?: number
  free_transfers_known?: boolean
  bank_tenths?: number
  roll_total?: number
  plan_total?: number
  gain_vs_roll?: number
  min_move_gain?: number
  moves?: WeekPlanMove[]
  declined?: WeekPlanMove[]
  curve?: { moves: number; total: number; gain_vs_roll: number }[]
  ft_after?: number
  bank_after_tenths?: number
  affordability?: string
  team_outlook?: Record<string, {
    short: string
    attack_rank: number
    defence_rank: number
    clubs: number
    xg_for_total: number
    cs_total: number
    fixtures: number
    next: { opponent: string; home: boolean; xg_for: number; xg_against: number; cs: number; market: boolean }[]
  }>
  captain_ladder?: { event: number; picks: { player_id: number; name: string; team_id: number; xp: number }[] }[]
  road_ahead?: {
    horizon: number
    total: number
    roll_total: number
    gain_vs_roll: number
    proven: boolean
    final_free_transfers: number
    weeks: { event: number; moves: { out: string; into: string; hit: boolean }[] }[]
  } | null
  chip_outlook?: {
    available: string[]
    double_gameweeks: { event: number; teams: string[] }[]
    blank_gameweeks: { event: number; teams: string[] }[]
    bench_boost_this_week: number
    horizon: number
  } | null
  proven_optimal?: boolean
  notes?: string[]
  lineup_now?: WeekPlanLineup
  lineup_after?: WeekPlanLineup
  lineup_set_by_you?: WeekPlanLineup | null
  doctor?: LineupChanges | null
  doctor_after_moves?: LineupChanges | null
  action_squad?: ActionSquadBlock
  captain?: CaptainBlock | null
  fixtures?: FixtureContext
}

export interface DeskPlayerChip {
  player_id: number
  photo_code?: number | null
  name: string
  team_code: number | null
  mine: boolean
  target: boolean
}

export interface DeskArticle {
  id: number
  source: string
  title: string
  link: string
  summary: string | null
  image: string | null
  published_at: string | null
  players: DeskPlayerChip[]
  relevance: number
  injury: boolean
}

export interface DeskInjury {
  player_id: number
  photo_code?: number | null
  name: string
  team_code: number | null
  team_short: string
  status: string
  news: string
  added_at: string | null
  chance: number | null
  owned: number | null
  mine: boolean
  target: boolean
}

export interface DeskVideo {
  id: number
  video_id: string
  channel: string
  title: string
  link: string
  thumbnail: string | null
  published_at: string | null
  players: DeskPlayerChip[]
  relevance: number
}

export interface DeskPost {
  id: number
  title: string
  link: string
  author: string | null
  thumbnail: string | null
  published_at: string | null
  players: DeskPlayerChip[]
}

export interface DeskPriceMove {
  player_id: number
  photo_code?: number | null
  name: string
  team_code: number | null
  old: string
  new: string
  at: string
  owned: number | null
  mine: boolean
  target: boolean
}

export interface DeskPriceLean {
  player_id: number
  photo_code?: number | null
  name: string
  team_code: number | null
  direction: 'RISE_LIKELY' | 'FALL_LIKELY'
  net_ratio: number
  owned: number | null
  mine: boolean
  target: boolean
}

export interface DeskPayload {
  generated_at: string
  lead: DeskArticle | null
  wire: DeskArticle[]
  injuries: DeskInjury[]
  videos: DeskVideo[]
  posts: DeskPost[]
  price: { rises: DeskPriceMove[]; falls: DeskPriceMove[]; leaning: DeskPriceLean[] }
  counts: { articles: number; yours: number; targets: number }
}

export interface PreviewKeyPlayer {
  player_id: number
  photo_code?: number | null
  name: string
  position: string
  xp: number
  price: number | null
  mine: boolean
  doubt: number | null
  news: string | null
}

export interface PreviewSide {
  team_id: number
  code: number
  name: string
  short: string
  difficulty: number | null
  form: { fixture_id: number; result: 'W' | 'D' | 'L'; score: string; home: boolean; opponent: string }[]
  key_players: PreviewKeyPlayer[]
  absentees: { player_id: number; name: string; status: string; chance: number | null; news: string }[]
  yours: { player_id: number; name: string }[]
}

export interface PreviewFixture {
  fixture_id: number
  kickoff: string | null
  home: PreviewSide
  away: PreviewSide
  xg: { home: number; away: number }
  model: {
    home_win: number
    draw: number
    away_win: number
    home_clean_sheet: number
    away_clean_sheet: number
    over_2_5: number
    likely_score: [number, number]
    likely_score_p: number
  }
  market: { home_win: number; draw: number; away_win: number; bookmakers: number; retrieved_at: string } | null
  lens: PreviewLens
}

export interface PreviewLensRow {
  source: string
  league: number
  attack: number
  defence: number
  expected: number
  shift: number
}

export interface PreviewLens {
  home: PreviewLensRow[]
  away: PreviewLensRow[]
  matches: { home: number; away: number }
  headline: (PreviewLensRow & { side: 'home' | 'away' }) | null
  takers?: { player_id: number; name: string; xg: number; shots: number }[]
}

export interface TickerEntry {
  opponent: string
  opponent_code: number
  home: boolean
  xg_for: number
  xg_against: number
  cs: number
  market: boolean
}

export interface PreviewsPayload {
  event: number | null
  events?: number[]
  generated_at: string
  fixtures: PreviewFixture[]
  ticker?: {
    first_event: number
    events: number[]
    rows: {
      team_id: number
      code: number
      name: string
      short: string
      events: Record<string, TickerEntry[]>
      xg_for_total: number
      cs_total: number
      fixtures: number
    }[]
  }
}

export interface PlayerIndexRow {
  player_id: number
  photo_code?: number | null
  name: string
  full_name: string
  team_short: string
  team_code: number
  position: string
  price: number | null
  owned: number | null
  status: string
}

export interface ComparePlayer {
  player_id: number
  photo_code?: number | null
  name: string
  full_name: string
  team_id: number
  team_name: string
  team_short: string
  team_code: number
  position: string
  status: string
  news: string | null
  chance: number | null
  is_mine: boolean
  price: number | null
  owned: number | null
  xp_next: number
  floor: number
  ceiling: number
  xp_window: number
  fixture_count: number
  expected_minutes: number
  p_blank: number | null
  p_5plus: number | null
  components: Record<'appearance' | 'goals' | 'assists' | 'bonus' | 'clean_sheet' | 'cards' | 'conceded' | 'defcon' | 'saves', number> | null
  points_per_pound: number | null
  form: number | null
  ppg: number | null
  total_points: number | null
  minutes: number
  starts: number | null
  goals: number | null
  assists: number | null
  xg: number | null
  xa: number | null
  xg90: number | null
  xa90: number | null
  start_percent: number | null
  solio_next: number | null
  price_trend: 'RISE_LIKELY' | 'FALL_LIKELY' | 'STABLE'
  duties: string[]
  fixtures: FixtureEntry[]
}

export interface ComparePayload {
  event: number | null
  window: number
  a: ComparePlayer
  b: ComparePlayer
  rows: { label: string; key: string; a: number | null; b: number | null; winner: 'a' | 'b' | null; a_text: string | null; b_text: string | null }[]
  gap_window: number
  gap_next: number
  price_gap: number | null
  model_mae: number | null
  as_transfer?: {
    out_id: number
    in_id: number
    same_position: boolean
    club_after: number
    club_ok: boolean
    bank_after_tenths: number
    affordable: boolean
    gain_window: number
    gain_next: number
    free_transfers: number
  } | null
}

export interface Story {
  kind: 'article' | 'video' | 'post'
  id: string
  source: string
  title: string
  link: string
  summary: string | null
  image: string | null
  published_at: string | null
  video_id?: string | null
  author?: string | null
}

export interface ProjectionPayload {
  event: number | null
  window: number
  player: ComparePlayer
}

export interface LuckRow {
  player_id: number
  photo_code?: number | null
  name: string
  team_id: number
  team_short: string
  team_code: number
  position: string
  minutes: number
  gws: number
  actual: number
  deserved: number
  luck: number
  goals_luck: number
  assists_luck: number
  cs_luck: number
  conceded_luck: number
  goals: number
  xg: number
  assists: number
  xa: number
  z: number
  luck_per_gw: number
  mine: boolean
  price: number | null
  owned: number | null
}

export interface MatchRebuild {
  match_id: number
  event: number | null
  kickoff: string
  home: { team_id: number; name: string; short: string; code: number; score: number; xg: number; shots: number }
  away: { team_id: number; name: string; short: string; code: number; score: number; xg: number; shots: number }
  shots: { minute: number; side: 'home' | 'away'; xg: number; goal: boolean; player: string; situation: string | null }[]
  deserved: { home_win: number; draw: number; away_win: number; home_points: number; away_points: number; likely_score: [number, number] }
  own_goals_or_unshot: { home: number; away: number }
}

export interface ArmbandRow {
  event: number
  multiplier: number
  chip: string | null
  captain: { player_id: number; name: string; actual: number; deserved: number }
  best_actual: { player_id: number; name: string; actual: number }
  best_deserved: { player_id: number; name: string; deserved: number }
  cost: number
  owed: number
}

export interface AuditPayload {
  armband: ArmbandRow[]
  event: number | null
  events: number[]
  radar_season: { hot: LuckRow[]; cold: LuckRow[] }
  radar_recent: { hot: LuckRow[]; cold: LuckRow[] }
  squad: LuckRow[]
  matches: MatchRebuild[]
  thresholds: { min_minutes: number; recent_gameweeks: number }
}

export interface EdgeStats {
  mean: number
  sd: number
  p_beat: number
  p10: number
  p90: number
  big_win: number
  big_loss: number
  percentile: number
  hist: number[]
}

export interface FieldOption {
  key: string
  label: string
  moves: { out: string; into: string }[]
  captain: { player_id: number; name?: string; team_short?: string } | null
  xi: { player_id: number; name?: string }[]
  edge: EdgeStats
  mean_points: number
}

export interface FieldPayload {
  status: 'ok' | 'no_plan' | 'no_sample'
  detail?: string
  event?: number
  n_trials?: number
  decision_id?: number
  field?: { kind: 'top10k' | 'population'; label: string; sample_event: number; sample_size: number; coverage: number; spread: number }
  posture?: { overall_rank: number; total_players: number; percentile: number; after_event: number } | null
  model_bias?: { n: number; bias_per_player: number; standard_error: number } | null
  options?: FieldOption[]
  plan_option?: FieldOption
  captains?: {
    player_id: number
    photo_code?: number | null
    name: string
    team_short: string
    team_code: number
    position: string
    mean_points: number | null
    captain_share: number
    field_eo: number
    edge: EdgeStats
    chosen: boolean
  }[]
  best_captain_id?: number
  upside_captain_id?: number
  threats?: { player_id: number; photo_code?: number | null; name: string; team_short: string; team_code: number; position: string; field_eo: number; mean_points: number; p_haul: number; cost: number }[]
  contributions?: { player_id: number; name: string; team_short: string; team_code: number; position: string; you: number; field_eo: number; mean_points: number; edge: number }[]
  axis?: { min: number; max: number; bins: number }
}

export interface LiveConePayload {
  status: 'ok' | 'not_live' | 'settled' | 'no_picks' | 'no_sample' | 'no_live_data'
  detail?: string
  event?: number
  field?: { kind: string; label: string }
  now?: number
  forecast?: { mean: number; p10: number; p50: number; p90: number }
  field_now?: number
  field_forecast?: number
  edge?: { mean: number; p_beat: number; p10: number; p90: number; percentile: number; hist: number[] }
  fixtures_left?: number
  fixtures_live?: number
  players?: {
    player_id: number
    photo_code?: number | null
    name?: string
    team_short?: string
    team_code?: number
    position?: string
    multiplier: number
    points_now: number
    remaining_mean: number
    remaining_sd: number
    p_five_more: number
    swing: number
  }[]
  axis?: { min: number; max: number; bins: number }
}

export interface WhatIfBrief {
  player_id: number
  name: string
  team_id: number
  team_short: string
  team_code: number
  position: string
  status: string
  news: string | null
  price: number | null
  photo_code?: number | null
}

export interface WhatIfPayload {
  status: 'ok' | 'no_squad'
  event?: number
  horizon?: number
  free_transfers?: number
  bank_tenths?: number
  squad?: WhatIfBrief[]
  moves?: { out: WhatIfBrief; into: WhatIfBrief }[]
  problems?: string[]
  hits?: number
  hit_cost?: number
  bank_after_tenths?: number
  per_gw?: { event: number; before: number; after: number }[]
  totals?: { before: number; after: number; gain_gross: number; gain_net: number } | null
  plan?: { gain: number | null; moves: string[] } | null
}

export interface ExplorerPlayer {
  player_id: number
  name: string
  full_name: string
  team_id: number
  team_short: string
  team_code: number
  position: string
  mine: boolean
  price: number | null
  owned: number | null
  xp_next: number
  xp_five: number
  xp_per_m: number | null
  form: number | null
  ppg: number | null
  points: number | null
  minutes: number
  minutes_share: number
  g_a_90: number | null
  xgi_90: number | null
  luck: number | null
  luck_z: number | null
  deserved_ppg: number | null
  actual_ppg: number | null
  status: string
  chance: number | null
  news: string | null
  fixtures: { opponent: string; home: boolean; difficulty: number | null }[]
  photo_code?: number | null
}

export interface ExplorerPayload {
  event: number
  generated_at: string
  window: number
  players: ExplorerPlayer[]
}
