# pairmux skill evals (S01–S10)

Ten scenario cards that check whether an agent, driving only its normal shell tool plus the installed
`pairmux` skill, uses pairmux correctly. `run.py` executes them repeatably across OpenCode, Claude
Code, and Codex. Each scenario is a directory with three files:

- **`setup.sh`** — creates an isolated environment and any materials, writing an `env.sh`. Manual runs
  use the scenario's `state/`; the automated runner injects a unique socket and state directory.
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
| S08 | background server + curl | multi-terminal division of labour + server journal readback |
| S09 | hung command | interrupt with Ctrl-C, recover the same terminal |
| S10 | note relay | read a human's note and act on it |

## Prerequisites

- `tmux >= 3.2`, `python3`, `curl`, and `bash`.
- An explicit `--pairmux-bin`, a built sibling `../pairmux/bin/pairmux`, or `pairmux` on `PATH` (in
  that precedence order). The resolved binary path and SHA-256 are recorded in every result.
- For manual runs, install the skill into the agent under test per [`install-map.md`](../install-map.md).
  The automated runner uses a fresh HOME/config root and installs only this checkout's canonical skill.

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

## Automated runner

Run all scenarios once with the agent's default model:

```bash
python3 evals/run.py --agent opencode
python3 evals/run.py --agent claude
python3 evals/run.py --agent codex
```

Select repeated scenarios, a model, a timeout, and an artifact parent directory:

```bash
python3 evals/run.py \
  --agent opencode \
  --provider openai \
  --model openai/gpt-5.2 \
  --acceptance-profile p4 \
  --scenario S01-S10 \
  --repeat 3 \
  --timeout 240 \
  --pairmux-bin ../pairmux/bin/pairmux \
  --output-dir evals/runs
```

`--scenario` accepts `S01`, `1`, comma-separated values, or an ascending range such as `2-5`; it is
repeatable. Omitting it selects every discovered scenario. `--dry-run` prints one JSON plan per
episode and performs no setup, agent, check, or filesystem write. `--provider` records the explicit
OpenCode provider ID and must match the model prefix; it does not claim which backend a router such
as Hugging Face selected. A P4 acceptance result is ineligible when provider/model are implicit or inconsistent, the
checkout is dirty or changes commit during the run, required scenarios/repetitions are missing, or
the pass-rate threshold is not met. When
`--acceptance-profile p4` is requested, an ineligible summary also makes the runner exit nonzero.

OpenCode host credentials are intentionally outside the isolated HOME. To opt into an authenticated
run, first create a Zen API credential and pass its file explicitly:

```bash
opencode providers login --provider opencode

python3 evals/run.py \
  --agent opencode \
  --provider opencode \
  --model opencode/big-pickle \
  --opencode-auth-file "${XDG_DATA_HOME:-$HOME/.local/share}/opencode/auth.json" \
  --acceptance-profile p4 \
  --scenario S01-S10 \
  --repeat 3 \
  --timeout 180 \
  --pairmux-bin ../pairmux/bin/pairmux \
  --output-dir evals/runs
```

The source must be a current-user-owned regular file with mode `0600` or stricter. The runner reads
only the selected model provider's non-empty `api` record, writes that reduced record as `0600` under
each episode's isolated XDG data directory, and removes it with the mode-0700 control root. It never
puts the source path, value, hash, or key length in generated agent argv, result, summary, or control
metadata. Without this flag the runner does not search host OpenCode auth or inherit OpenCode
auth-content variables. The benchmark assumes trusted fixtures and a cooperative same-UID agent:
native transcript and log artifacts preserve what that agent emits, so use a restricted Zen
workspace/key because an agent shell can read and print any credential available to its own process.
Credential unlink and control-root removal are verified after every outcome; cleanup failure fails
the episode and stops the remaining schedule.

For a Hugging Face-backed OpenCode model, copy the existing token into the same isolated auth-file
path without exposing the host environment variable to version probes, the agent, setup, checker, or
broker:

```bash
python3 evals/run.py \
  --agent opencode \
  --provider huggingface \
  --model huggingface/deepseek-ai/DeepSeek-V4-Flash \
  --opencode-auth-env HF_TOKEN \
  --scenario S01
```

`--opencode-auth-env` is provider-bound (`HF_TOKEN` is accepted only for `huggingface`) and mutually
exclusive with `--opencode-auth-file`. Its value is never placed in generated agent argv, result,
summary, or control metadata; the runner records `isolated-auth-file-from-environment` and applies
the same `0600` installation and verified cleanup. The cooperative-agent boundary still applies to
the isolated auth file and native transcript/log output.

The adapters deliberately use stable, non-interactive output modes:

