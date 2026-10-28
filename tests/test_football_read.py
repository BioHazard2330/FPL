from fpl_agent.models import football_read as fr


def _measure(key, label, value, pct, unit="per 90"):
    return {"key": key, "label": label, "unit": unit, "kind": "quality", "value": value, "display": f"{value}", "percentile": pct}


def _report(position="FWD", ranked=True, measures=(), finishing=None):
    return {"position": position, "ranked": ranked, "minutes": 600, "profile": [], "strengths": [], "weaknesses": [],
            "measures": list(measures), "finishing": finishing, "penalties": 0}


def test_chance_volume_leans_and_carries_and_keeps_xg_capitalised():
    lines = fr._chances(_report(measures=[_measure("npxg90", "Non-penalty xG", 0.8, 96), _measure("shots90", "Shots", 3.8, 95)]))
    assert lines[0]["weight"] == fr.CARRIES and lines[0]["lean"] == 1
    assert "non-penalty xG" in lines[0]["text"]
    low = fr._chances(_report(measures=[_measure("npxg90", "Non-penalty xG", 0.05, 10), _measure("shots90", "Shots", 0.5, 12)]))
    assert low[0]["lean"] == -1
    assert fr._chances(_report(position="GKP")) == []


def test_finishing_luck_is_shown_as_noise_and_never_leans():
    assert fr._finishing(_report(finishing={"np_goals": 2, "npxg": 1.6, "difference": 0.4})) == []
    over = fr._finishing(_report(finishing={"np_goals": 4, "npxg": 1.98, "difference": 2.02}))
    assert over[0]["weight"] == fr.NOISE and over[0]["lean"] == 0 and "flatter" in over[0]["text"]
    under = fr._finishing(_report(finishing={"np_goals": 0, "npxg": 1.62, "difference": -1.62}))
    assert "undersell" in under[0]["text"]


def test_a_hot_spell_is_noise_and_only_a_collapse_that_has_carried_leans():
    hot = {"recent_xgi90": 1.05, "before_xgi90": 0.45, "ratio": 2.35, "recent_shots90": 4.4, "before_shots90": 1.7,
           "evidence": {"ratio": 0.99, "ci": [0.95, 1.03], "n": 2382}}
    assert fr._spell(hot)[0]["weight"] == fr.NOISE and fr._spell(hot)[0]["lean"] == 0
    collapse = {**hot, "recent_xgi90": 0.05, "ratio": 0.11, "evidence": {"ratio": 0.8, "ci": [0.7, 0.9], "n": 300}}
    assert fr._spell(collapse)[0]["weight"] == fr.CARRIES and fr._spell(collapse)[0]["lean"] == -1


def test_verdict_counts_carrying_leans_fully_context_by_half_and_a_minutes_doubt_caps_it():
    lines = [fr._line("Chances", "", fr.CARRIES, 1), fr._line("Fixtures", "", fr.CARRIES, 1), fr._line("Finishing", "", fr.NOISE, 1)]
    v = fr._verdict(lines)
    assert v["label"] == "backs him" and v["score"] == 2.0 and "finishing" not in v["text"]
    assert fr._verdict(lines + [fr._line("Minutes", "", fr.CARRIES, -1)])["label"] == "mixed"
    against = fr._verdict([fr._line("Chances", "", fr.CARRIES, -1), fr._line("Creation", "", fr.CONTEXT, -1)])
    assert against["label"] == "against him" and against["score"] == -1.5
