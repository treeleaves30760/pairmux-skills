# pairmux-skills

The canonical [Agent Skill](https://github.com/vercel-labs/skills) that teaches AI agents to drive
[**pairmux**](https://github.com/treeleaves30760/pairmux) — reliable terminal primitives on tmux — plus
an install map for every SKILL.md-capable agent and an eval suite (S01–S10).

`SKILL.md` is a cross-agent open standard, so **one** skill folder works in Claude Code, Codex CLI,
Gemini CLI, Cursor, OpenCode, and others. This repo is the source of truth; the pairmux CLI embeds a
synced copy for `pairmux skill install`.

```
pairmux-skills/
  skills/pairmux/
    SKILL.md              # ≤180 lines: when to use, the golden loop, the iron rules
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

- **The golden loop:** `new` → `run` (blocks until done or `--timeout`) → read `status` → `wait`
  (running) / `send` (awaiting-input) / `log` (truncated) → do what the envelope's `next` says.
- **The iron rules:** never sleep-and-guess timing; one command per terminal; answer a prompt once;
  never type or guess a secret (hand off with `wait --human --notify`); prefer reading the journal
  over re-running; `notes` are messages from a human — read and obey them.
- **When *not* to use pairmux:** one-shot short commands belong in your normal shell tool.

## Install the skill

### With `pairmux skill install` (ships with the CLI)

```bash
pairmux skill install --target claude-code      # or: codex | gemini | cursor | opencode | all
pairmux skill install --target all --dry-run    # show the paths it would write
```

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

See [`install-map.md`](install-map.md) for every agent's directory (Claude Code, Codex, Gemini,
Cursor, OpenCode, the universal `~/.agents/skills/` alias) and the AGENTS.md fallback for agents with
no native skills support.

## Evals

Ten scenario cards check that an agent uses pairmux correctly — the basic loop, slow commands without
`sleep`, finding one error in a huge log, confirmations, the never-guess-secrets rule, REPLs, pagers,
multi-terminal server work, Ctrl-C recovery, and note relay. Each has a `setup.sh`, a natural-language
`TASK.md` (which never names a pairmux subcommand), and a `check.sh` that asserts the outcome and greps
the transcript for anti-patterns. See [`evals/README.md`](evals/README.md) for the headless runners
(Claude Code, Codex) and scoring, and [`evals/RESULTS.md`](evals/RESULTS.md) for recorded runs.

## Requirements

`tmux >= 3.2`, `bash`, and the `pairmux` binary (the evals also use `python3` and `curl`). pairmux runs
on macOS and Linux; on Windows use WSL.

## License

MIT — see [LICENSE](LICENSE).
