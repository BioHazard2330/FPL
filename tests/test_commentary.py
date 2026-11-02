from fpl_agent.ingestion.commentary import _norm


def test_club_names_normalise_across_sources():
    assert _norm("Nott'm Forest") == "nottingham forest"
    assert _norm("Man Utd") == "manchester united"
    assert _norm("Spurs") == "tottenham"
    assert _norm("Brighton & Hove Albion") == "brighton  hove albion"
