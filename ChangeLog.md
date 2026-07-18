# Changelog

All notable changes to pairmux-skills are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Canonical `pairmux` Agent Skill (`skills/pairmux/`): a ≤180-line `SKILL.md` (when to use pairmux vs a
  one-shot shell command, the golden loop, the iron rules, an envelope quick-read, and copy-paste
  examples with real `pairmux.v1` JSON), plus four progressive-disclosure references —
  `commands.md` (every command/flag and the full envelope schema), `interactive.md` (REPLs, pagers,
  `[y/N]`, the never-guess-secrets rule), `collaboration.md` (`attach`/`watch`/`note` and the human
  handoff loop), and `troubleshooting.md` (`E_BUSY`, dead terminals, `wait --pattern`/`--idle`
  gotchas, huge journals, sentinel mode).
- `install-map.md`: per-agent skills directories for Claude Code, Codex CLI, Gemini CLI, Cursor,
  OpenCode, and the universal `~/.agents/skills/` alias (each marked verified or best-known with its
  source), install instructions for `pairmux skill install` / `npx skills add` / manual copy, and a
  ~15-line AGENTS.md fallback template for agents without native skills support.
- Eval suite `evals/` with scenarios S01–S10, each a `setup.sh` (isolated `PAIRMUX_SOCKET`/
  `PAIRMUX_STATE_DIR` under the scenario), a natural-language `TASK.md` (never naming a pairmux
  subcommand), and a `check.sh` that asserts outcomes via `pairmux --json`/journal files and greps the
  transcript for anti-patterns like `sleep`. Covers the basic loop, slow commands, needle-in-a-huge-log,
  `[y/N]` confirmations, password handoff, Python REPL, pager escape, background server + curl,
  Ctrl-C recovery, and note relay. Includes a shared `lib.sh`, `evals/README.md` (headless Claude Code
  and Codex runners, scoring) and `evals/RESULTS.md`.
- Repo scaffolding: `README.md`, `ChangeLog.md`, MIT `LICENSE`, and `.gitignore` (ignores scenario
  runtime dirs; keeps `RESULTS.md` tracked). All shell scripts are shellcheck-clean.

[Unreleased]: https://github.com/treeleaves30760/pairmux-skills/commits/main
