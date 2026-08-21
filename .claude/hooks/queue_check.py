"""SessionStart hook (matchday-autonomy pass, 2026-08-22). Real, explicit
user requirement: "When I next open Claude Code for this project, the
session should automatically detect and process any pending jobs before
doing anything else." This hook is the "automatically detect" half - it
runs `fpl analysis-queue --pending` and prints the result so it lands in
the new session's own context automatically, with no manual `fpl
analysis-queue` invocation needed. The "process" half (running the
match-intelligence-analysis skill, then `fpl match-analyze`) stays a real
Claude Code reasoning step - this hook never invokes an LLM itself, same
zero-cost-runtime boundary as `ingestion/analysis_queue.py`.

Non-fatal by design: any failure here (missing venv, DB not yet migrated,
etc) must never block a session from starting - prints nothing and exits 0
rather than surfacing a hook error on every single session start.
"""
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FPL_EXE = _PROJECT_ROOT / ".venv" / "Scripts" / "fpl.exe"


def main() -> int:
    if not _FPL_EXE.exists():
        return 0
    try:
        result = subprocess.run(
            [str(_FPL_EXE), "analysis-queue", "--pending"],
            capture_output=True, text=True, timeout=20, cwd=str(_PROJECT_ROOT),
        )
    except Exception:
        return 0
    output = (result.stdout or "").strip()
    if not output or output.startswith("no pending"):
        return 0
    print("Pending qualitative-analysis jobs found - process these before other work:")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
