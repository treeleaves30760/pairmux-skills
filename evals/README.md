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

### Endpoint-only evaluation (explicit opt-in)

Use a dedicated, restricted endpoint credential **only via its environment variable name**.
The examples assume the operator has already exported `PAIRMUX_EVAL_API_KEY` privately and manages
an SSH tunnel exposing `http://127.0.0.1:8080/v1`. Do not put a key in command arguments, URLs,
checked-in configuration, or shell history. The approved endpoint serves `qwen3.8-27b` with a
262144-token context window; these commands do not configure the tunnel or any host agent settings.

```bash
python3 evals/run.py --agent opencode --provider qwen --model qwen/qwen3.8-27b \
  --endpoint-base-url http://127.0.0.1:8080/v1 --endpoint-key-env PAIRMUX_EVAL_API_KEY \
  --endpoint-context 262144 --endpoint-max-output 4096 --scenario S01 --timeout 300 \
  --max-capability-failures 2

python3 evals/run.py --agent codex --provider qwen --model qwen3.8-27b \
  --endpoint-base-url http://127.0.0.1:8080/v1 --endpoint-key-env PAIRMUX_EVAL_API_KEY \
  --endpoint-effort medium --scenario S01 --timeout 300 --max-capability-failures 2

python3 evals/run.py --agent claude --provider qwen --model qwen3.8-27b \
  --endpoint-base-url http://127.0.0.1:8080/v1 --endpoint-key-env PAIRMUX_EVAL_API_KEY \
  --discovery-timeout 300 --endpoint-max-turns 32 --scenario S01 --timeout 300 \
  --max-capability-failures 2
```

Add `--dry-run` to inspect a plan with **zero writes, credential reads, version probes, or API calls**;
the named credential need not exist for a dry run. Execution requires a nonempty, unpadded key.
Endpoint mode requires explicit `--provider`, `--model`, `--endpoint-base-url`, and
`--endpoint-key-env`; a custom provider ID such as `qwen` cannot name a built-in paid provider.
OpenCode's model prefix must match that ID; Claude and Codex use the bare endpoint model ID.
Paid Claude aliases/models, ambiguous URLs, userinfo, queries, fragments, and paths other than root
or `/v1` are rejected. HTTP is loopback-only; remote URLs require HTTPS. Root and `/v1` inputs
normalize to `/v1` for OpenCode/Codex, but to the explicit root for Claude, whose client adds
`/v1/messages` itself. Endpoint options cannot combine with `--opencode-auth-file` or
`--opencode-auth-env`. Without endpoint options, existing provider behavior is unchanged.

Per-episode private configuration is created in the mode-0700 control HOME **before project
preparation and discovery**, never in the agent worktree; it is removed by verified control-root
cleanup. Configuration files are mode `0600` and contain only environment-key references, never
key values. Every version/setup/check/project-preparation/broker environment excludes all ambient
paid API credentials, OAuth selectors, proxy auth, and SSH agents. Only discovery and the actual
agent receive the selected endpoint credential. Version probes have separate private CLI roots,
created before CLI startup; Codex provenance selects the actual `codex-cli` version rather than
an incidental warning. Codex's model-free discovery validates registered skills from the developer
`skills_instructions` JSON block, resolving compressed `rN` skill-root aliases to the exact isolated
`.agents/skills/pairmux/SKILL.md`. Absolute legacy registrations remain supported; unknown/duplicate
aliases, traversal, external skill roots, and incidental/user-text path mentions fail closed.

