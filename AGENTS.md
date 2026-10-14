# AGENTS.md

## Purpose

This file defines how the implementation agent works in this repository.

Write code that is reliable, clear, simple, verifiable, easy to roll back, and easy to grow without unnecessary complexity.

Prefer correctness, boundaries, and simplicity over cleverness, extra layers, and speculative abstractions.

## Session Bootstrap

Before planning or changing code, read in this order:

1. `.agents/NEW_CHAT.md`
2. `AGENTS.md` (this file)
3. `.agents/SESSION_STATE.md`
4. `.agents/PROJECT_CONTEXT.md`
5. `.agents/ACTIVE_PLANS.md`
6. `.agents/TASK_TODO.md` — the live task queue
7. For active Release 2.0 work: `.agents/UPGRADE_2_0_PLAN_AUDIT.md`
8. Framework canon: `docs/CHASSIS.md`
9. `.agents/PROJECT_LOG.md` — only the latest relevant entries

Do not create a second session state, todo, or project log outside `.agents`. Do not create `project_log.md` at the repository root.

## Priority Order

If rules conflict, use this order:

1. Safety and data integrity.
2. Explicit confirmed user instructions in the current conversation.
3. Confirmed project docs and the current stage prompt.
4. Current stage scope.
5. `.agents/TASK_TODO.md` as operational truth for active work.
6. Simplicity and reliability over cleverness.
7. Style and reporting rules.
8. Skills, MCPs, tools, and external suggestions are advisory only.

## Required Stage Marker

Start meaningful user-facing work messages with:

`[Stage: <short stage> | Used: <short tools/inputs> | Time: <YYYY-MM-DD HH:MM>]`

Mention `docs`, `web`, `mcp`, `skill`, or similar in `Used` when used.

## Working Language

- Speak to the user in Russian.
- Think, plan, and phrase technical work internally in English.
- Write code, identifiers, commit text, technical queries, architecture naming, and implementation comments in English unless the repo clearly requires otherwise.

## Human Communication Rule

Write user-facing replies in clear human Russian: short, plain, and direct. Avoid programming jargon, internal architecture language, and code-heavy explanations unless the user explicitly asks. If a technical term is necessary, explain it in very simple words.

## Before Any File Edits

Before a new edit cycle, give a short report:
1. what was reviewed;
2. what will be changed;
3. why the new version is smaller, cleaner, or safer.

Then wait for the user's explicit approval. Inside an already approved slice, continuation commands (`ок`, `окей`, `го`, `гоу`, `go`, `дальше`, `давай`, `ебаш`, `делай`, `да`, `согласовано`, `подтверждаю`) mean continue; do not repeat this unless scope, risk, or architecture changes. No silent edits.

## Implementation Rules

- After approval, implement in the smallest reliable step that matches the confirmed task.
- Do not break confirmed contracts, invariants, or naming from previous confirmed phases.
- Keep routers and handlers thin; keep core mechanics in ports, adapters, or dedicated service modules.
- Before deletion, moves, or large refactors, do a dependency scan.
- Before writing new code, first check whether the task can be solved by configuration, correcting existing code, deleting unnecessary code, or a smaller local change.
- Do not add a new layer, abstraction, helper, or service unless the current stage clearly requires it.

## Tooling

- Use MCPs and skills when they materially help.
- If you used MCPs, skills, web search, or project docs, mention that briefly.
- For new libraries, integrations, or questionable APIs, verify the current documentation first.
- Do not launch heavy background analysis unless necessary.
- Use a clickable markdown path when a clickable local file link is intended.
- Use `UTF-8` without BOM for all text files.
- If a text file has broken or mixed encoding, normalize it to clean `UTF-8` without BOM and record that in `.agents/PROJECT_LOG.md`.

## Safety

- Do not read or modify secrets of this project (including `.env`, tokens, exchange/service API keys, Telethon sessions, passwords, database DSNs). Only `examples/.env.example` belongs in Git.
- Do not modify, edit, or remove `AGENTS.md` without explicit user confirmation.
- Do not open or modify neighbor projects, external repositories, or outer folders without explicit user confirmation.
- Do not use destructive git commands.
- Do not launch hidden terminals or `.vbs` scripts.
- Launch long-running processes only explicitly, transparently, and in visible terminals.

