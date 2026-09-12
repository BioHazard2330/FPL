from fpl_agent.models.match_intelligence import (
    FULL_TIME,
    HALFTIME,
    LIVE,
    PRE_MATCH,
    derive_status,
    parse_insights,
    parse_match,
    parse_match_events,
    parse_momentum,
    parse_player_states,
    parse_reviews,
    parse_shot_map,
    parse_team_states,
)

# Trimmed real fragments of FotMob's actual matchDetails payload shape
# (confirmed live 2026-08-21 against Arsenal v Coventry, matchId 5795363,
# pre-kickoff) - not invented field names.
_PAYLOAD = {
    "general": {
        "matchId": "5795363",
        "leagueName": "Premier League",
        "matchTimeUTCDate": "2026-08-21T19:00:00.000Z",
        "homeTeam": {"name": "Arsenal", "id": 9825},
        "awayTeam": {"name": "Coventry City", "id": 8669},
        "started": False,
        "finished": False,
    },
    "header": {
        "teams": [
            {"name": "Arsenal", "id": 9825, "score": 0},
            {"name": "Coventry City", "id": 8669, "score": 0},
        ],
        "status": {"started": False, "finished": False},
    },
    "content": {
        "lineup": {
            "homeTeam": {
                "id": 9825, "name": "Arsenal", "formation": "4-3-3",
                "starters": [
                    {"id": 562727, "name": "David Raya"},
                    {"id": 111111, "name": "Bukayo Saka"},
                ],
            },
            "awayTeam": {
                "id": 8669, "name": "Coventry City", "formation": "4-4-2",
                "starters": [{"id": 222222, "name": "Test Coventry Player"}],
            },
        },
        "stats": None,
        "shotmap": {"shots": [], "Periods": {"All": []}},
    },
}


def test_parse_match_reads_real_confirmed_fields():
    m = parse_match(_PAYLOAD)
    assert m.fotmob_match_id == "5795363"
    assert m.competition == "Premier League"
    assert m.kickoff_utc == "2026-08-21T19:00:00.000Z"
    assert m.home_team_name == "Arsenal"
    assert m.away_team_name == "Coventry City"
    assert m.status == PRE_MATCH
    assert m.home_score == 0
    assert m.away_score == 0
    # No `lineupType` in this trimmed fixture - a real honest gap, never
    # guessed as "predicted" or "standard".
    assert m.lineup_type is None


def test_parse_match_reads_real_lineup_type_predicted():
    """Confirmed live 2026-09-12 against every real GW4 PRE_MATCH fixture:
    FotMob's own `content.lineup.lineupType` is "predicted" (source
    "enetpulse", a third-party guess) hours before a real official
    teamsheet exists - this is the field `lineup_state.py` must check
    before ever reporting CONFIRMED_STARTING/CONFIRMED_BENCHED."""
    payload = {**_PAYLOAD, "content": {**_PAYLOAD["content"], "lineup": {**_PAYLOAD["content"]["lineup"], "lineupType": "predicted"}}}
    m = parse_match(payload)
    assert m.lineup_type == "predicted"


def test_parse_match_reads_real_lineup_type_standard():
    """Confirmed live 2026-09-12 against six real already-played matches:
    a match's own `lineupType` reads "standard" once the real lineup that
    was actually used is known."""
    payload = {**_PAYLOAD, "content": {**_PAYLOAD["content"], "lineup": {**_PAYLOAD["content"]["lineup"], "lineupType": "standard"}}}
    m = parse_match(payload)
    assert m.lineup_type == "standard"


def test_derive_status_pre_match_live_halftime_full_time():
    assert derive_status({"started": False, "finished": False}) == PRE_MATCH
    assert derive_status({"started": True, "finished": False}) == LIVE
    # Real field confirmed live 2026-08-21 against the actual Arsenal v
    # Coventry match at real halftime - the original guess (`reason.short`)
    # doesn't exist in the real payload at all; `liveTime.short` does.
    assert derive_status({"started": True, "finished": False}, {"liveTime": {"short": "HT"}}) == HALFTIME
    assert derive_status({"started": True, "finished": True}) == FULL_TIME


def test_parse_player_states_extracts_starters_from_both_sides_no_fabricated_stats():
    states = parse_player_states(_PAYLOAD)
    assert len(states) == 3
    saka = next(s for s in states if s.name_raw == "Bukayo Saka")
    assert saka.started is True
    assert saka.team_name == "Arsenal"
    # No shots yet (empty shotmap) - real zero, not fabricated, and unrelated
    # fields genuinely unavailable pre-kickoff must stay null, not defaulted.
    assert saka.shots == 0
    assert saka.goals == 0
    assert saka.rating is None
    assert saka.position is None
    assert saka.minutes is None