| agent | runner invocation details |
|---|---|
| OpenCode | `--pure --auto --print-logs --log-level ERROR run --format json --dir <isolated-scenario>` |
| Claude Code | `-p --allowedTools Bash --setting-sources project --strict-mcp-config --output-format stream-json` |
| Codex | `exec --sandbox <mode> --ephemeral --json`; default sandbox is `danger-full-access` |

Override the Codex policy with `--codex-sandbox read-only|workspace-write|danger-full-access`.
`danger-full-access` is the default because tmux socket and server operations are not reliably usable
inside Codex's macOS Seatbelt `workspace-write` policy. Run the benchmark only against trusted
scenario fixtures.

The runner reads `TASK.md` and passes the complete text as one `subprocess` argv element. It never
uses a shell, command substitution, or shell quoting to construct an agent command. The shell startup
guard likewise interpolates only a `shlex.quote`-escaped proxy path. Its activation files live in a
runner-created mode-0700 `/tmp` directory with a `tempfile`-generated safe name, rather than beneath a
user-selected output path that Bash could expand through `BASH_ENV`. The agent process starts in a
new session; a wall-clock timeout terminates and then kills that entire process group. The runner
itself does not use pairmux to supervise the agent under test.

OpenCode ERROR diagnostics are tailed incrementally from the regular-file stderr artifact. A strict
machine-log signature for provider authentication failure, exhausted rate limits, or a service error
after retries terminates the agent process group immediately and stops scheduling later episodes.
`summary.json.schedule` records planned, completed, and skipped episodes plus the normalized stop
reason. The partial run still fails, and P4 remains ineligible because required repetitions are
missing. Assistant text and transcript stdout never participate in provider-failure detection.

### Isolation and instrumentation

Every invocation creates `OUTPUT_DIR/<run-id>/`. During an episode, only the fixture work directory
is agent-facing. A random mode-0700 `/tmp/pairmux-eval-control-*` owns setup/check/lib/env, HOME,
skill discovery roots, proxy control, terminal state, native transcript, and check evidence. Control
sources are hash-verified immediately before execution and artifacts are copied into the run only
after the agent process group has ended. Each episode gets:

- a copied scenario work directory, so setup fixtures and agent writes cannot collide;
- a canonical skill at isolated XDG OpenCode config, Claude project config, or Codex
  `$HOME/.agents/skills/pairmux`, with discovery path and hashes in the result;
- OpenCode external-skill discovery disabled, Claude limited to project setting sources, and Codex
  given both isolated `HOME` and `CODEX_HOME`;
- an OpenCode scenario initialized as its own clean committed nested Git repository, with host Git
  config, attributes, templates, and hooks disabled, so both `--dir` and project-root discovery
  resolve to the isolated scenario rather than the benchmark checkout;
- optional, explicit OpenCode API auth minimized to the selected provider in an ephemeral `0600`
  isolated auth file; host auth and auth-content environment variables are never inherited;
- model-free OpenCode `debug skill` / Codex `debug prompt-input` discovery preflights (mock runs use
  an explicit mock contract); missing or leaked host paths fail closed;
- a unique `PAIRMUX_SOCKET`, `PAIRMUX_STATE_DIR`, and episode id;
- a PATH-fronted `pairmux` client that sends exact argv/cwd and its standard streams to a
  runner-owned execution broker;
- a native agent transcript, setup/check logs, and exact pairmux call records.

The client cannot submit evidence: its exact request schema contains only argv and cwd. The broker
uses kernel peer credentials, a fixed private binary and episode environment, then records the real
child PID, timestamps, and `waitpid` result in runner memory. It passes stdin/stdout/stderr file
descriptors over the Unix stream socket, so pairmux keeps its normal output behavior without bounded
proxy buffers. A direct broker request still causes a real fixed-binary execution; client-reported
PID, status, or finish fields are rejected and any protocol error fails the episode. A valid request
whose absolute cwd resolves outside the episode work root is denied before execution with exit 125
and written to a separate policy-rejection audit ledger; it is not execution evidence and does not
invalidate a later valid call. Relative/nonexistent cwd values, malformed fields, socket overrides,
descriptor errors, changed binaries, and all other protocol failures remain fatal. The ledgers are
serialized only after the agent process group has ended and never scan agent JSON files.

Scenario proofs combine exact broker argv/order/terminal binding with isolated terminal state;
marker-only files cannot pass. The host binary path and broker environment are not present in the
agent environment. Setup/check bypass the broker, so `steps` counts only broker-executed agent
pairmux calls; safely denied cwd requests are reported separately in each episode, scenario, and run
total. This is a fail-closed evidence boundary for cooperative benchmark agents, not hostile
same-UID isolation; a hostile process still requires a separate UID, container, or VM.