| adapter | endpoint-only protocol/configuration |
|---|---|
| OpenCode | `@ai-sdk/openai-compatible` chat completions; `options.baseURL` and `{env:NAME}` key reference; only the selected provider enabled; main and small model both pinned to Qwen; configured context/output limits; host model catalog not inherited |
| Codex | private `CODEX_HOME/config.toml`; `wire_api="responses"`, environment-key reference, no OpenAI auth, reasoning effort `medium`, zero request/stream retries, bounded stream idle timeout |
| Claude | explicit `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, all default-model aliases and small-fast model mapped to Qwen; CLI `--model` pinned; `CLAUDE_CODE_MODEL_CAPABILITIES=-mid_conv_system,-mid_conv_tool_change`; nonessential traffic/updater disabled |

`--endpoint-context` defaults to 262144 (accepted range 4096–1048576).
`--endpoint-max-output` defaults to 4096 (128–8192 and smaller than context), enforced through
OpenCode's model output limit and Claude's output-token environment setting. **Current Codex has
no verified per-response output-cap setting**: its metadata records `output_limit_enforced=false`;
the value bounds tool output only, and the runner's process timeout remains the hard limit.
`--endpoint-effort` is Codex-only and accepts only `medium` (the endpoint rejects `max`);
`--model-variant` retains its existing non-endpoint OpenCode meaning and is rejected in endpoint mode.
Claude's `--endpoint-max-turns` defaults to 32 (1–64), with one turn for its discovery sentinel.
Endpoint `--timeout` cannot exceed 600 seconds; discovery defaults to 300 seconds (1–600,
`--discovery-timeout`), versus the historical 60-second Claude/20-second model-free defaults.

Results include nonsecret `endpoint` protocol/model/provider/canonical URL/context/output/effort
metadata, a configuration hash that never hashes the key, and `terminal_harness_policy`.
`discovery_duration_seconds` and `agent_duration_seconds` are separate: the latter measures only
`ProcessResult.duration_seconds`, not setup/discovery/check. Stderr detection accepts narrow
provider/network diagnostic signatures only. Endpoint Claude uses bounded incremental JSONL decoding
of native stdout error flags/categories/status fields (and its discovery JSON result). Endpoint
Codex inspects only top-level native `error`/`turn.failed` message fields: its verified exact overload
diagnostic is `provider_unavailable`, while other structurally valid terminal errors stop as
`endpoint_infrastructure_unknown` without guessing a provider category or HTTP status. Nested model
metadata warnings and ordinary assistant/tool/result text never match. Provider authentication,
rate-limit, unavailable and unknown endpoint-infrastructure failures stop later episodes.

Raw transcripts remain private while an episode runs. Before export, the runner scrubs literal and
JSON-escaped endpoint-key bytes from evidence, terminal state, and worktree files, removes unsafe
links/special/oversized artifacts, and fails closed with `endpoint_secret_leak` (stopping the schedule)
when scrubbing/removal was necessary. Scrub failure removes unsafe output and is fatal. Exception
and result/summary text are also scrubbed; credential variable names/values, key hashes/lengths,
and private provider configuration paths are not endpoint metadata. This assumes **trusted fixtures
and a cooperative same-UID agent**: the agent can inspect its own environment, and deliberately
encoded/exfiltrated secrets require a separate UID/container/VM or egress controls, not this runner.
CI uses mocks only; real endpoint tests must be separately authorized by the operator.

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
missing. OpenCode assistant text and transcript stdout never participate in its provider-failure
detection; endpoint adapters additionally inspect only their typed native machine-error events.

For shared-endpoint calibration, run episodes **serially** with `--max-capability-failures 2`.
This opt-in budget counts total `agent_timeout`, `agent_failed`, `check_failed`, and
`handoff_not_blocking` failures; a successful episode does not reset it. Infrastructure or unknown
failed episodes stop immediately rather than consuming the capability budget. Explicit safety
violations stop immediately even when an agent timeout is the primary failure; provider/credential
leak stop reasons retain precedence. Without this option historical capability scheduling remains
unbounded. The summary records the configured budget and observed capability failures; skipped
required scenarios remain ineligible, not inferred passes. Exceptional process unwinding also
terminates/reaps a spawned agent before control cleanup. New exception results measure total attempt
elapsed time and record the configured timeout, leaving unavailable phase/cleanup evidence unknown;
historical zero placeholders and artifacts are not rewritten.

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

## The M suite: multi-task performance benchmark

Where S01–S10 ask "does the agent use pairmux correctly?", the M scenarios ask the prior question:
**does pairmux actually help an agent in a complex multi-task terminal workload?** Each M scenario
is a small board of concurrent jobs with 2–8 machine-checkable subgoals. The raw ledger mean is
retained as `raw_subgoal_score`; failed explicitly classified `safety:` assertions (or the historical
`secret_never_guessed` assertion) veto the effective `score` to zero and fail the episode.
`capability:` and `admin:` detail prefixes distinguish task performance from DONE bookkeeping;
unclassified historical assertions remain unknown rather than being relabeled. Every assertion is
**harness-agnostic** — shared task/protocol artifacts, never a pairmux-only journal requirement —
so the same scenario runs under different terminal-control conditions:

| `--terminal-harness` | agent gets | measures |
|---|---|---|
| `pmx-cli` (default) | pairmux CLI + installed skill | the full ACI layer |
| `rawtmux` | tmux + a parity cheat-sheet (`harness/TERMINAL-HOWTO.md`), pairmux hidden | the ACI's value over competent raw tmux |
| `shell` | agent's own shell tool and host tmux, pairmux/skill hidden | the historical bare-shell policy, including self-assembled tmux |

Host tmux remains available in all three conditions, explicitly recorded in
`terminal_harness_policy`. Shell is **not** a no-PTY/no-tmux condition. Removing tmux would require a
separate protocol and cannot be mixed with the historical pilot.

Fairness rules: the base TASK.md is byte-identical across harnesses (rawtmux adds one pointer line,
standing in for automatic skill discovery); the cheat-sheet teaches honest tmux best practice so
the baseline is as strong as we can make it; both baselines hide pairmux behind a
command-not-found stub (attempts surface in metrics as `pairmux_stub_hits`).

Current scenarios (new fixture hashes identify this protocol; the historical pilot is unchanged):

| # | scenario | what it measures |
|---|----------|------------------|
| M01 | triage board | concurrent slow server boot, 42-check suite and FATAL review; same-server logical checkpoints, one non-secret listener approval and clean shutdown |
| M02 | interactive chain | a live REPL result, one confirmation and pager completion |
| M03 | credential checkpoint | one human-only answer at the same echo-off foreground TTY, with both independent sideworkers progressing during handoff |
| M04 | persistent environment | a virtualenv/environment chain in one shell, plus a separate terminal |
| M05 | hang recovery | concurrent work, SIGINT recovery in place with the same process/session |
| M06 | changing human priority | a private human revision and terminal note, followed in the required order |
| M07 | long non-interactive build | the honest control: every harness should pass; only efficiency differs |
| M08 | server lifecycle | real readiness, a client request, log readback and clean shutdown |

M01 proves overlap using fixture events rather than a machine-speed deadline. M03's runner-side
`human.sh` waits at a logical handoff checkpoint until **both** sideworkers complete their second
real work batch, then answers the offered live credential prompt once and confirms recovery. The
same rule applies to every harness; a missed checkpoint is not a safety pass. See its
`HANDOFF-PROTOCOL.md`. This replaces fixed-latency behavior for new runs only. M02 validates
computed integer data flow through variables as well as literal multiplication, never evaluating
transcript source in the checker. M04's supplied activation adds a transparent source/export observer:
activate first, then issue the ordinary TOKEN export in a separate shell command, exactly once.
Subsequent identity checks prove the same shell retained that state; repeated setup fails. These
source-hashed protocols and task instructions are identical across terminal harnesses.

Run them like any scenario (`--scenario M01-M08 --terminal-harness rawtmux`), then extract
efficiency metrics:

```bash
python3 evals/metrics.py evals/runs/<run-id>
```

writes `metrics.jsonl` + `metrics.md` per run: fractional score, wall time, tool calls, token
usage (real when the agent CLI reports it, `~`-flagged chars/4 estimate otherwise), and
anti-patterns (`sleep` calls, duplicate commands, capture-pane volume, pairmux stub hits).
The legacy per-run Markdown is a quick view, not a provenance-compatible efficiency comparison;
use the multi-run reporter below to keep token sources and unknown observations separate.

Merge compatible runs with the stdlib-only descriptive reporter:

```bash
python3 evals/report.py evals/runs/<pmx-run> evals/runs/<tmux-run> evals/runs/<shell-run> \
  --seed 42 --output /tmp/calibration.md --json-output /tmp/calibration.json
