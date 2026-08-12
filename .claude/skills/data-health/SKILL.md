---
name: data-health
description: >
  Run the deterministic health checks (database, migrations, disk, config, source
  connectivity). Trigger: "is the data healthy", "run doctor", "check the system".
---

# Data Health

## Purpose

Thin wrapper - `fpl doctor` already does all the deterministic checking (section 109).
This skill's only job is to run it and translate a FAIL into plain language with a
concrete next step, not to re-derive the checks in prose.

## Process

`.venv/Scripts/fpl.exe doctor`

## Output

If everything's OK, say so in one line - don't enumerate every passing check unless
asked for detail. If anything FAILs:

- `database`/`migrations` FAIL → likely means `fpl sync` hasn't been run yet, or the
  DB file is missing/corrupted. Suggest `fpl sync` first; if that doesn't fix it,
  this needs actual debugging, not a scripted response.
- `disk` FAIL → low disk space, not an app bug. Tell the user directly.
- `sources` FAIL → check `fpl source-status` for which source and why (network,
  rate limit, schema change on FPL's side).
