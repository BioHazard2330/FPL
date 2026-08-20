# Continuation prompt — paste this to resume

I'm continuing work on `fpl-agent` (FPL 2026-27 intelligence system). Read
`fpl-agent/CLAUDE.md` fully first — it's the live source of truth, kept
current, most recent section is "Session 2026-08-20/21: pre-GW1 hardening,
chip-horizon correction, squad finalization" at the bottom. This prompt is
just a pointer, not a replacement for reading it.

**Check real time remaining before anything else** — GW1 deadline is
2026-08-21T17:30:00Z. Run `date -u` and compare.

## Immediate priority: finalize and lock the GW1 squad

Not yet confirmed by the user. Last built candidate (Haaland forced
captain, Fernandes forced vice, `bench_weight=0.5`, exactly £100.0m):

- GKP: Raya
- DEF: Guéhi, Dalot, N.Williams, Shaw
- MID: B.Fernandes, Anderson, Zubimendi
- FWD: Haaland, Gyökeres, Thiago
- Bench: Dubravka, Hume, Yarmoliuk, Gomez
- Headline: 56.61 xP (vs 57.92 at default bench_weight=0.1, a real
  -1.31 cost for a genuinely playable bench instead of fodder)

Rebuild command (ids may have drifted if a resync happened — re-resolve by
name if `optimise_squad` returns different ids):
```
optimise_squad(conn, n_gw=1, objective='median', must_include_ids={haaland_id, fernandes_id}, bench_weight=0.5)
```

Open sub-decisions the user hasn't closed:
- **Zubimendi vs Rice** — Rice is the stronger pick on real data (higher
  reliability AND median), Zubimendi's only edge is much lower ownership
  (rank-differential value). User's call.
- Re-run `fpl transfers --squad <ids> --search --horizon 5` against
  whatever squad actually gets locked — the last real run (Gyökeres→João
  Pedro at GW2, no hits) was against a similar but not identical squad.
- **Do not** recommend using any chip in GW1-4 without a real, visible
  reason (confirmed: zero blank/double GWs exist in GW1-5 this season;
  chips are eligible through GW19). A short `--horizon` on `season-sim`
  makes its own chip-DP output misleading — this is a real, disclosed,
  still-open limitation (see CLAUDE.md).

## Also still open, lower priority

- `fpl sync-eo --event 1` — genuinely time-gated until the GW1 deadline
  passes. Run it for real once it has, confirm non-degenerate sample
  output, per CLAUDE.md's existing note on this.
- `fpl live-watch` / dashboard Live Tracking panel — built and unit-tested
  but not yet outcome-verified against a real live match (GW1 hasn't
  kicked off as of this writing). Worth a real spot-check once it has.
- Cross-league data coverage beyond the current 6 free leagues (La Liga/
  Bundesliga/Serie A/Ligue 1/Russia/PL) — a real, quantified, scoped-out
  gap (~13/18 new-to-PL signings this window have zero signal). Not a
  quick fix; a real new-source-integration project if ever picked up.

## Working rhythm (carry forward)

- **No subagents for this project** — burns tokens, do everything
  directly (standing instruction).
- Build → test → live-verify against the real DB/API → sanity-check
  real-world magnitudes by hand → commit locally. Never push without being
  asked.
- The highest-value bug-finding pattern this session: check a *specific
  named real player* against *real external evidence* (official API,
  community screenshots, news) rather than reviewing code in the abstract.
  Every real bug found this session came from that, not from re-reading
  code.
- 444/444 tests passing as of this handoff. Keep it that way — run the
  full suite before every commit.
- Dashboard: `fpl dashboard` regenerates `data/dashboard.html` on demand;
  `fpl run-scheduled` regenerates it automatically every cycle (15-360min,
  self-adapting to real deadline proximity). Open the file in a browser and
  leave the tab open — it self-refreshes every 60s.
