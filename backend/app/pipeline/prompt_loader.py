"""Load system prompts from app/pipeline/prompts/*.md."""

from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@cache
def load_prompt(name: str) -> str:
    """Return the prompt file content; cached so every call sends byte-identical text."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
