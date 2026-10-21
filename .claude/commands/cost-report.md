---
description: Print calls, tokens, cost and duration per pipeline step for the latest analysis (README §5)
argument-hint: "[analysis_id]"
---

Produce the token/cost report for an analysis. Answer the user in French.

1. Find the SQLite database path from `backend/app/config.py` (database URL setting) or `backend/.env`. If no database exists yet, look for `out/result.json` written by `run_pipeline_cli.py` and use its usage section instead.
2. Target analysis: `$ARGUMENTS` if given, otherwise the most recent analysis with `status = 'done'`.
3. Query the `llm_calls` table (use `sqlite3` if installed, otherwise `python -c` with the standard `sqlite3` module). Group by `step` (preprocess / extract / cluster / synthesize) and return: number of calls, model, `input_tokens`, `cache_creation_tokens`, `cache_read_tokens`, `output_tokens`, total `duration_ms`.
4. Compute the estimated cost with the pricing table in `backend/app/config.py` (never invent prices; if the table is missing, say so and show tokens only). Convert to FCFA with the rate defined in config if present.
5. Also report: number of verbatims received / processed / skipped, and wall-clock duration of the analysis (`finished_at - created_at`).
6. Output a Markdown table ready to paste into README §5, followed by a one-line summary: "200 verbatims = X appels, Y tokens, ~Z FCFA, en N secondes". Read-only: do not modify any file.