def test_parse_player_states_sums_real_shot_events_per_player():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["shotmap"] = {
        "shots": [
            {"playerId": 111111, "eventType": "Goal", "expectedGoals": 0.42},
            {"playerId": 111111, "eventType": "AttemptSaved", "expectedGoals": 0.08},
        ],
        "Periods": {"All": []},
    }
    states = parse_player_states(payload)
    saka = next(s for s in states if s.fotmob_player_id == "111111")
    assert saka.shots == 2
    assert saka.goals == 1
    assert abs(saka.xg - 0.5) < 1e-9


def test_parse_player_states_extracts_real_penalty_shots():
    """Real gap found 2026-08-26 (GW1-postmortem audit P1) - FotMob's real
    shotmap carries a genuine `situation` field, verified live before this
    was built (2 real GW1 penalty shots found). A non-penalty goal must not
    be counted, and a missed penalty must count as a penalty shot without a
    penalty goal - both real, distinct cases."""
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["shotmap"] = {
        "shots": [
            {"playerId": 111111, "eventType": "Goal", "expectedGoals": 0.79, "situation": "Penalty"},
            {"playerId": 111111, "eventType": "Miss", "expectedGoals": 0.3, "situation": "RegularPlay"},
            {"playerId": 222222, "eventType": "Miss", "expectedGoals": 0.76, "situation": "Penalty"},
        ],
        "Periods": {"All": []},
    }
    states = parse_player_states(payload)

    saka = next(s for s in states if s.fotmob_player_id == "111111")
    assert saka.penalty_shots == 1
    assert saka.penalty_goals == 1
    assert saka.shots == 2  # the real regular-play shot still counts toward the total

    coventry_player = next(s for s in states if s.fotmob_player_id == "222222")
    assert coventry_player.penalty_shots == 1
    assert coventry_player.penalty_goals == 0  # a real missed penalty - a shot, not a goal


def test_parse_player_states_defaults_penalty_fields_to_zero_pre_kickoff():
    states = parse_player_states(_PAYLOAD)
    saka = next(s for s in states if s.name_raw == "Bukayo Saka")
    assert saka.penalty_shots == 0
    assert saka.penalty_goals == 0


def test_parse_player_states_handles_missing_lineup_entirely():
    payload = {"content": {}}
    assert parse_player_states(payload) == []


def test_parse_team_states_reads_formation_and_degrades_gracefully_on_null_stats():
    states = parse_team_states(_PAYLOAD)
    assert len(states) == 2
    home = next(s for s in states if s.team_name == "Arsenal")
    assert home.formation == "4-3-3"
    # content.stats was null (real, pre-kickoff) - every numeric stat field
    # must be None, never a fabricated 0.
    assert home.possession_pct is None
    assert home.shots is None
    assert home.xg is None


def test_parse_team_states_never_crashes_on_malformed_stats_shape():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["stats"] = {"totally": "unexpected shape"}
    states = parse_team_states(payload)
    assert len(states) == 2
    assert all(s.possession_pct is None for s in states)


# Real fragments confirmed live 2026-08-29 ("live command centre" pass)
# against a real finished GW2 match (Crystal Palace 1-4 Man City, fotmob
# matchId 5795429) - trimmed shapes, not invented field names.
_REAL_STATS_WITH_BIG_CHANCES = {
    "Periods": {"All": {"stats": [
        {"title": "Top stats", "stats": [
            {"title": "Ball possession", "stats": [28, 72]},
            {"title": "Big chances", "stats": [3, 5]},
            {"title": "Big chances missed", "stats": [3, 2]},
            {"title": "Corners", "stats": [2, 6]},
        ]},
    ]}},
}


def test_parse_team_states_extracts_real_big_chances():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["stats"] = _REAL_STATS_WITH_BIG_CHANCES
    states = parse_team_states(payload)
    home, away = states[0], states[1]
    assert home.big_chances == 3
    assert home.big_chances_missed == 3
    assert away.big_chances == 5
    assert away.big_chances_missed == 2


def test_parse_momentum_returns_empty_list_pre_match_when_false():
    # Real confirmed shape - `content.momentum` is the literal bool `False`
    # before kickoff, never a dict with empty data.
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["momentum"] = False
    assert parse_momentum(payload) == []


