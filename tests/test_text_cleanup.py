from fpl_agent.models.text_cleanup import clean_display_text, strip_rhetorical_filler


def test_strips_leading_real_comma_after_article():
    assert strip_rhetorical_filler("A real, high-shot-volume attacking involvement.") == \
        "A high-shot-volume attacking involvement."


def test_strips_genuine_real_stack_mid_sentence_with_no_article():
    """The EXACT real phrase confirmed live on the FOOTBALL dashboard
    screen during the Phase 7.4 forensic audit - not article-anchored (a
    dash introduces it, not "a"/"an"), so the article-anchored pattern
    alone doesn't catch it; needed its own unconditional rule."""
    text = (
        "the single highest-value created chance in the match, from a full-back position - "
        "genuine, real creative involvement well beyond a typical defensive role this game."
    )
    cleaned = strip_rhetorical_filler(text)
    assert "genuine" not in cleaned.lower()
    # Bare "real" (no comma, no article) is deliberately left alone even
    # here - consistent with this module's own disclosed policy (protects
    # a real club name like "Real Madrid" elsewhere in the same dataset).
    assert "creative involvement well beyond a typical defensive role" in cleaned


def test_strips_leading_genuine_real_after_article():
    assert strip_rhetorical_filler("A genuine, real creative involvement for this role.") == \
        "A creative involvement for this role."


def test_strips_sentence_leading_real_comma():
    assert strip_rhetorical_filler("Real, large territorial dominance did not convert into goals.") == \
        "Large territorial dominance did not convert into goals."


def test_strips_genuinely_adverb():
    assert strip_rhetorical_filler("Genuinely getting into good positions, not a token appearance.") == \
        "Getting into good positions, not a token appearance."


def test_strips_clearly_and_obviously():
    assert strip_rhetorical_filler("This is clearly a strong performance.") == "This is a strong performance."
    assert strip_rhetorical_filler("He was obviously involved throughout.") == "He was involved throughout."


def test_leaves_normal_text_completely_untouched_no_recasing():
    """Real, confirmed regression found while building this cleanup: an
    earlier version unconditionally capitalized the first character even
    when nothing was actually stripped - corrupting short, already-correct
    evidence strings this cleanup has no business touching."""
    assert strip_rhetorical_filler("obs") == "obs"
    assert strip_rhetorical_filler("3 goals, 8 shots, 1.95 xG.") == "3 goals, 8 shots, 1.95 xG."
    assert strip_rhetorical_filler("penalty order 2 -> 1") == "penalty order 2 -> 1"


def test_does_not_strip_real_as_a_load_bearing_noun_phrase():
    """Real, disclosed scope limit - "real" is only stripped in the specific
    leading-intensifier patterns this cleanup targets, never everywhere
    indiscriminately (a genuine "real quality"/"real threat" noun phrase
    elsewhere in a sentence is left alone)."""
    text = "The real quality of the chances faced matches the goals conceded."
    assert strip_rhetorical_filler(text) == text


def test_clean_display_text_passes_none_through_unchanged():
    assert clean_display_text(None) is None


def test_clean_display_text_matches_a_real_production_example():
    """A real, verbatim example found live in `player_fpl_implications.
    reason` during the Phase 7.4 forensic audit."""
    raw = (
        "A real, high-shot-volume attacking involvement in his first Arsenal PL start - "
        "genuinely getting into good positions, not a token appearance."
    )
    cleaned = clean_display_text(raw)
    assert "real," not in cleaned.lower()
    assert "genuinely" not in cleaned.lower()
    assert "high-shot-volume attacking involvement" in cleaned
    assert "getting into good positions, not a token appearance" in cleaned
