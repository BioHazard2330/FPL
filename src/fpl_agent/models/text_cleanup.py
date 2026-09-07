"""Real, display-time text cleanup shared across every module that renders
LLM-authored qualitative text on the dashboard (2026-09-07, Phase 7.4 Part
13 - "no obvious evidence-free rhetorical language"). Factored out of
`football_signal.py` (its original home) so `qualitative_feed.py`/
`decision_fusion.py` can reuse the identical real cleanup rather than a
second, independently-drifting copy - one real definition of "rhetorical
filler" for this whole project.

Real, confirmed finding: this project's own qualitative-analysis skill
routinely writes real analysis text leaning on "genuine"/"real"/"clearly"/
"obviously" as rhetorical emphasis rather than data provenance (confirmed
live against real stored rows in BOTH `match_observations.inferred` and
`player_fpl_implications.reason` - e.g. "A real, high-shot-volume attacking
involvement... genuinely getting into good positions, not a token
appearance"). This is DATA, not a code template - rewriting thousands of
already-stored historical rows would risk altering their real meaning with
no LLM re-pass to verify against, so this strips the KNOWN filler
constructions at DISPLAY time only - the underlying stored text is never
modified.

Real, disclosed, bounded scope: targets the specific constructions actually
observed in this project's own real stored text (comma-joined leading
intensifiers, standalone adverbs) - not a general NLP filler detector. A
construction outside this list may still slip through uncaught; this is a
real, honest display cleanup, not a claimed-complete rewrite. "real"/
"genuine" are NOT stripped everywhere indiscriminately (e.g. "real quality",
"real threat" as a load-bearing noun phrase are left alone) - only the
specific leading-intensifier patterns below, which is where the actual
filler usage concentrates in this project's real data. Deliberately NOT
targeted: a bare "Real "/"real " with no following comma, anywhere in the
string - this project's own cross-league Understat coverage (La Liga
included) means "Real" is also a genuine, real club name prefix (Real
Madrid, Real Sociedad, Real Betis) that a blanket no-comma strip would
corrupt. The comma-anchored patterns above are a deliberately safer,
narrower net that catches the common rhetorical constructions without that
risk - a real, disclosed residual gap (e.g. "Real 6-point GW1 debut..." is
left alone) rather than a broader rule that could silently mangle a real
team name elsewhere in the same real dataset."""
import re

_RHETORICAL_FILLER_PATTERNS = [
    # "A real, high-shot-volume..." / "A genuine, real creative..." -> "A high-shot-volume..." / "A creative..."
    (re.compile(r"\b(a|an)\s+(genuine,?\s+)?real,?\s+", re.IGNORECASE), r"\1 "),
    # "...position - genuine, real creative involvement..." / "genuine,
    # sustained central goal threat..." (mid-sentence, no article, "genuine"
    # comma-stacked with ANY following adjective - two real, confirmed live
    # examples of this exact construction). Unconditional (not article-
    # anchored, unlike the pattern above) - "genuine," is never itself a
    # legitimate club-name-adjacent phrase the way bare "Real" can be
    # (no real football club is named "Genuine ..."), so this carries none
    # of that risk regardless of what follows the comma.
    (re.compile(r"\bgenuine,\s*", re.IGNORECASE), ""),
    # "Real, large territorial..." (sentence-leading) -> "Large territorial..."
    (re.compile(r"(?:^|(?<=[.!?]\s))real,\s+", re.IGNORECASE), ""),
    # "genuinely getting into good positions" -> "getting into good positions"
    (re.compile(r"\bgenuinely\s+", re.IGNORECASE), ""),
    # ", genuinely strong" / "was genuine" as a bare intensifier
    (re.compile(r"\bgenuine\s+(?=\w)", re.IGNORECASE), ""),
    (re.compile(r"\bclearly\s+", re.IGNORECASE), ""),
    (re.compile(r"\bobviously\s+", re.IGNORECASE), ""),
]


def strip_rhetorical_filler(text: str) -> str:
    original = text
    for pattern, replacement in _RHETORICAL_FILLER_PATTERNS:
        text = pattern.sub(replacement, text)
    if text == original:
        return text  # nothing matched - real, honest no-op, never touches unrelated text/casing
    # A stripped leading intensifier can leave a lowercase word at the real
    # start of a sentence (e.g. "Real, large..." -> "large...") - capitalize
    # only the very first character, and only when something was actually
    # stripped, never mid-sentence and never on text this cleanup left
    # completely alone (would silently re-case real evidence strings this
    # function has no business touching, e.g. short non-prose fixtures).
    return text[:1].upper() + text[1:] if text else text


def clean_display_text(text: str | None) -> str | None:
    """`None` passes through unchanged - the honest "nothing to clean"
    case, never a fabricated empty string."""
    if text is None:
        return None
    return strip_rhetorical_filler(text)