def test_parse_momentum_reads_real_per_minute_series():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["momentum"] = {
        "main": {"data": [{"minute": 0, "value": 0}, {"minute": 2, "value": 27}, {"minute": 8, "value": -100}]},
    }
    points = parse_momentum(payload)
    assert [(p.minute, p.value) for p in points] == [(0, 0), (2, 27), (8, -100)]


def test_parse_shot_map_reads_real_coordinates_and_outcome():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["shotmap"] = {"shots": [{
        "id": 2960614345, "eventType": "Miss", "teamId": 9826, "playerId": 860920,
        "fullName": "Edward Nketiah", "x": 99.78, "y": 45.89, "min": 2, "isOnTarget": False,
        "expectedGoals": 0.048, "shotType": "LeftFoot", "situation": "RegularPlay", "period": "FirstHalf",
    }]}
    shots = parse_shot_map(payload)
    assert len(shots) == 1
    s = shots[0]
    assert s.fotmob_shot_id == "2960614345"
    assert s.player_name == "Edward Nketiah"
    assert s.minute == 2
    assert abs(s.x - 99.78) < 1e-9
    assert s.outcome == "Miss"
    assert s.is_on_target is False


# Real values confirmed live 2026-09-10 against a real finished match
# (Everton 2-2 Man Utd, fotmob matchId 5795438) - a real on-target goal by
# Bryan Mbeumo, not invented.
def test_parse_shot_map_reads_real_xgot_and_goal_crossed_coordinates():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["shotmap"] = {"shots": [{
        "id": 4123456789, "eventType": "Goal", "teamId": 8586, "playerId": 1123877,
        "fullName": "Bryan Mbeumo", "x": 87.21, "y": 22.25, "min": 46, "isOnTarget": True,
        "expectedGoals": 0.31, "expectedGoalsOnTarget": 0.612, "goalCrossedY": 36.97, "goalCrossedZ": 0.77,
        "shotType": "RightFoot", "situation": "RegularPlay", "period": "SecondHalf",
    }]}
    shots = parse_shot_map(payload)
    assert len(shots) == 1
    s = shots[0]
    assert abs(s.xgot - 0.612) < 1e-9
    assert abs(s.goal_crossed_y - 36.97) < 1e-9
    assert abs(s.goal_crossed_z - 0.77) < 1e-9


def test_parse_shot_map_goal_crossed_none_for_a_shot_that_never_reached_goal():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["shotmap"] = {"shots": [{
        "id": 999, "eventType": "BlockedShot", "teamId": 1, "playerId": 2, "fullName": "Test Player",
        "x": 80.0, "y": 40.0, "min": 10, "isOnTarget": False, "expectedGoals": 0.05,
    }]}
    s = parse_shot_map(payload)[0]
    assert s.xgot is None
    assert s.goal_crossed_y is None
    assert s.goal_crossed_z is None


# Real raw stat values confirmed live 2026-09-10 against the same Everton
# 2-2 Man Utd match - the "Accurate passes" compound string was confirmed
# character-for-character, along with the "Distance covered" real metres
# figure (not km).
_REAL_RICHER_STATS = {
    "Periods": {"All": {"stats": [
        {"title": "Top stats", "stats": [
            {"title": "Ball possession", "stats": ["45%", "55%"]},
            {"title": "Touches in opposition box", "stats": [32, 26]},
            {"title": "Accurate passes", "stats": ["361 (86%)", "458 (87%)"]},
            {"title": "Tackles", "stats": [16, 11]},
            {"title": "Interceptions", "stats": [12, 9]},
            {"title": "Blocks", "stats": [5, 7]},
            {"title": "Clearances", "stats": [18, 31]},
            {"title": "Duels won", "stats": [51, 40]},
            {"title": "Yellow cards", "stats": [3, 3]},
            {"title": "Red cards", "stats": [0, 0]},
            {"title": "Distance covered", "stats": [112473, 110010]},
            {"title": "Number of sprints", "stats": [97, 87]},
        ]},
    ]}},
}


def test_parse_team_states_extracts_richer_stats_including_compound_accurate_passes():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["stats"] = _REAL_RICHER_STATS
    home, away = parse_team_states(payload)
    # "361 (86%)" must split into a real count and a real percentage - never
    # concatenated into one wrong number (the real bug this test guards).
    assert home.accurate_passes == 361
    assert abs(home.pass_accuracy_pct - 86.0) < 1e-9
    assert away.accurate_passes == 458
    assert abs(away.pass_accuracy_pct - 87.0) < 1e-9
    assert home.touches_opp_box == 32
    assert home.tackles == 16
    assert home.interceptions == 12
    assert home.blocks == 5
    assert home.clearances == 18
    assert home.duels_won == 51
    assert home.yellow_cards == 3
    assert home.red_cards == 0
    # Real raw metres, not a fabricated km conversion.
    assert home.distance_covered_m == 112473
    assert home.sprints == 97


