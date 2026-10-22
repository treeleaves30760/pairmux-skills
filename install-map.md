# install-map: where the pairmux skill goes, per agent

There is **one canonical skill** — [`skills/pairmux/`](skills/pairmux/) (a `SKILL.md` plus
`references/`). Installing it into any SKILL.md-capable agent means copying that folder to the agent's
skills directory as `.../skills/pairmux/`. No per-agent rewrite; the same folder works everywhere.

```
<agent skills dir>/pairmux/
  SKILL.md
  references/{commands,interactive,collaboration,troubleshooting}.md
```

## Verified paths (new targets checked 2026-10-22)

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
| **Cline** | `~/.cline/skills/pairmux/` | `.cline/skills/pairmux/` | ✓ verified (docs) | [docs.cline.bot · Skills](https://docs.cline.bot/customization/skills) |
| **Roo Code** | `~/.roo/skills/pairmux/` | `.roo/skills/pairmux/` | ✓ verified (docs) | [docs.roocode.com · Skills](https://docs.roocode.com/features/skills) |
| **Kilo Code** | `~/.kilo/skills/pairmux/` | `.kilo/skills/pairmux/` | ✓ verified (docs) | [kilo.ai · Skills](https://kilo.ai/docs/customize/skills) |
| **Factory Droid** | `~/.factory/skills/pairmux/` | `.factory/skills/pairmux/` | ✓ verified (docs) | [docs.factory.com · Skills](https://docs.factory.com/cli/configuration/skills) |
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

The examples using `-t`, the `cline`/`roo-code`/`kilo-code`/`droid` targets, and bundle provenance
reports require pairmux **v1.1.0+**. The terminal guidance supports v1.0.x too; use manual copy
below when installing this skill with an older compatible CLI.

The pairmux executable embeds the **five canonical files at build time** (SKILL.md + four references).
`skill install` works **offline**: no network source is consulted and it does not fetch a remote
latest skill. It installs the bytes bundled in the executable you actually invoked. The report
identifies them as `source: embedded in pairmux VERSION; bundle sha256:DIGEST` (bundle SHA-256).

```bash
pairmux skill install --target claude-code          # one agent
pairmux skill install --target copilot              # Copilot CLI / agent mode
pairmux skill install --target windsurf             # Windsurf Cascade
pairmux skill install --target kiro                  # Kiro IDE / CLI
pairmux skill install --target amp                   # Amp
pairmux skill install -t cline                       # Cline
pairmux skill install -t roo-code                    # Roo Code
pairmux skill install -t kilo-code                   # Kilo Code
pairmux skill install -t droid                       # Factory Droid
pairmux skill install --target agents                # universal ~/.agents/skills alias
pairmux skill install -t all                         # every agent it can find
pairmux skill install --target codex --dry-run      # print the paths it would write, do nothing
```
`-t` is an alias for `--target`. Valid targets are `claude-code`, `codex`, `gemini`, `cursor`,
`opencode`, `copilot`, `windsurf`, `kiro`, `amp`, `cline`, `roo-code`, `kilo-code`, `droid`, `agents`,
and `all`. `cursor` installs relative to the **current working directory**
at `.cursor/skills/pairmux/`; the other named targets install to user/global paths in the table.
`all` installs only where the agent's configuration directory already exists, reporting missing roots
as skipped (and shared destinations only once). A named target can create its destination.

Every install **replaces** the managed same-name files, including locally edited copies, and
**preserves** extra files; there is no timestamp/version gate. Back up local edits before refreshing.
The five-file embedded bundle is synced from this repo's `skills/pairmux/` before the executable is
built. The bundle SHA-256 identifies its content independently of CLI version; it is computed over
sorted relative paths plus NUL and each file's raw SHA-256 bytes. It is a provenance identifier, not
a network lookup or remote-freshness guarantee.

#### Refreshing an existing installation

1. To obtain latest bundled content, first obtain a **fresh executable** that embeds it, through the
   installation's supported release/update path and with explicit user authorization. Re-running an
   older executable installs the same older bundle, not the newest GitHub skill.
2. Run that executable's `pairmux skill install --target T --dry-run` to inspect its version, digest
   and paths; then run without `--dry-run` to replace the managed files.
3. Restart/reload the agent so it discovers the refreshed files. `codex` and `agents` write
   `~/.agents/skills/pairmux/`; they do **not** refresh a legacy `~/.codex/skills/pairmux/` tree. Review
   and remove or update a legacy copy separately so stale duplicate content does not linger.

A source reinstall must use CLI source whose embedded skill copy has first been refreshed from the
canonical repo; rebuilding stale source still embeds stale content. A normal source build/reinstall
produces a `dev` executable, and `pairmux update` refuses dev builds under existing verification policy.
A content refresh does not change that policy or turn a dev build into a supported release installation.

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

For an agent with no skills directory, paste this short pointer block into the project's `AGENTS.md`
(or `CLAUDE.md`/`.cursor/rules/`). It gives the agent the golden loop and the iron rules inline, and
points at the full skill for details.

```markdown
## Using pairmux (terminal control)

Use pairmux for **interactive** programs (REPL/TUI/pager/prompts), **persistent live shell state**,
**long-lived** servers/watch tasks, or **human takeover**. Slow commands qualify when they share that
live terminal/state or need a human. Use your normal shell for one-shot short commands; plain long
non-interactive builds/tests often fit your harness's background execution just as well.

- Shell loop: submit `pairmux run X "<cmd>" --timeout 30s` after `pairmux new --name X`, then estimate
  time to first meaningful signal, not total runtime. Initial bounded observation is generally 30s,
  shorter for fast tasks; a bounded `run` counts. Inspect returned output/status or a safe `peek`;
  no redundant wait when it already gives completion or healthy-startup evidence. Verify healthy
  startup before unrelated work or a long wait; unknown/silent is not healthy, timeout is not failure.
  If more evidence is needed, use `pairmux wait X --done --idle 800 --timeout 30s`, then reassess.
  On `done`, read output + exit_code; inspect prompts and answer a safe one once with `send`.
- Prefer event-aware bounded `run`/`wait`. A brief sleep is only a fallback when no suitable blocking
  observation is available, followed by a safe check, not repeated blind polling. Long subscriptions
  (e.g. 600s) suit verified startup or intentional passive listening, not an unchecked launch.
- Known program: `new --cmd "<program>"`, then `send`/`peek`, `wait --idle`, future `--pattern`, or an
  explicit note; `run`/`wait --done` are shell-only, even if the program reports sentinel mode.
- Read already-printed readiness/truncated output via `peek`/`log --grep`; don't re-run or wait for
  a past pattern. Raw-mode inferred awaiting-input is not proof a turn completed or input is safe.
- Never type or guess a secret: `pairmux wait X --human --notify`; keep the 300s default or ≥300s,
  explicitly excluded from the 30s startup rule. Repeat after client interruption/timeout.
  Resumed is not completed; a note is not completion. Never put credentials in notes or automatically
  read a sensitive span, including for startup checks; handoff is not redaction.
- Inside a pane, PAIRMUX_SOCKET is a child endpoint. The creator supplies the owning endpoint for
  `pairmux --socket <owner> note <name> "turn complete"`; do not infer a parent socket.
- Ordinary CLI replies support `--json` envelopes (help stays text; MCP uses JSON-RPC). Read `next`
  in order, obey safety/prose, replace placeholders, choose an applicable command, and read `notes`.
- Full reference: the `pairmux` skill (SKILL.md + references/) or `pairmux help`.
```