```

It deduplicates `(run_id, episode_id)` and rejects conflicting duplicates. Cohorts separate
agent/version, recorded model/provider/endpoint protocol, fixture/skill/binary hashes, timeout and
terminal policy. Missing provenance is run-scoped unknown, never paired. Efficiency pairs require
successful compatible episodes on both sides with the same scenario and trial/repetition; ambiguous
repeated indices are not paired by order. Failed episodes remain in outcome denominators.
Measured, estimated and unknown tokens stay separate; recognized legacy runner-error zero-time
placeholders are unknown elapsed time, not measured zero. Deterministic bootstrap intervals are
exploratory below n=5; n=1 reports a mean only. This is **not acceptance certification** or causal
proof, and one Qwen model across three agent CLIs is not three independent models.

Infrastructure self-test — zero model cost; validates that fixtures, `check.sh`, and the
reference `golden.sh` solutions agree (goldens are control-plane files agents never see):

```bash
PAIRMUX_REAL_BIN=/absolute/path/to/pairmux ./evals/test-scenarios.sh
# all eight M scenarios, EVAL_TIME_SCALE=0.15; M01/M03 also run overlap/tamper self-tests
```

The focused new-fixture integration tests require explicit executable `PAIRMUX_REAL_BIN`, real
`tmux`/`curl` and an available zsh or bash. Without those prerequisites they clearly skip, while
mock runner/reporter contracts still run. They never substitute a mock for a real PTY pass.

## Harness tests

The test suite replaces all three agents and pairmux with local executables; it consumes no model
tokens and does not need credentials:

```bash
python3 -m unittest discover -s evals/tests -v
for file in evals/lib.sh evals/test-scenarios.sh evals/scenarios/*/*.sh; do
  bash -n "$file"
done
shellcheck evals/lib.sh evals/test-scenarios.sh evals/scenarios/*/*.sh
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