def test_parse_team_states_richer_stats_none_on_malformed_shape():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["stats"] = {"totally": "unexpected shape"}
    home, away = parse_team_states(payload)
    assert home.accurate_passes is None
    assert home.pass_accuracy_pct is None
    assert home.distance_covered_m is None


# Real example confirmed live 2026-09-10 against the same Everton v Man Utd
# match's real content.insights[0].
_REAL_INSIGHT = {
    "type": "team", "playerId": None, "teamId": 8668, "priority": 1338,
    "defaultText": "Have scored {0} goals in their last {1} matches",
    "localizedTextId": "insights_goals_team",
    "statValues": [{"value": 11, "name": None, "type": "integer"}, {"value": 5, "name": None, "type": "integer"}],
    "text": "Have scored 11 goals in their last 5 matches", "color": "#00359C",
}


def test_parse_insights_reads_real_storyline():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["insights"] = [_REAL_INSIGHT]
    insights = parse_insights(payload)
    assert len(insights) == 1
    i = insights[0]
    assert i.text == "Have scored 11 goals in their last 5 matches"
    assert i.team_fotmob_id == 8668
    assert i.player_fotmob_id is None
    assert i.priority == 1338
    assert i.color == "#00359C"
    assert i.fotmob_insight_key == "insights_goals_team|team8668"


def test_parse_insights_composes_distinct_keys_for_duplicate_localized_id_across_teams():
    # The same real localizedTextId can legitimately fire for both sides -
    # the dedup key must not collapse them into one row.
    home_insight = dict(_REAL_INSIGHT)
    away_insight = dict(_REAL_INSIGHT, teamId=9825, text="Have scored 4 goals in their last 5 matches")
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["insights"] = [home_insight, away_insight]
    insights = parse_insights(payload)
    keys = {i.fotmob_insight_key for i in insights}
    assert len(keys) == 2


def test_parse_insights_empty_when_absent():
    assert parse_insights(_PAYLOAD) == []


def test_parse_insights_skips_entries_missing_text_or_id():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["insights"] = [{"teamId": 1, "text": None, "localizedTextId": "x"}, {"teamId": 1, "text": "ok", "localizedTextId": None}]
    assert parse_insights(payload) == []


# Real example confirmed live 2026-09-10 against the same match's real
# content.postReview (trimmed to the fields this project reads).
_REAL_REVIEW_ENTRY = {
    "id": "46ycqbva0iu415b0ra60g02of", "lang": "en",
    "title": "Everton 2-2 Manchester United: Debutant Maitland-Niles salvages last-gasp draw",
    "image": "https://images.fotmob.com/image_resources/review/example.jpg",
    "description": "A late equaliser rescued a point for Everton.",
    "contentUrl": "https://www.fotmob.com/match-review/example",
    "dateUpdated": "2026-09-06T17:30:00Z",
}


def test_parse_reviews_reads_real_en_entry_and_filters_other_languages():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["postReview"] = [
        dict(_REAL_REVIEW_ENTRY, lang="de", title="German title, must be skipped"),
        _REAL_REVIEW_ENTRY,
    ]
    reviews = parse_reviews(payload)
    assert len(reviews) == 1
    r = reviews[0]
    assert r.kind == "post"
    assert r.title == _REAL_REVIEW_ENTRY["title"]
    assert r.image_url == _REAL_REVIEW_ENTRY["image"]
    assert r.content_url == _REAL_REVIEW_ENTRY["contentUrl"]
    assert r.published_at == _REAL_REVIEW_ENTRY["dateUpdated"]


def test_parse_reviews_prefers_post_and_pre_independently():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["preReview"] = [dict(_REAL_REVIEW_ENTRY, title="Preview headline")]
    reviews = parse_reviews(payload)
    assert len(reviews) == 1
    assert reviews[0].kind == "pre"
    assert reviews[0].title == "Preview headline"


def test_parse_reviews_empty_when_not_a_list():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["postReview"] = None
    assert parse_reviews(payload) == []


def test_parse_shot_map_empty_pre_match():
    assert parse_shot_map(_PAYLOAD) == []


