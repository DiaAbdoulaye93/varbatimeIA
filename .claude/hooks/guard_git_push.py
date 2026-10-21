"""PreToolUse hook: block `git push` when a sensitive file is tracked or staged.

Blocked paths: any .env file (except .env.example), any kubeconfig, anything under out/.
Exit 2 blocks the tool call; stderr explains why to Claude and the user.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

PROJECT_DIR = Path(__file__).resolve().parents[2]
PUSH_RE = re.compile(r"\bgit\b[^;&|\n]*\bpush\b")


def is_sensitive(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name.lower()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if name == "kubeconfig" or name.endswith(".kubeconfig"):
        return True
    return "out" in p.parts[:-1]


def git_paths(*args: str) -> set[str]:
    result = subprocess.run(
        ["git", *args], cwd=PROJECT_DIR, capture_output=True, text=True
    )
    return set(result.stdout.splitlines()) if result.returncode == 0 else set()


def main() -> int:
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    if not PUSH_RE.search(command):
        return 0
    # Staged changes plus everything already tracked: both end up in the push.
    paths = git_paths("diff", "--cached", "--name-only") | git_paths("ls-files")
    leaks = sorted(p for p in paths if is_sensitive(p))
    if leaks:
        print(
            "git push blocked: sensitive files are in the git index:\n  "
            + "\n  ".join(leaks)
            + "\nRemove them with `git rm --cached <file>` and check .gitignore.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
