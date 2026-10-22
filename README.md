# pairmux-skills

The canonical [Agent Skill](https://github.com/vercel-labs/skills) that teaches AI agents to drive
[**pairmux**](https://github.com/treeleaves30760/pairmux) — reliable terminals on tmux or its built-in
PTY/ConPTY backend — plus an install map for SKILL.md-capable agents and an eval suite (S01–S10).

`SKILL.md` is a cross-agent open standard, so **one** skill folder works in Claude Code, Codex CLI,
Gemini CLI, Cursor, OpenCode, GitHub Copilot, Windsurf, Kiro, Amp, and others. This repo is the source
of truth; the pairmux CLI embeds a synced copy for `pairmux skill install`.

```
pairmux-skills/
  skills/pairmux/
    SKILL.md              # concise workflow, terminal-kind choice, golden loop and safety rules
    references/
      commands.md         # every command, every flag, the full pairmux.v1 envelope schema
      interactive.md      # REPLs, pagers, [y/N], the never-guess-secrets rule
      collaboration.md    # attach / watch / note and the human handoff loop
      troubleshooting.md  # E_BUSY, dead terminals, wait gotchas, sentinel mode
  install-map.md          # per-agent skills paths (verified) + AGENTS.md fallback template
  evals/
    scenarios/S01..S10/   # setup.sh + TASK.md + check.sh each
    README.md  RESULTS.md  lib.sh
  ChangeLog.md  LICENSE
```

## What the skill teaches

- **The golden loop:** submit the command, estimate time to its first meaningful signal, then use
  a bounded `run`/`wait` (generally 30s, shorter for fast tasks). Inspect returned output/status or a
  safe `peek`, and verify healthy startup before unrelated work or a long wait. No extra wait when
  the initial reply is enough; unknown/silent is not healthy, and timeout is not failure. Shells use
  `wait --done --idle 800`; known REPLs/TUIs/servers use `new --cmd`, then `send`/`peek` and
  idle/future-pattern/note waits, not shell-only `run`/`--done`.
- **The iron rules:** prefer event-aware bounded observation over sleep-and-guess; a brief sleep is
  only a fallback when no suitable blocking observation is available, not repeated blind polling.
  One command per terminal; answer a safe prompt once; never type or guess a secret. Credential
  handoffs use `wait --human --notify` at ≥300s, are excluded from the 30s startup rule, and never
  justify reading secret spans. Long subscriptions (e.g. 600s) suit verified startup or intentional
  passive listening. Prefer the journal over re-running; read and obey human `notes` within authorization.
- **When *not* to use pairmux:** one-shot short commands belong in your normal shell tool.

## Install the skill

### With `pairmux skill install` (ships with the CLI)

The `-t` alias, four additional targets, and bundle provenance report require **pairmux v1.1.0+**.
Terminal workflows remain compatible with v1.0.x; manually copy this skill for an older compatible CLI.

```bash
pairmux skill install --target claude-code
pairmux skill install -t cline                 # -t aliases --target
# targets: claude-code codex gemini cursor opencode copilot windsurf kiro amp agents
#          cline roo-code kilo-code droid all
pairmux skill install --target all --dry-run    # show the paths it would write
```

The executable embeds the **five canonical files at build time** (SKILL.md + four references).
Installation is **offline**: it uses that executable's bundle, not a network source or remote latest.
The report shows the embedded CLI version and bundle SHA-256. Each run replaces managed same-name
files (including local edits) and preserves extra files; back up edits first.

For latest bundled content, obtain a **fresh executable** through your supported installation/update
path, then rerun `skill install` and restart/reload the agent. `--target all` skips missing agent roots;
`cursor` is relative to your current working directory. Codex installs to `.agents/skills/`, not the
legacy `.codex/skills/` tree. See [`install-map.md`](install-map.md) for refresh and source-build limits.

### With `npx skills` (Vercel Labs' cross-agent installer)

```bash
npx skills add treeleaves30760/pairmux-skills        # project scope, auto-detects your agents
npx skills add treeleaves30760/pairmux-skills -g      # global (user) scope
```

### Manually

```bash
# Claude Code (authoritative path); adapt from install-map.md for other agents:
mkdir -p ~/.claude/skills && cp -R skills/pairmux ~/.claude/skills/pairmux
```

See [`install-map.md`](install-map.md) for every verified agent directory and the universal
`~/.agents/skills/` alias, plus the AGENTS.md fallback for agents with no native skills support.
See [`RELEASING.md`](RELEASING.md) for the repository release checklist and the required sync into
the pairmux CLI repository.

## Evals

Ten scenario cards check that an agent uses pairmux correctly — the basic loop, slow commands without
`sleep`, finding one error in a huge log, confirmations, the never-guess-secrets rule, REPLs, pagers,
multi-terminal server work, Ctrl-C recovery, and note relay. Each has a `setup.sh`, a natural-language
`TASK.md` (which never names a pairmux subcommand), and a `check.sh` that asserts the outcome and greps
the transcript for anti-patterns. See [`evals/README.md`](evals/README.md) for the OpenCode, Claude
Code, and Codex runners and scoring, and [`evals/RESULTS.md`](evals/RESULTS.md) for recorded runs.

## Requirements

**Runtime:** the `pairmux` binary (persistent `uv tool install pairmux` needs Python 3.9+). From v1.0,
macOS/Linux auto uses available tmux 3.2+ or built-in PTYs; native Windows 10 1809+ uses built-in
ConPTY. tmux, bash and WSL are not universal runtime prerequisites; use your selected shell's syntax.
An existing built-in endpoint remains selected unless tmux also runs there.

**Repository eval fixtures:** POSIX shell/bash, `tmux >= 3.2`, `python3`, `curl` and a compatible
`pairmux` binary for the real-terminal scenarios. These fixture requirements are separate from runtime
support; Windows users need a suitable POSIX environment (such as WSL) for those scenarios. Model-free
Python unit tests do not require a paid model or all real-terminal prerequisites.

## License

MIT — see [LICENSE](LICENSE).
