# SmartOfficeAI360 agent instructions

## Read first

1. Read `AI_CONTEXT.md`.
2. Read `ai-memory/INDEX.md` and the files in its required order.
3. Read the relevant ADR before changing an established boundary.

## Invariants

- Preserve the dirty worktree and unrelated user changes.
- QLVB automation uses the authenticated external Edge CDP session at `127.0.0.1:9223`.
- The CDP workflow does not launch or close the externally owned browser, context, or page.
- Category order is incoming registry, forwarded processed, then processed; pending is excluded by default.
- Match menu labels exactly after normalization, reject mojibake, and use bounded post-click polling.
- Validate the visible `#div_data_list` table structurally; obtain document identifiers only from its selected row.
- Keep NeoRemoting, safe parsing, authenticated direct download, signature, and integrity contracts intact.

## Forbidden actions

- Do not reset, stash, clean, or overwrite unrelated worktree changes.
- Do not expose credentials, cookies, session URLs, document contents, or user data in logs.
- Do not claim whole-repository success when only focused checks pass.
- Do not run live QLVB, deploy, push, migration, OCR, AI, or Planner work unless explicitly authorized.

## Required checks

- Run the focused tests relevant to the change with the pinned interpreter.
- Run `python scripts/validate_ai_memory.py` and `git diff --check` after memory edits.

## Worktree preservation

Use explicit file paths for staging or edits. Never use broad cleanup commands. Leave this repository uncommitted unless the task explicitly authorizes a commit.
