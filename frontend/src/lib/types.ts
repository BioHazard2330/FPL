// Real TypeScript types mirroring `monitoring/api/*.py`'s own JSON payload
// shapes (2026-09-08, Phase 8.2 Stage 2). Hand-kept in sync with the Python
// side for now - see docs/FRONTEND_MIGRATION_PLAN.md's "nice to have" note
// on generating these from the Python dataclasses once the shapes settle.

export interface PlayerBrief {
  player_id: number
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
    tie: string | null
    confidence: string
    score: number | null
    delta_vs_roll: number | null
    roll_total: number | null
  }
  trajectory_series?: TrajectorySeries[]
  paths?: PlanPath[]
  sensitivity?: { label: string; pct: number }[]
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

export interface AdvancedPayload {
  readiness: { name: string; status: string; detail: string }[]
  sources: {
    source_name: string; last_success: string | null; last_failure: string | null
    last_error: string | null; latency_ms: number | null; failure_count: number
  }[]
  pipeline: { stage: string; status: string; detail: string }[]
  benchmark: BenchmarkBlock | null
  chips: ChipStrategyRow[]
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
}

export interface LiveChartSeries {
  events: number[]
  values: number[]
}

export interface LiveCharts {
  rank: LiveChartSeries
  cumulative_points: LiveChartSeries
  captain_contribution: LiveChartSeries
}

export interface LiveSnapshot {
  version?: number
  generated_at: string
  event: number | null
  gw: { event: number | null; state: string | null }
  rank: Record<string, unknown> | null
  points: Record<string, unknown> | null
  squad: LiveSquadPlayer[]
  active_matches: Record<string, unknown>[]
  bonus_defcon: unknown
  match_events: Record<string, unknown>[]
  recent_changes: Record<string, unknown>[]
  points_changes: unknown
  recommendation: Record<string, unknown> | null
  source_freshness: unknown
  cadence: unknown
  charts: LiveCharts | null
}

export interface ActionSquadPlayer {
  player_id: number
  name: string
  position: string
  team_code: number | null
  median: number
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