# Real fragment confirmed live 2026-08-29 - `content.playerStats` (keyed by
# FotMob player id) carries real rating/minutes/assists/xA/chances-created
# once a match has started; previously never extracted (hardcoded to None).
_PAYLOAD_WITH_PLAYER_STATS = {
    "content": {
        "lineup": {
            "homeTeam": {
                "name": "Arsenal", "formation": "4-3-3",
                "starters": [{"id": 111111, "name": "Bukayo Saka", "performance": {"rating": 7.8}}],
                "subs": [{"id": 333333, "name": "Test Sub", "performance": {
                    "rating": 6.5, "substitutionEvents": [{"time": 70, "type": "subIn"}],
                }}],
            },
            "awayTeam": {"name": "Coventry City", "formation": "4-4-2", "starters": []},
        },
        "shotmap": {"shots": [], "Periods": {"All": []}},
        "playerStats": {
            "111111": {"stats": [{"key": "top_stats", "stats": {
                "FotMob rating": {"stat": {"value": 7.8}},
                "Minutes played": {"stat": {"value": 90}},
                "Assists": {"stat": {"value": 1}},
                "Expected assists (xA)": {"stat": {"value": 0.31}},
                "Chances created": {"stat": {"value": 2}},
            }}]},
        },
    },
}


# Real fragments confirmed live 2026-08-29 against the actual finished GW2
# match (id 5795429) - `general.homeTeam.id` matches `isHome` semantics.
_PAYLOAD_WITH_EVENTS = {
    "general": {"homeTeam": {"id": 9825}, "awayTeam": {"id": 8456}},
    "content": {
        "matchFacts": {"events": {"events": [
            {
                "reactKey": "goal1", "eventId": 111, "type": "Goal", "time": 17, "isHome": False,
                "player": {"id": 737066, "name": "Erling Haaland"}, "assistStr": "Phil Foden",
            },
            {
                # Real confirmed shape - a Substitution event's own top-level
                # `player` is always empty; the real names live in `swap`
                # (swap[0]=ON, swap[1]=OFF, confirmed against FotMob's own
                # real commentary text for this exact match).
                "reactKey": "sub1", "type": "Substitution", "time": 89, "isHome": False,
                "player": {"id": None}, "swap": [
                    {"name": "Vitor Reis", "id": "1580952"}, {"name": "Abdukodir Khusanov", "id": "1362998"},
                ],
            },
        ]}},
        "shotmap": {"shots": [], "Periods": {"All": []}},
    },
}


def test_parse_match_events_reads_real_goal_with_assist():
    events = parse_match_events(_PAYLOAD_WITH_EVENTS)
    goal = next(e for e in events if e.event_type == "Goal")
    assert goal.player_name == "Erling Haaland"
    assert goal.minute == 17
    assert "Haaland" in goal.description
    assert "Phil Foden" in goal.description


def test_parse_match_events_real_bug_fix_substitution_shows_real_player_names():
    """Real bug found + fixed 2026-08-29 (direct user report): a
    Substitution event's own top-level `player` field is always empty
    (`{"id": null}`) - the real names live in `swap` instead. Before this
    fix, `description` fell through to the bare, nameless event-type
    string ("Substitution"), matching the exact reported symptom
    ("SUBSTITUTION Substitution" with no player)."""
    events = parse_match_events(_PAYLOAD_WITH_EVENTS)
    sub = next(e for e in events if e.event_type == "Substitution")
    assert sub.description == "Vitor Reis on for Abdukodir Khusanov"
    assert sub.player_name == "Vitor Reis"  # the player coming ON
    assert sub.fotmob_player_id == "1580952"
    assert sub.minute == 89


def test_parse_player_states_reads_real_playerstats_fields():
    states = parse_player_states(_PAYLOAD_WITH_PLAYER_STATS)
    saka = next(s for s in states if s.fotmob_player_id == "111111")
    assert saka.minutes == 90
    assert saka.rating == 7.8
    assert saka.assists == 1
    assert abs(saka.xa - 0.31) < 1e-9
    assert saka.key_passes == 2


def test_parse_player_states_includes_bench_with_substitution_timing():
    states = parse_player_states(_PAYLOAD_WITH_PLAYER_STATS)
    sub = next(s for s in states if s.fotmob_player_id == "333333")
    assert sub.started is False
    assert sub.substituted_on_minute == 70
    assert sub.rating == 6.5  # falls back to performance.rating - not in playerStats this fixture
