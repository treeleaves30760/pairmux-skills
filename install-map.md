# install-map: where the pairmux skill goes, per agent

There is **one canonical skill** — [`skills/pairmux/`](skills/pairmux/) (a `SKILL.md` plus
`references/`). Installing it into any SKILL.md-capable agent means copying that folder to the agent's
skills directory as `.../skills/pairmux/`. No per-agent rewrite; the same folder works everywhere.

```
<agent skills dir>/pairmux/
  SKILL.md
  references/{commands,interactive,collaboration,troubleshooting}.md
```

## Verified paths (as of 2026-07)

Legend: **✓ verified** = confirmed on this machine or in the agent's own current docs; **~ best-known**
= from current third-party/community docs, confirm on your version.

| agent | user / global path | project path | status | source |
|-------|--------------------|--------------|--------|--------|
| **Claude Code** | `~/.claude/skills/pairmux/` | `.claude/skills/pairmux/` | ✓ verified (this machine: `~/.claude/skills/` exists and loads skills) | authoritative for this repo |
| **Codex CLI** | `~/.agents/skills/pairmux/` | `.agents/skills/pairmux/` | ✓ verified (Codex 0.144.6 local discovery probe + docs) | [developers.openai.com/codex/skills](https://developers.openai.com/codex/skills) |
| **Gemini CLI** | `~/.gemini/skills/pairmux/` (alias `~/.agents/skills/pairmux/`) | `.gemini/skills/pairmux/` (alias `.agents/skills/`) | ✓ verified (docs) | [github.com/google-gemini/gemini-cli · docs/cli/skills.md](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/skills.md) |
| **OpenCode** | `~/.config/opencode/skills/pairmux/` (also reads `~/.claude/skills/`, `~/.agents/skills/`) | `.opencode/skills/pairmux/` | ✓ verified (docs) | [opencode.ai/docs/skills](https://opencode.ai/docs/skills/) |
| **Cursor** | `~/.cursor/skills/pairmux/` (~ best-known; some builds are project-only) | `.cursor/skills/pairmux/` | ✓ verified project path (docs) | [cursor.com/docs/skills](https://cursor.com/docs/skills) |
| **GitHub Copilot CLI** | `~/.copilot/skills/pairmux/` (also reads `~/.agents/skills/`) | `.github/skills/pairmux/` | ✓ verified (docs) | [docs.github.com · Adding agent skills](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills) |
| **Windsurf Cascade** | `~/.codeium/windsurf/skills/pairmux/` (also reads `~/.agents/skills/`) | `.windsurf/skills/pairmux/` | ✓ verified (docs) | [docs.windsurf.com · Cascade Skills](https://docs.windsurf.com/windsurf/cascade/skills) |
| **Kiro** | `~/.kiro/skills/pairmux/` | `.kiro/skills/pairmux/` | ✓ verified (docs) | [kiro.dev · Agent Skills](https://kiro.dev/docs/skills/) |
| **Amp** | `~/.config/amp/skills/pairmux/` (also reads `~/.agents/skills/`) | `.agents/skills/pairmux/` | ✓ verified (docs) | [ampcode.com · Owner's Manual](https://ampcode.com/manual#agent-skills) |
| **Universal alias** | `~/.agents/skills/pairmux/` | `.agents/skills/pairmux/` | ✓ read by Gemini, OpenCode, Copilot, Windsurf, and Amp | multiple (above) |
| **Anything else** | — | — | AGENTS.md fallback (below) | — |

Notes:
- The `~/.agents/skills/` (and project `.agents/skills/`) location is Codex's canonical path and a
  **cross-agent alias** honored by several other agents. The `agents` target is therefore compatible
  with Codex; do not depend on the legacy `.codex/skills/` path.
- Skill discovery is one directory deep: an agent finds `<dir>/pairmux/SKILL.md`, not a bare
  `<dir>/SKILL.md`. Keep the `pairmux/` folder.
- The skill `name:` frontmatter is `pairmux`, matching the folder name (required by OpenCode/Cursor).

## Install options

### Option A — `pairmux skill install` (ships with the CLI)

The pairmux binary embeds a synced copy of this skill and installs it into the right directory for you:

```bash
pairmux skill install --target claude-code          # one agent
pairmux skill install --target copilot              # Copilot CLI / agent mode
pairmux skill install --target windsurf             # Windsurf Cascade
pairmux skill install --target kiro                  # Kiro IDE / CLI
pairmux skill install --target amp                   # Amp
pairmux skill install --target agents                # universal ~/.agents/skills alias
pairmux skill install --target all                  # every agent it can find
pairmux skill install --target codex --dry-run      # print the paths it would write, do nothing
```
Valid targets are `claude-code`, `codex`, `gemini`, `cursor`, `opencode`, `copilot`, `windsurf`,
`kiro`, `amp`, `agents`, and `all`. `cursor` installs project-relative to `.cursor/skills/pairmux/`;
the other named targets above install to their user/global paths in the table.
`all` installs only where the agent's configuration directory already exists, and reports skipped
targets. The embedded copy is synced from this repo's `skills/pairmux/` at release time.

### Option B — `npx skills add` (community installer, Vercel Labs)

`npx skills` is a cross-agent skill installer that auto-detects the agents you have installed:

```bash
npx skills add treeleaves30760/pairmux-skills       # project scope, pick agents interactively
npx skills add treeleaves30760/pairmux-skills -g     # global (user) scope
```
It resolves the repo, finds `skills/pairmux/`, and copies it into each selected agent's directory
(`~/.claude/skills/`, `~/.agents/skills/`, `~/.cursor/skills/`,
`~/.config/opencode/skills/`, …). Subcommands: `add`, `find`, `list`, `remove`, `update`.
Source: [github.com/vercel-labs/skills](https://github.com/vercel-labs/skills).

### Option C — manual copy (works for every agent)

```bash
# pick your agent's directory from the table above, e.g. Claude Code:
mkdir -p ~/.claude/skills
cp -R skills/pairmux ~/.claude/skills/pairmux
# Gemini / OpenCode / any agent that reads the universal alias:
mkdir -p ~/.agents/skills && cp -R skills/pairmux ~/.agents/skills/pairmux
```

## Fallback: inject into AGENTS.md (no native skills support)

For an agent with no skills directory, paste this ~15-line pointer block into the project's `AGENTS.md`
(or `CLAUDE.md`/`.cursor/rules/`). It gives the agent the golden loop and the iron rules inline, and
points at the full skill for details.

```markdown
## Using pairmux (terminal control)

When a shell command is **slow** (builds, tests, installs), **interactive** (a REPL, a TUI, a pager, a
[y/N] or password prompt), **long-lived** (a dev server, watch, tail -f), or a **human may need to take
over**, drive it with `pairmux` instead of the raw shell. For one-shot short commands, use the shell.

- Golden loop: `pairmux new --name X` → `pairmux run X "<cmd>" --timeout 30s` → read `status`:
  `done` (read output+exit_code) · `running` (`pairmux wait X --idle 800`, never `sleep`) ·
  `awaiting-input` (`pairmux send X --text y --enter`).
- Truncated output → `pairmux log X --grep "..."` (read the journal; don't re-run).
- **Never** `sleep` to guess timing. **Never** type or guess a secret — on a password prompt run
  `pairmux wait X --human --notify` to hand off to a human.
- Add `--json` for a machine-readable envelope. Read optional `next` hints in order: obey safety/prose,
  replace placeholders, and run the first applicable command; never execute hint text literally.
  Read and obey human `notes`.
- Full reference: the `pairmux` skill (SKILL.md + references/) or run `pairmux help`.
```
