# Changelog

All notable changes to pairmux-skills are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-10

### Added

- The skill teaches `wait --done`: subscribing to a terminal another agent (or a human) is driving,
  which blocks until its command finishes and reports the `exit_code`. Any number of agents can
  hold one at once.
- The M suite: a multi-task performance benchmark measuring whether pairmux actually helps an
  agent, not just whether it is used correctly. `run.py --terminal-harness {pmx-cli,rawtmux,shell}`
  runs the same byte-identical task under the full ACI, a raw-tmux baseline with a parity
  cheat-sheet (`evals/harness/TERMINAL-HOWTO.md`), or the agent's bare shell tool — baselines hide
  pairmux behind a command-not-found stub. Episodes score fractionally from harness-agnostic
  subgoal ledgers (`score` and `subgoals` in results/summary). Pilot scenarios: M01 (triage board:
  server readiness + test suite + log needle, concurrently), M03 (credential checkpoint with a
  scripted human bot answering at whatever live terminal the agent offers via `handoff.json`),
  M07 (long non-interactive build — the honest control). Reference `golden.sh` solutions and
  `evals/test-scenarios.sh` validate fixtures/checks at zero model cost, and `evals/metrics.py`
  extracts wall time, tool calls, token usage, and anti-pattern counts from all three agents'
  transcripts into `metrics.jsonl`/`metrics.md`.

### Changed

- The handoff loop no longer teaches that `wait --human` ends only on a note. It also ends when the
  *human* is finished — the prompt is answered and the terminal is visibly moving again (`running`,
  with `wait --done` offered for following the command the rest of the way), or the command
  finishes outright (`done` + `exit_code`) — and returns no `output` in those cases, because the
  span it would quote is the span the human typed into. A note is now documented as how the human
  says *what* they did, not as the precondition for the agent to resume.
- A `timeout` is documented as "the human has not come yet", with the instruction to run the `next`
  hint — the same wait at a longer deadline — rather than act alone or change strategy.


- The skill now leads with what an exec-style shell tool cannot do at all — driving interactive
  programs in a real PTY, persistent shell state, and live human handoff — and demotes slow
  non-interactive commands to "use pairmux when they share that live terminal". The when-to-use
  boundary states plainly that a harness's own background execution often serves plain long
  builds/tests just as well.
- `run`'s documented contract is one quoted command argument (matching the MCP tool); the variadic
  form is now an `E_BAD_ARGS` with a corrected-quoting hint.
- The never-guess-secrets rule covers the broadened secret classes (PIN, OTP/MFA/verification
  codes, API keys, localized sudo prompts), states that recognition is best-effort and
  English-biased, teaches the quiet-`running`-on-a-credential-command handoff heuristic, and
  documents the `PAIRMUX_SECRET_PROMPT_RE` extension point.
- New `pairmux prune` coverage: cheat-sheet row, command reference, and a troubleshooting recipe
  for reclaiming huge journals (rotate with kill+new, then prune).

### Added

- Repeatable cross-agent eval runner (`evals/run.py`) for OpenCode, Claude Code, and Codex with range
  selection, repeats, model/timeout/output controls, dry runs, Codex sandbox selection, per-episode
  process-group timeouts, collision-free copied workspaces/socket/state, injection-safe shell PATH
  guards, a runner-owned pairmux execution broker with an in-memory lifecycle ledger, canonical
  project-local skill injection/hashing,
  explicit binary selection/hashing, interrupted-call proof for S05 expected-handoff outcomes, JSONL
  results, JSON/Markdown summaries, and model-free mock-agent tests.
- Canonical `pairmux` Agent Skill (`skills/pairmux/`): a ≤180-line `SKILL.md` (when to use pairmux vs a
  one-shot shell command, the golden loop, the iron rules, an envelope quick-read, and copy-paste
  examples with real `pairmux.v1` JSON), plus four progressive-disclosure references —
  `commands.md` (every command/flag and the full envelope schema), `interactive.md` (REPLs, pagers,
  `[y/N]`, the never-guess-secrets rule), `collaboration.md` (`attach`/`watch`/`note` and the human
  handoff loop), and `troubleshooting.md` (`E_BUSY`, dead terminals, `wait --pattern`/`--idle`
  gotchas, huge journals, sentinel mode).
- `install-map.md`: per-agent skills directories for Claude Code, Codex CLI, Gemini CLI, Cursor,
  OpenCode, GitHub Copilot CLI, Windsurf, Kiro, Amp, and the universal `~/.agents/skills/` alias (each
  marked verified or best-known with its source), install instructions for `pairmux skill install` /
  `npx skills add` / manual copy, and an AGENTS.md fallback for agents without native skills support.
- Eval suite `evals/` with scenarios S01–S10, each a `setup.sh` (isolated `PAIRMUX_SOCKET`/
  `PAIRMUX_STATE_DIR` under the scenario), a natural-language `TASK.md` (never naming a pairmux
  subcommand), and a `check.sh` that asserts outcomes via `pairmux --json`/journal files and greps the
  transcript for anti-patterns like `sleep`. Covers the basic loop, slow commands, needle-in-a-huge-log,
  `[y/N]` confirmations, password handoff, Python REPL, pager escape, background server + curl,
  Ctrl-C recovery, and note relay. Includes a shared `lib.sh`, `evals/README.md` (OpenCode, Claude
  Code, and Codex runners plus scoring), and `evals/RESULTS.md`.
- Repo scaffolding: `README.md`, `ChangeLog.md`, MIT `LICENSE`, and `.gitignore` (ignores scenario
  runtime dirs; keeps `RESULTS.md` tracked). All shell scripts are shellcheck-clean.

### Changed

- Eval checks resolve journals and indexes through both the legacy state layout and endpoint-identity
  `.sockets/<sha256(canonical-tmux-endpoint)>/` layout. Issued-content filtering understands OpenCode,
  Claude, and Codex JSON without treating aggregated tool output as agent-issued content.
- S05 accepts a human handoff only when the exact effective `wait --human` call remains blocked and
  is interrupted by the episode harness; a completed short wait cannot pass through transcript fallback.
- Skill guidance now treats `next` as contextual ordered hints, documents requested-condition `wait`
  behavior, and covers Bash/zsh hooks, Fish 4+ native OSC 133, Fish-safe sentinel fallback, and doctor
  completion tiers without conflating tiers with envelope modes.

[Unreleased]: https://github.com/treeleaves30760/pairmux-skills/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/treeleaves30760/pairmux-skills/releases/tag/v0.1.0
