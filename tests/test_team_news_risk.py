from fpl_agent.models.team_news_risk import flag_squad_rotation_risk, rotation_risk_snippet


def _seed_ref(conn):
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','t0')")
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )


def _seed_player(conn, player_id, web_name, second_name=None):
    conn.execute(
        "INSERT INTO players (id, code, web_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,?,1,1,'a','t0')",
        (player_id, player_id, web_name, second_name),
    )


def _seed_news(conn, latest_news):
    conn.execute(
        "INSERT INTO predicted_lineup_teams (team_id, formation, next_match_text, latest_news, "
        "source, source_tier, fetched_at) VALUES (1, '4-3-3', 'Test FC (H)', ?, 'test', 'strong_reporter', 't0')",
        (latest_news,),
    )


def test_real_osula_style_three_way_rotation_is_flagged(db_conn):
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "Osula")
    _seed_news(db_conn, "It'll be two from three of Will Osula, Yoane Wissa and Nick Woltemade up top.")
    db_conn.commit()

    snippet = rotation_risk_snippet(db_conn, 1)

    assert snippet is not None
    assert "Osula" in snippet


def test_real_dorgu_style_named_threat_is_flagged(db_conn):
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "Dorgu")
    _seed_news(db_conn, "Matheus Cunha may miss out, unless he displaces Patrick Dorgu on the left.")
    db_conn.commit()

    snippet = rotation_risk_snippet(db_conn, 1)

    assert snippet is not None
    assert "Dorgu" in snippet


def test_no_evidence_returns_none_not_a_fabricated_risk(db_conn):
    """Real, honest negative case (Foden's actual state this session): a
    player predicted starting whose team's news simply never mentions them -
    must never fabricate a risk that isn't actually in the source text."""
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "Foden")
    _seed_news(db_conn, "Matheus Nunes is a concern, Jeremy Doku is out for weeks.")
    db_conn.commit()

    assert rotation_risk_snippet(db_conn, 1) is None


def test_name_mention_without_a_hedge_keyword_is_not_flagged(db_conn):
    """A player's name appearing in the news at all isn't itself a risk -
    only a name alongside a real hedge/rotation keyword in the same sentence."""
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "Haaland")
    _seed_news(db_conn, "Erling Haaland scored twice in the friendly and looks sharp for the opener.")
    db_conn.commit()

    assert rotation_risk_snippet(db_conn, 1) is None


def test_keyword_in_a_different_sentence_does_not_false_positive(db_conn):
    """Sentence-scoped, not paragraph-wide - a hedge phrase about a DIFFERENT
    player in the same news blob must not spuriously flag this one."""
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "Saka")
    _seed_news(db_conn, "Bukayo Saka is fit and ready to start. Elsewhere, the backup keeper is a doubt for Friday.")
    db_conn.commit()

    assert rotation_risk_snippet(db_conn, 1) is None


def test_no_predicted_lineup_data_at_all_returns_none(db_conn):
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "Osula")
    db_conn.commit()

    assert rotation_risk_snippet(db_conn, 1) is None


def test_real_dalot_style_any_one_of_rotation_is_flagged(db_conn):
    """Real gap found 2026-08-21 (continued user pushback after the first
    fix shipped): "any one of X, Y or Z" is functionally identical rotation
    language to "two from three" but phrased differently - the original
    keyword list missed it entirely for a real case (Man Utd right-back)."""
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "Dalot")
    _seed_news(db_conn, "At right-back, it could be any one of Diogo Dalot, Noussair Mazraoui or Leny Yoro.")
    db_conn.commit()

    snippet = rotation_risk_snippet(db_conn, 1)

    assert snippet is not None
    assert "Dalot" in snippet


def test_real_stay_of_execution_phrasing_is_flagged(db_conn):
    """Real gap found 2026-08-21: a conditional "he's only in the side
    because someone else isn't fit yet" read (Sunderland's O'Nien)."""
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "O'Nien")
    _seed_news(db_conn, "Luke O'Nien has a stay of execution for now, then.")
    db_conn.commit()

    snippet = rotation_risk_snippet(db_conn, 1)

    assert snippet is not None
    assert "O'Nien" in snippet


def test_second_name_collision_does_not_false_positive(db_conn):
    """Real bug caught live 2026-08-21: Raya's second_name is "Raya Martín" -
    matching on the last word alone ("Martin") false-positived against an
    unrelated "Martin Zubimendi" mention in the same sentence. web_name-only
    matching must not flag Raya here."""
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "Raya", second_name="Raya Martin")
    _seed_news(db_conn, "Arteta has alternatives to Rice, such as Martin Zubimendi and Kai Havertz.")
    db_conn.commit()

    assert rotation_risk_snippet(db_conn, 1) is None


def test_flag_squad_rotation_risk_returns_only_flagged_players(db_conn):
    _seed_ref(db_conn)
    _seed_player(db_conn, 1, "Osula")
    _seed_player(db_conn, 2, "Haaland")
    _seed_news(db_conn, "It's two from three for Osula up top. Haaland scored twice and is nailed on.")
    db_conn.commit()

    flags = flag_squad_rotation_risk(db_conn, [1, 2])

    assert len(flags) == 1
    assert flags[0].player_id == 1
    assert flags[0].web_name == "Osula"
    assert "Osula" in flags[0].snippet
