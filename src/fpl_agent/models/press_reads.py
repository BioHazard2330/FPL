"""PRESS READS: what each manager has said about his players, read from the stored team-news summaries of his press
conference (fantasyfootballscout's per-club `latest_news`, synced with the predicted lineups) - 2026-11-27, the manager:
"learn from managers".

Each summary is split into sentences and each sentence into clauses; a clause naming one or more of the club's players
(web name, surname or full name, accents folded) is read for what it says about them, by the first matching class:
  out      - miss out / set to miss / ruled out / sidelined / remain(s) out / won't feature / absent
  doubt    - doubt / fitness test / touch and go / assessed / not clear whether / sick / illness / hopes to be back
  back     - available again / recovered / back in training / fit again / returns / comes (straight) back
  in       - start / recall / come(s) in / the nod / back into the XI / same XI / led the line / earmarked / praise
  dropped  - a player named after "in for" / "over" / "instead of" / "ahead of", or benched / rested / dropped
A clause that only lists more names ("along with Y and Z") continues the clause before it; an injury in brackets
("Hato (back)") is never read as a verdict. Every read carries the sentence it came from, so the evidence is always the
summary's own words. A rule over wording, not a fitted classifier: read the sentence before acting on the label."""
import re
import sqlite3
import unicodedata

CLASSES = [
    ("out", r"\b(miss(es|ing)? out|set to miss|will miss|ruled out|sidelined|remains? out|won'?t feature|absent|out for (the|a|several|weeks|months)|long-term absentee)\b"),
    ("doubt", r"\b(doubt(ful)?|fitness test|late test|touch and go|being assessed|assessed|not clear whether|sick|illness|hopes? to be back|question mark over)\b"),
    ("back", r"\b(available again|recovered|back in training|fit again|returned to training|returns?|comes? (straight )?back|is back|nearing a return|close to (a )?return)\b"),
    ("in", r"\b(start(s|ed|ers?)?|recall(s|ed)?|come(s)? in|coming in|get(s)? the nod|back into the xi|same (xi|line-up|team)|led the line|earmarked|praise)\b"),
]
DROPPED = r"\b(benched|rested|dropped|left out)\b"
REPLACED = r"\b(?:in for|over|instead of|ahead of)\s+([A-Z][\w'\-]+(?:\s[A-Z][\w'\-]+)?)"
CLAUSE = r"[,;:]|\b(?:but|although|however|while|whereas|meanwhile|though)\b"
LIST_ON = r"\s*(along with|as well as|plus|nor)\b"


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def _sentences(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z£\"'])", text.replace("\n", " ")) if x.strip()]


def reads(conn: sqlite3.Connection, team_ids: list[int] | None = None) -> dict[int, list[dict]]:
    """Per player id: the reads from his club's latest press summary, with label, sentence and when it was fetched."""
    rows = conn.execute(
        "SELECT p.team_id, p.latest_news, p.fetched_at, t.short_name FROM predicted_lineup_teams p JOIN teams t ON t.id = p.team_id "
        "WHERE p.latest_news IS NOT NULL AND p.latest_news != ''").fetchall()
    out: dict[int, list[dict]] = {}
    for team_id, text, fetched, short in rows:
        if team_ids is not None and team_id not in team_ids:
            continue
        players = conn.execute("SELECT id, web_name, first_name, second_name FROM players WHERE team_id = ?", (team_id,)).fetchall()
        keys = []
        for pid, web, first, second in players:
            names = {_fold(web or "")}
            if second:
                names.add(_fold(second))
                names.add(_fold(f"{first} {second}"))
                names.add(_fold(second.split()[-1]))
            keys.append((pid, sorted({n for n in names if len(n) >= 4}, key=len, reverse=True)))
        for sent in _sentences(text):
            replaced = set()
            for m in re.finditer(REPLACED, sent):
                target = _fold(m.group(1))
                replaced |= {pid for pid, ns in keys if any(n == target or n == target.split()[-1] for n in ns)}
            carry = None
            pending: list[int] = []
            listing = False
            for clause in re.split(CLAUSE, sent):
                if not clause or not clause.strip():
                    continue
                low = _fold(re.sub(r"\([^)]*\)", "", clause)).replace("out-of-sorts", "").replace("out of sorts", "")
                named = [pid for pid, ns in keys if any(re.search(r"\b" + re.escape(n) + r"\b", low) for n in ns)]
                label = next((c for c, pat in CLASSES if re.search(pat, low)), None)
                if label is None and re.search(DROPPED, low):
                    label = "dropped"
                if label is None and named and re.match(LIST_ON, low):
                    label, listing = carry, True
                elif label is None and named and listing:
                    label = carry
                elif label is not None:
                    listing = False
                if label is not None:
                    carry = label
                if label is not None and not named and pending:
                    named = pending
                pending = named if label is None else []
                for pid in named:
                    lab = "dropped" if pid in replaced else label
                    if lab is None:
                        continue
                    out.setdefault(pid, []).append({"label": lab, "sentence": sent[:400], "team": short, "fetched_at": fetched})
    return out


def latest_label(entries: list[dict]) -> str | None:
    """The strongest read for a player: out over doubt over dropped over back over in."""
    order = ["out", "doubt", "dropped", "back", "in"]
    labs = {e["label"] for e in entries}
    return next((o for o in order if o in labs), None)
