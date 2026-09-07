import pytest

from fpl_agent.cli.main import _parse_squad_option


def test_none_means_omitted_and_passes_through():
    assert _parse_squad_option(None) is None


def test_comma_separated_ids_parsed():
    assert _parse_squad_option("1,2,3") == [1, 2, 3]


def test_empty_string_raises_a_clear_error_instead_of_silently_returning_none():
    """Real bug found via mypy 2026-09-07: an empty/whitespace `--squad`
    value used to fall through the same `not squad` check as a genuinely
    omitted option and return None - every required-squad CLI command
    (captain/transfers/season-sim/final-check/rate-team) then crashed with
    a confusing TypeError deep inside optimizer code instead of a clear
    message naming the actual problem."""
    with pytest.raises(SystemExit, match="non-empty"):
        _parse_squad_option("")
    with pytest.raises(SystemExit, match="non-empty"):
        _parse_squad_option("   ")