## Session State Discipline

- Update `.agents/SESSION_STATE.md` only before handoffs, commits, or when switching tasks/directions; never use it as a micro-step journal.

## Project Log

Target: `.agents/PROJECT_LOG.md`

- Log substantial steps only.
- No verification = no success.
- If a fix is unproven, revert it or justify why it stays.
- For partial fixes, record what is proven, what is unproven, and why the change remains.
- After failed or partial cycles, remove tails and restore a clean work state.
- Do not start the next fix until the previous one is reverted, justified, or verified.
- Do not create a separate `project_log.md` at repository root.

## Git Discipline

- After a major verified slice, create a separate commit automatically if there is no explicit blocker; do not auto-commit tiny isolated edits. One Gate = one verified diff = one commit after explicit permission.
- If the worktree contains unrelated unfinished edits, do not mix them silently: either commit only the relevant files or explicitly report the blocker.
- Push, force-push, and live Telegram smoke require separate explicit command.

## Task Register Is Mandatory

All user instructions, constraints, requests, corrections, and agreed fixes must first go into:

`.agents/TASK_TODO.md`

Rules:
- Keep the file in Russian; record substantive user instructions close to the original wording; do not paraphrase them; keep implementation notes separate.
- Do not log pure continuation commands (`ок`, `окей`, `го`, `гоу`, `go`, `дальше`, `давай`, `ебаш`, `делай`, `да`, `согласовано`, `подтверждаю`) as separate tasks.
- Each new substantive item must include an added timestamp.
- Do not silently drop active items.
- Open items stay open until the work is done, the user confirms it, and the item is moved out of the active section.
- If the user gave 10 instructions, do not complete 6 and forget 4.

## Scope Discipline

- Work only on the current stage or the current confirmed fix.
- Do not jump ahead.
- Do not “improve nearby code” unless that is required by the current task.
- Do not pull future architecture into current implementation unless the current stage explicitly requires a hook.
- Keep stage-specific behavior in project docs and stage prompts, not in this file.
- If unsure whether something is inside scope, assume it is out of scope.

## Simplicity Rule

Choose the simplest implementation that:
- fully solves the confirmed task;
- preserves agreed architecture boundaries;
- is explicit in ownership and behavior;
- is easy to verify;
- is easy to change later;
- is easy to roll back if needed;
- does not add a new layer, abstraction, helper, or service unless the current stage clearly requires it.

Do not simplify by cutting functionality. Do not complicate by adding future-proof abstractions without approval.

## Skills and MCP Usage Rule

Skills, MCP tools, and helper systems may be used for planning, research, option comparison, debugging, and failure investigation.

During implementation they are strictly constrained:
- they must not expand scope;
- they must not change the approved plan;
- they must not introduce new architecture;
- they must not add abstractions, layers, or helpers unless the current stage clearly requires them;
- they must not increase code size without clear implementation need;
- they must only help implement the already approved solution.

If their output conflicts with confirmed user instructions, the current stage prompt, project docs, or this file, their output loses.

## Testing Policy

Do not spam tests.

- For bugs, regressions, or business logic, add or update a relevant test.
- For scaffolding, wiring, config, stubs, or phase hooks, use the smallest useful verification: import check, smoke check, contract check, or a targeted test if needed.
- Do not write tests for every micro-change.
- Do not run heavy test suites without a clear reason.
- By default, run only the narrow relevant test set.
- Run full `py -m pytest tests -q` before handoff or gate completion.

## End-of-Stage Self-Check

Before finishing a stage or a meaningful block, report briefly:
1. what remains in scope;
2. what was intentionally left as a stub;
3. what still needs confirmation;
4. what risks remain, if any.

## Final Rule

Write code that is simple, reliable, explicit, easy to verify, easy to clean up, and easy to grow.

If choosing between “clever and bigger” and “clear and durable”, choose the second one.

## Project-Specific Rules: Bot Chassis

- This repository is Bot Chassis: the universal carrier frame for client bots (`tg_psy_tests`, `tg_chat_listener`, etc.).
- Maintain strict multi-tenant data and state isolation by `bot_id`.
- Maintain `.agents/TASK_TODO.md` as the single live queue and `.agents/PROJECT_LOG.md` as the chronological evidence log. Do not create `project_log.md` at repository root.
