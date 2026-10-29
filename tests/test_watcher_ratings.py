from fpl_agent.ingestion import watcher_ratings as wr

FORMAT_A = """<p>Here's how I rated the players and how you rated the players.</p>
<h3>Aston Villa</h3>
<p>Nicolas Jackson:</p><p>Brimming with confidence. Took the opening goal brilliantly.</p><p>9</p>
<p>Subs:</p><p>Ibrahim Mbaye (on 58, Alysson)</p><p>Instant impact after coming on.</p><p>7</p>
<p>Emiliano Buendia (on 66, Manzambi) 6</p>
<p>How did you rate the players?</p>
<p>Player of the match</p><p>Number: 11</p><p>N. Jackson</p><p>Average rating</p><p>8.73</p>
<p>Number:</p><p>11</p><p>N. Jackson</p><p>Average Rating:</p><p>8.73</p>
<p>Number:</p><p>22</p><p>I. Mbaye</p><p>Average Rating:</p><p>7.10</p>"""

FORMAT_B = """<p>Here's how I rated the players and you can see how you scored them below.</p>
<p>Everton XI</p><p>Jordan Pickford</p><p>: The England goalkeeper may be disappointed. 5</p>
<p>Subs:</p><p>Christian Norgaard (on 85, Armstrong)</p><p>: Looked rusty. 4</p>"""


def test_reporter_and_fan_scores_parse_in_both_layouts():
    a = wr.parse_ratings(FORMAT_A)
    assert ("Nicolas Jackson", 9.0) == a["reporter"][0][:2]
    assert ("Ibrahim Mbaye", 7.0) == a["reporter"][1][:2]
    assert ("Emiliano Buendia", 6.0) == a["reporter"][2][:2]
    assert ("N. Jackson", 8.73) in a["fans"] and ("I. Mbaye", 7.1) in a["fans"]
    assert a["potm"] == "N. Jackson"
    b = wr.parse_ratings(FORMAT_B)
    assert [(n, s) for n, s, _ in b["reporter"]] == [("Jordan Pickford", 5.0), ("Christian Norgaard", 4.0)]
    assert b["reporter"][0][2] == "The England goalkeeper may be disappointed."


def test_names_match_players_by_full_name_surname_or_initial():
    pool = [
        {"id": 1, "web_name": "N.Jackson", "first_name": "Nicolas", "second_name": "Jackson"},
        {"id": 2, "web_name": "Mbaye", "first_name": "Ibrahim", "second_name": "Mbaye"},
        {"id": 3, "web_name": "Nørgaard", "first_name": "Christian", "second_name": "Nørgaard"},
        {"id": 4, "web_name": "D.Jackson", "first_name": "Dan", "second_name": "Jackson"},
    ]
    assert wr._match_player("Nicolas Jackson", pool) == 1
    assert wr._match_player("N. Jackson", pool) == 1
    assert wr._match_player("I. Mbaye", pool) == 2
    assert wr._match_player("Christian Norgaard", pool) == 3
    assert wr._match_player("Jackson", pool) is None  # two Jacksons and no initial: not guessed
