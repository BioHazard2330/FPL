"""
PreToolUse guard for the Bash tool, scoped to the fpl-agent project (section 81
secrets, section 101 destructive-command protection). Reads the tool call as JSON
on stdin; if the command is destructive or risks committing a real .env, emits a
deny decision on stdout. Otherwise exits silently (allow).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DESTRUCTIVE_PATTERNS = [
    (re.compile(r"\brm\s+-rf\b.*\b(data[\\/]|fpl\.db)\b", re.IGNORECASE), "rm -rf targeting the project's data/DB files"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard discards uncommitted work"),
    (re.compile(r"\bgit\s+push\s+.*--force\b"), "git push --force can overwrite remote history"),
    (re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE), "raw DROP TABLE - use a migration instead"),
    (re.compile(r"\bDELETE\s+FROM\s+\w+\s*;", re.IGNORECASE), "DELETE FROM without a WHERE clause"),
]

_GIT_ADD_COMMIT = re.compile(r"\bgit\s+(add|commit)\b")
_BROAD_ADD = re.compile(r"\bgit\s+add\s+(\.|-A\b|--all\b)")
_ENV_TOKEN = re.compile(r"(^|[\s/\\])\.env($|[\s\"'])")


def _deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _staged_real_env_file() -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return False
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if path.endswith(".env") and not path.endswith(".env.example"):
            return True
    return False


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        return

    for pattern, reason in _DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            _deny(f"Blocked (fpl-agent bash guard): {reason}. Command: {command!r}")

    if _GIT_ADD_COMMIT.search(command):
        if _ENV_TOKEN.search(command) and ".env.example" not in command:
            _deny("Blocked (fpl-agent bash guard): command directly references a real .env file - never commit secrets.")
        if _BROAD_ADD.search(command) and _staged_real_env_file():
            _deny("Blocked (fpl-agent bash guard): a real .env file is present in `git status` and this broad `git add` would stage it.")


if __name__ == "__main__":
    main()
