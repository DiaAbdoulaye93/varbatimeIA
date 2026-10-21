---
description: Open a work session - read the plan, find the next unchecked task, propose a plan and wait
---

Open a new work session on this repo. Answer the user in French.

1. Read `CLAUDE.md` in full (conventions, forbidden items, `## Journal`).
2. Read `IMPLEMENTATION.md` §7 (session plan) and §9 (decisions that must not be reopened). Read other sections only if the next task needs them.
3. Run `git status --short` and `git log --oneline -10` to see where the work stopped.
4. Identify the **first unchecked box** (`- [ ]`) in §7, within the earliest session whose "Fini quand" checklist is not complete. Never pick a task from a later session or anything tagged `[V2]`.
5. Read the files that this task touches (existing code, prompts in `backend/app/pipeline/prompts/`, `data/DATASET.md` if relevant).
6. Propose a plan in **10 lines maximum**: files to create or modify, key technical choices, how it will be tested, the commit message(s) planned (`feat(scope): ...` format). Flag any library API that must first be checked with Context7.
7. Mention any blocker (missing tool, missing env var, open question).

**Stop there and wait for the user's explicit validation before writing any code.**
