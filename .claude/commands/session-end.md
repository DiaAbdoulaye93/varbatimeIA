---
description: Close a work session - checks, update §7 boxes and the journal, propose the commit
---

Close the current work session. Answer the user in French.

1. Run the checks that apply (skip and say so if the folder does not exist yet):
   - `cd backend && uv run ruff check . && uv run pytest -q`
   - `cd frontend && npm run lint && npm run build`
   Report results faithfully, including failures with their output.
2. In `IMPLEMENTATION.md` §7, check (`- [x]`) only the boxes whose work is actually done, committed and tested. Do not check a box that is partially done; say what is missing instead.
3. Append one line to `## Journal` in `CLAUDE.md`, format: `- YYYY-MM-DD — <what was done>. Bloquant : <blocker or "rien">.` (in French).
4. Show `git status --short` and propose a commit message for the remaining changes (`chore(docs): close session N` or more specific). Do not commit or push without the user's approval.
5. State in 3 lines what the next session should start with.
