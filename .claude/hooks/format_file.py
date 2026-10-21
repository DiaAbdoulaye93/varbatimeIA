"""PostToolUse hook: format the file Claude just edited.

- .py -> ruff check --fix + ruff format (via `uv run` in backend/ when available)
- .ts -> prettier --write (local install in frontend/, never downloaded on the fly)

Exit codes follow the Claude Code hook contract:
  0 = ok, 1 = non-blocking warning shown to the user, 2 = feedback sent back to Claude.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_DIR / "backend"
FRONTEND_DIR = PROJECT_DIR / "frontend"


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def find_uv() -> str | None:
    # The standalone installer puts uv in ~/.local/bin, which may not be on PATH yet.
    fallback = Path.home() / ".local" / "bin" / ("uv.exe" if sys.platform == "win32" else "uv")
    return shutil.which("uv") or (str(fallback) if fallback.exists() else None)


def ruff_cmd() -> list[str] | None:
    uv = find_uv()
    if uv and (BACKEND_DIR / "pyproject.toml").exists():
        return [uv, "run", "--project", str(BACKEND_DIR), "ruff"]
    if shutil.which("ruff"):
        return ["ruff"]
    return None


def format_python(path: Path) -> int:
    ruff = ruff_cmd()
    if ruff is None:
        print(
            f"[hook] ruff not found, {path.name} was NOT formatted (install uv).", file=sys.stderr
        )
        return 1
    cwd = BACKEND_DIR if BACKEND_DIR.exists() else PROJECT_DIR
    check = run([*ruff, "check", "--fix", str(path)], cwd)
    run([*ruff, "format", str(path)], cwd)
    if check.returncode != 0:
        # Unfixable lint errors: hand them back to Claude so it fixes them.
        print(check.stdout + check.stderr, file=sys.stderr)
        return 2
    return 0


def format_typescript(path: Path) -> int:
    npx = shutil.which("npx")
    if npx is None or not (FRONTEND_DIR / "node_modules" / ".bin").exists():
        print(
            f"[hook] prettier unavailable (frontend not installed), {path.name} NOT formatted.",
            file=sys.stderr,
        )
        return 1
    result = run([npx, "--no-install", "prettier", "--write", str(path)], FRONTEND_DIR)
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        return 1
    return 0


def main() -> int:
    payload = json.load(sys.stdin)
    file_path = payload.get("tool_input", {}).get("file_path")
    if not file_path:
        return 0
    path = Path(file_path).resolve()
    # Only format files that belong to this repo (skip scratch files elsewhere).
    if not path.exists() or not path.is_relative_to(PROJECT_DIR):
        return 0
    if path.suffix == ".py":
        return format_python(path)
    if path.suffix == ".ts":
        return format_typescript(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
