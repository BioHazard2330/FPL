# Product

## Register

product

## Users

One user: the person who owns and runs this codebase. An aerospace engineering
grad student with a CFD/numerical-methods background, comfortable with dense
quantitative data, uncomfortable with fluff. Not a multi-tenant product, not a
public-facing tool, not designed for a stranger to onboard into. The person
using this already understands FPL deeply and wants the model's verdict fast,
not explained from first principles.

Context of use: checking this on a laptop, usually in short bursts before a
gameweek deadline or during a live match, sometimes idly between matches to
see if anything changed. Not a leisurely browse - a fast, confident read.

## Product Purpose

Real-time FPL (Fantasy Premier League) decision support. One question,
answered well every time: **what should I do right now, and why**. A real
Python backend (optimizer, projections, decision engine, football
intelligence - all already built, real, and authoritative) computes the
actual answer; this frontend's only job is presenting that answer with the
confidence and clarity of a sports broadcast graphics package, not a SaaS
admin panel.

Success looks like: opening the app and understanding the verdict in under
three seconds, the way a viewer reads a scoreboard bug during a match, not
the way someone reads a quarterly report.

## Brand Personality

**Confident. Broadcast. Decisive.**

The explicit direction (user's own choice among offered aesthetic lanes):
**maximalist broadcast** - the visual energy of live sports graphics
packages (match-day scoreboard bugs, half-time stat graphics, transfer-deadline-day
build-up graphics), not a financial dashboard and not a generic AI-generated
admin panel. Real color blocks, real scale drama, real typographic weight -
never mistaken for a spreadsheet, a SaaS trial dashboard, or a crypto
tracker.

This is a maximalist exception, granted explicitly and repeatedly by the
user ("no restrictions on creativity", "fuck the brand colours... this is a
complete redesign", "no time limit") - not the Restrained-by-default posture
product UI normally takes. Committed to here on purpose, not by accident.

## Anti-references

The single, explicit thing to avoid: **generic AI-generated dashboard
slop** - dark background + cyan/purple neon glow, glassmorphism cards,
monospace numerals used purely as a "tech" decoration rather than a real
typographic choice, gradient text on metrics, a hero number in a glowing
ring, identical bordered card grids repeated down the page. This was
literally built once already this session and correctly rejected - it reads
as "AI made this," not as a real product with a point of view.

No other specific anti-reference named - just don't let it read as
templated or unconsidered.

## Accessibility & Inclusion

Single sighted user, desktop only (this project has a standing, explicit
"desktop-first, permanently" rule - no mobile-viewport design or QA).
Reduced-motion support should still be real (`prefers-reduced-motion`
respected), since motion is used for state changes the user should be able
to opt out of. Color is never the only signal for a state (buy/sell/hold
verdicts, robustness, etc. always pair color with a real label/icon, not
color alone) - not because of a stated accessibility requirement, but
because this project's own decision-integrity rules already demand every
verdict be legible and unambiguous.
