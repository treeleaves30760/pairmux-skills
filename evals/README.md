# pairmux skill evals (S01–S10)

Ten scenario cards that check whether an agent, driving only its normal shell tool plus the installed
`pairmux` skill, uses pairmux correctly. Each scenario is a directory with three files:

- **`setup.sh`** — creates an isolated environment (a unique `PAIRMUX_SOCKET` and `PAIRMUX_STATE_DIR`
  under the scenario's own `state/`) and any materials, writing an `env.sh` for the runner to source.
  Some scenarios pre-create a terminal in a starting state (a stuck pager, a hung command, a note).
- **`TASK.md`** — the natural-language task handed to the agent. It never names a pairmux subcommand;
  choosing `run`/`wait`/`send`/… is the skill's job.
- **`check.sh [transcript]`** — asserts the outcome (via `pairmux --json` and the journal files) and,
  when a transcript path is given, greps it for anti-patterns like `sleep`. Exit 0 = pass.

| # | scenario | what it exercises |
|---|----------|-------------------|
| S01 | instant command | the basic loop, no detours |
| S02 | ~20s fake build | wait for completion, never `sleep`-guess |
| S03 | one FATAL line in 10k | truncation pointer → `log --grep` |
| S04 | `[y/N]` confirmation | `awaiting-input` → answer once |
| S05 | password prompt | hand off to a human, never guess a secret |
| S06 | Python REPL | drive with `send`/`peek`, read back a result |
| S07 | stuck in a pager | recognise the pager, escape with `q` |
| S08 | background server + curl | multi-terminal division of labour + log grep |
| S09 | hung command | interrupt with Ctrl-C, recover the same terminal |
| S10 | note relay | read a human's note and act on it |

## Prerequisites

- `tmux >= 3.2`, `python3`, `curl`, and `bash`.
- The `pairmux` binary on `PATH` **or** a built sibling `../pairmux/bin/pairmux` (the scenarios resolve
  it automatically and prepend it to `PATH` in `env.sh`).
- The skill installed into the agent under test (`pairmux skill install --target <agent>`, or copy
  `skills/pairmux/` per [`install-map.md`](../install-map.md)).

## Running one scenario by hand

```bash
cd evals/scenarios/S01
./setup.sh                 # builds the isolated env + writes env.sh
source ./env.sh            # so THIS shell (and the agent it launches) share the socket/state
# ... let the agent perform TASK.md against pairmux ...
./check.sh                 # outcome-only
./check.sh transcript.txt  # outcome + anti-pattern grep
```

Because `env.sh` exports `PAIRMUX_SOCKET`/`PAIRMUX_STATE_DIR`/`PATH`, the agent process launched from
this shell inherits them and its `pairmux` calls hit the isolated socket. `check.sh` sources the same
`env.sh`. Re-running `setup.sh` wipes the previous run (`tmux -L <sock> kill-server` + fresh `state/`).

## Headless runners

### Claude Code

```bash
cd evals/scenarios/S02
./setup.sh && source ./env.sh
claude -p "$(cat TASK.md)" \
  --allowedTools Bash \
  --max-turns 25 \
  --output-format stream-json --verbose | tee transcript.jsonl
./check.sh transcript.jsonl
```

`--output-format stream-json` records each tool call (including the exact Bash command strings), which
is what `check.sh` greps for anti-patterns. `--allowedTools Bash` is enough — pairmux is a CLI the
agent calls through Bash.

### Codex CLI

```bash
cd evals/scenarios/S02
./setup.sh && source ./env.sh
codex exec --sandbox workspace-write "$(cat TASK.md)" 2>&1 | tee transcript.txt
./check.sh transcript.txt
```

Use `--sandbox workspace-write` so Codex can run commands unattended. Codex's transcript format
differs from Claude's, but both include the shell commands the agent ran, so the same `check.sh`
greps work (plain-text transcripts use whole-file greps — see the S05 note).

**Why `env.sh` sets `TMUX_TMPDIR`.** Codex's macOS Seatbelt sandbox only permits writes under the
workdir, `/tmp`, and `$TMPDIR` — and tmux's default socket dir `/tmp/tmux-UID` is denied anyway
because the `/tmp` symlink resolves to `/private/tmp`. Placing the socket under the scenario dir
instead overflows the 104-byte AF_UNIX `sun_path` limit on these deeply nested paths ("File name too
long"). The generated `env.sh` therefore sets `TMUX_TMPDIR="${TMPDIR:-/tmp}"` — short, resolved, and
sandbox-approved — while the unique per-scenario `-L` socket names keep runs isolated.

### S05 note

S05's correct behaviour is to hand off to a human and block on `wait --human --notify`. With no human,
that call will sit until its `--timeout`, so give the runner a bounded `--max-turns`/time budget; the
check passes as long as no password was submitted and a `wait --human` handoff was issued.

**What counts as a leak.** Only the password appearing in content the *agent issued* — a command it
ran or prose it wrote. Reading `secret.sh` before running it (prudent pre-execution inspection) echoes
the fixture password into a `tool_result`; that is a fixture artifact, not a violation — real secrets
don't live in the script — and does **not** fail the check. For Claude stream-json transcripts the
check extracts exactly the issued content (assistant `tool_use` inputs + text blocks, via `jq`, with a
jq-less line-filter fallback); the same scoping applies to the positive assertion, so a `--human` hint
merely echoed in an envelope's `next` does not count as a handoff. Plain-text transcripts (codex
`exec`) can't be reliably separated into issued vs echoed content, so there the greps cover the whole
file — stricter for codex, by design: avoid `cat`ing `secret.sh` in codex runs.

## Scoring

Per scenario, record **pass/fail** (`check.sh` exit code) and the **step count** (number of pairmux
commands the agent issued — lower is better for the same outcome). Aggregate as a pass rate across
S01–S10. Log every run in [`RESULTS.md`](RESULTS.md) with the machine, date, and model/agent version.

## Acceptance (from the P4 contract)

- Claude Code passes **S01–S09** headless with the skill installed.
- Codex passes at least **S01–S06 and S08** (harness differences noted in `RESULTS.md`).
