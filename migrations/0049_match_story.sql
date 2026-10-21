-- The Match Analyst's output (models/match_analyst.py): one story per finished
-- match, built from stored shots/events/states with no network and no LLM.
-- `story_json` holds the timeline, per-side metrics, game-state profile,
-- classified substitutions, player lines and ranked findings. Rebuilt whenever
-- the engine version changes or the match's shots are newer than the story.
CREATE TABLE match_story (
    match_id INTEGER PRIMARY KEY REFERENCES match_intelligence(id),
    engine_version TEXT NOT NULL,
    story_json TEXT NOT NULL,
    generated_at TEXT NOT NULL
);