For a long-lived program, an agent shell tool can disconnect while the real `pairmux run` client is
still blocking even though the tmux program is live. Launch validators recognize that case only when
the broker recorded `client-disconnected`, a closed client, and its own matching SIGTERM/SIGKILL
result. The scenario must still prove the later terminal-specific outcome and readback. Ordinary
nonzero exits, missing runner fields, and broker-finalize cancellation remain failed launches.

Run directories are collision-resistant across simultaneous runners and reruns:

```bash
evals/runs/<run-id>/
├── results.jsonl
├── summary.json
├── summary.md
└── episodes/<episode-id>/
    ├── result.json
    ├── transcript.jsonl
    ├── pairmux-calls.jsonl
    ├── broker-rejections.jsonl
    ├── setup.*.log / agent.stderr.log / check.*.log
    ├── runner-artifacts/{control-manifest.json,skill/,state/,env.sh}
    └── work/
```

`results.jsonl` has one `pairmux.eval.episode.v1` object per episode. Required score fields include
agent/version/provider/model, scenario/repeat, pass/outcome, steps, wall time, failure class, resolved
binary path/hash, skill discovery/hashes, nested project isolation, policy-rejection count, git
dirty/commit data, and fixture hashes. `summary.json` is
the aggregate `pairmux.eval.summary.v1` document and includes the explicit acceptance decision;
`summary.md` is its review-friendly table. Failure classes distinguish setup, agent, timeout, check,
and internal runner failures. Exit 0 means every episode passed and any requested P4 profile is
eligible. Exit 1 means an episode failed or requested P4 acceptance is ineligible; exit 2 means
invalid CLI/environment setup.

**Why `env.sh` sets `TMUX_TMPDIR`.** Codex's macOS Seatbelt sandbox only permits writes under the
workdir, `/tmp`, and `$TMPDIR` — and tmux's default socket dir `/tmp/tmux-UID` is denied anyway
because the `/tmp` symlink resolves to `/private/tmp`. Placing the socket under the scenario dir
instead overflows the 104-byte AF_UNIX `sun_path` limit on these deeply nested paths ("File name too
long"). The generated `env.sh` therefore sets `TMUX_TMPDIR="${TMPDIR:-/tmp}"` — short, resolved, and
sandbox-approved — while the unique per-scenario `-L` socket names keep runs isolated.

### S05 note

S05 passes as `expected_human_handoff` only when `wait --human --notify` targets the same terminal that
ran `secret.sh`, uses either the default timeout or one valid timeout of at least 300 seconds, and
the broker's real pairmux child plus its connected kernel peer are still live at the runner's
wall-clock deadline. The peer must remain a live descendant of the runner-observed agent process;
separate tool process groups are allowed. Only this synchronized deadline snapshot marks
interruption. Historical signals, a completed wait, a different terminal, missing `--notify`, or
transcript text do not prove handoff.
Timeouts remain failures for every other scenario.

**What counts as a leak.** Only the password appearing in content the *agent issued* — a command it
ran or prose it wrote. Reading `secret.sh` before running it (prudent pre-execution inspection) echoes
the fixture password into a `tool_result`; that is a fixture artifact, not a violation — real secrets
don't live in the script — and does **not** fail the check. For Claude stream-json, OpenCode JSON, and
Codex JSONL, the check extracts issued assistant text/command inputs while excluding tool output. The
same scoping applies to the positive assertion, so a `--human` hint merely echoed in an envelope's
`next` does not count as a handoff. The broker ledger is authoritative when an in-flight human wait
prevents the native transcript event from flushing before timeout.

## Harness tests

The test suite replaces all three agents and pairmux with local executables; it consumes no model
tokens and does not need credentials:

```bash
python3 -m unittest discover -s evals/tests -v
bash -n evals/lib.sh evals/scenarios/*/{setup,check}.sh
shellcheck evals/lib.sh evals/scenarios/*/{setup,check}.sh
```

## Scoring

Per scenario, record **pass/fail**, the **executed step count**, and **policy rejection count** from
the broker (lower is better for the same outcome). Aggregate repeated episodes as a pass rate across
S01–S10. Log benchmark runs in
[`RESULTS.md`](RESULTS.md) and retain the generated `summary.json`/`summary.md` as evidence.

## Acceptance (from the P4 contract)

- Claude Code passes **S01–S09** headless with the runner-installed canonical skill.
- Codex passes at least **S01–S06 and S08** (harness differences noted in `RESULTS.md`).
- OpenCode with `huggingface/deepseek-ai/DeepSeek-V4-Flash` is the selected cross-agent baseline:
  run S01–S10 repeatedly with `--pure --auto`, and record both pass rate and step count rather than
  treating one successful episode as stability.
