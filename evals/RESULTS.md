# Eval results

Record accepted benchmark runs and a compact history of formal acceptance attempts here. Targeted
canaries remain auditable in `evals/runs/`, but they are diagnostic evidence rather than acceptance
claims.

## Run template

Copy this block for a benchmark run. Most values come from generated `summary.json`; record the
runner command, machine, and tmux version alongside it. Keep the run id and artifact location so the
claim can be reproduced and audited.

```markdown
### YYYY-MM-DD — <agent> <version> / <model> — <machine>

- runner: `python3 evals/run.py --agent ... --scenario S01-S10 --repeat N ...`
- requested provider/model: `<provider>` / `<model>` (both explicit, not agent defaults)
- run id: `<summary.json run_id>`
- artifacts: `<path to run directory>`
- tmux: `<version>`; pairmux: `<version>`, `<resolved path>`, `<binary sha256>`
- skill: `<tree sha256>`, `SKILL.md <sha256>`
- sandbox/config: `<Codex sandbox or agent-specific notes>`; project isolation
  `<result.json agent_project_isolation.method>`
- credential injection: `<none, isolated-auth-file, or isolated-auth-file-from-environment>`;
  provider `<id>`; never record source/secret
- provenance: git `<commit>` to `<end_commit>` (`dirty=false`, `end_dirty=false`, `stable=true`)
- fixtures: `summary.json.fixture_sha256` (per-scenario file/hash map)
- schedule: `<completed>/<planned>` episodes; `<skipped>` skipped; stop reason `<reason or null>`
- acceptance: profile `<profile>`; minimum repetitions `<N>`; threshold `<rate>`; eligible `<bool>`

| scenario | passed / episodes | pass rate | steps | policy rejections | wall time | notes |
|----------|-------------------|-----------|-------|-------------------|-----------|-------|
| S01 | N/N | 100% | N | N | N.Ns | ... |
| ... | ... | ... | ... | ... | ... | ... |

overall: N/N episodes passed; N broker-executed pairmux steps; N policy rejections; N.Ns runner wall
time
```

`pass` normally requires a successful agent exit, valid runner-owned exact-call proof, isolated
terminal-state assertions, and `check.sh` exit 0. S05 additionally permits `expected_human_handoff`
only for the same-terminal `wait --human --notify` still live at the runner deadline, using either
the default timeout or one valid Go duration of at least 300 seconds. Earlier signals and completed
calls are not interruption proof. `steps`
counts broker-executed calls, not transcript grep or agent JSON files. A fully validated absolute
working directory outside the episode work root is rejected without execution, recorded as a policy
rejection, and may be nonfatal; malformed requests and every other broker protocol violation are
fatal. A normalized provider authentication, rate-limit, or post-retry service failure stops the
remaining schedule and leaves P4 ineligible; raw provider error text is not copied into result or
summary fields.

---

### 2026-07-19 — historical pre-hardening author self-test — macOS (darwin 25.5.0)

tmux 3.7b, pairmux 0.1.0-dev. Method: for each scenario, ran `setup.sh`, then issued exactly the
pairmux commands the skill dictates (no shortcuts), then ran `check.sh`. This validates that the
checks are passable with correct behavior and that they fail on a virgin/incorrect environment. It is
**not** a substitute for the headless Claude Code / Codex acceptance runs (see below) — it confirms the
scenarios, checks, and skill guidance are internally consistent.

This run predates the current broker, nested-project isolation, and hardened fixture/checker hashes.
It remains historical context and cannot support current acceptance.

| scenario | result | steps | notes |
|----------|--------|-------|-------|
| S01 instant command      | pass | 2 | `new` + `run`; done, exit 0 |
| S02 ~20s build           | pass | 2 | `run --timeout 30s` blocked ~20.6s to `done`; no sleep |
| S03 needle in 10k lines  | pass | 3 | `run` truncated → `log --grep FATAL` found `code E4231` |
| S04 `[y/N]` confirm      | pass | 4 | `awaiting-input` → `send --text y --enter` → `CONFIRMED-DELETING` |
| S05 password prompt      | pass | 3 | secret detected; `wait --human --notify` handoff; nothing typed |
| S06 Python REPL          | pass | 3 | `new --cmd python3` → `send` → `peek` read back `7006652` |
| S07 stuck in pager       | pass | 3 | `peek` saw `:` → `send --text q` → idle |
| S08 server + curl        | pass | 5 | two terminals; client got 200; server logged `"GET / HTTP/1.1" 200` |
| S09 C-c recovery         | pass | 4 | `send C-c` → `wait --idle` (settle) → `run` recovered same terminal |
| S10 note relay           | pass | 2 | `peek` surfaced the note → wrote token to `token.txt` |

pass rate: 10/10 (author self-test)

Negative / virgin-environment checks (no false passes):

| check                              | expected | got |
|------------------------------------|----------|-----|
| S01 virgin env (no agent actions)  | fail     | fail (exit 1) |
| S02 virgin env                     | fail     | fail (exit 1) |
| S02 transcript containing `sleep 20` | fail   | fail (exit 1) — sleep-gate works |
| S04 virgin env                     | fail     | fail (exit 1) |
| S04 agent answered `n` (ABORTED)   | fail     | fail (exit 1) |

Notes:
- S09: interrupting is asynchronous — running the recovery command immediately after `C-c` returns
  `E_BUSY`; the correct flow (and what the skill teaches) is `wait --idle` until the terminal settles,
  then `run`. The check rewards the robust flow.
- S08: the server prints its readiness banner during the initial `run`, so the agent reads readiness
  from that output rather than `wait --pattern` (which only matches output produced after it starts).

---

## Pre-acceptance P4 attempts

These full-profile runs are retained as transparent pre-acceptance history. Subsequent changes
addressed evaluator or guidance gaps where applicable. Targeted follow-up runs are not listed here;
their artifacts remain under `evals/runs/`.

| run id | git commit | result | failure focus |
|--------|------------|--------|---------------|
| `20260719T004757.211669Z-84952-3ce6dafc` | `d2fe3aa` | 27/30 | S10 0/3: exact-token newline mismatch; r1 also exposed project-root/cwd-policy handling |
| `20260719T012459.473483Z-13610-1b53341f` | `b425856` | 28/30 | S08 2/3; S09 2/3: equivalent journal evidence and recovery guidance |
| `20260719T015615.849508Z-44088-8be8218f` | `1446a73` | 27/30 | S01 2/3; S08 1/3: provider early stop and equivalent server journal readback |
| `20260719T061906.478016Z-19329-7168026d` | `e02c91a` | 29/30 | S05 2/3: evaluator rejected a live 600s handoff retry after OpenCode's 120s client disconnect |
| `20260719T070137.908603Z-49635-46b70d75` | `732b52f` | 29/30 | S05 2/3: exact 300s retry had trailing global `--json`; shared decoder/socket validation did not yet mirror pairmux global parsing |

---

## Accepted P4 runs

### 2026-07-19 — OpenCode 1.18.3 / DeepSeek V4 Flash — macOS 26.5.1 arm64

- runner: `python3 evals/run.py --agent opencode --provider huggingface --model huggingface/deepseek-ai/DeepSeek-V4-Flash --opencode-auth-env HF_TOKEN --acceptance-profile p4 --scenario S01-S10 --repeat 3 --timeout 180 --pairmux-bin ../pairmux/bin/pairmux --output-dir evals/runs`
- requested provider/model: `huggingface` / `huggingface/deepseek-ai/DeepSeek-V4-Flash`
- run id: `20260719T073333.055301Z-76364-d8febe70`
- artifacts: `evals/runs/20260719T073333.055301Z-76364-d8febe70`
- machine: Darwin 25.5.0 arm64; macOS 26.5.1
- tmux: 3.7b; pairmux: 0.1.0-dev, `../pairmux/bin/pairmux`,
  `0288e5a85890ba92587c8b757116ee521a3174a6f0fe4b7d56eb1561c48f7919`
- skill: tree `9a3b3c9521e14ddec0d7d89fbcef32035ac9b9b339ded12a595fae99ee3c3c4b`,
  `SKILL.md 2d132d1ca2c02820fbf4d5bd825b96075bcddabc65318904c8f88e7eb8d384f7`
- sandbox/config: OpenCode `--pure --auto`; project isolation `nested-committed-git-root`
- credential injection: `isolated-auth-file-from-environment`; provider `huggingface`; 30/30
  installations verified and 30/30 cleanups verified; no source name or secret persisted in the
  generated run artifacts
- provenance: git `2f0e6a48ae8fc5645236417a349d12befa60854a` to the same commit
  (`dirty=false`, `end_dirty=false`, `stable=true`)
- fixtures: all S01-S10 file hashes recorded in `summary.json.fixture_sha256`
- schedule: 30/30 episodes; 0 skipped; no stop reason
- acceptance: profile `p4`; minimum repetitions 3; threshold 1.0; eligible `true`; no reasons
- audit: 0 trace errors, 0 provider failures, 0 control-cleanup failures, and no remaining
  `pairmux-eval-control-*` directory

| scenario | passed / episodes | pass rate | steps | policy rejections | wall time | notes |
|----------|-------------------|-----------|-------|-------------------|-----------|-------|
| S01 | 3/3 | 100% | 6 | 0 | 45.394s | instant command |
| S02 | 3/3 | 100% | 7 | 0 | 138.463s | slow command completion |
| S03 | 3/3 | 100% | 9 | 0 | 81.234s | truncated-output log search |
| S04 | 3/3 | 100% | 15 | 0 | 96.688s | interactive confirmation |
| S05 | 3/3 | 100% | 10 | 0 | 548.795s | `expected_human_handoff`; no secret submitted |
| S06 | 3/3 | 100% | 17 | 0 | 97.658s | REPL interaction |
| S07 | 3/3 | 100% | 12 | 0 | 67.474s | pager exit |
| S08 | 3/3 | 100% | 15 | 0 | 134.786s | long-lived server and client |
| S09 | 3/3 | 100% | 12 | 0 | 78.775s | in-place interrupt and recovery |
| S10 | 3/3 | 100% | 4 | 0 | 56.973s | note relay |

overall: 30/30 episodes passed; 107 broker-executed pairmux steps; 0 policy rejections;
1348.061s runner wall time

---

## Qwen endpoint diagnostic status (2026-10-09; not acceptance)

All runs below used the explicit free `qwen3.8-27b` endpoint serially, private per-episode
configuration and a source-built `pairmux 0.6.0-dev` binary; **not published v0.6.0**. The skills
checkout was dirty, the acceptance profile was `none`, and every run was ineligible for P4.
Run IDs use UTC (2026-10-08); this status date follows the operator's local date.

| agent | run id | S01 | executed pairmux calls | wall / discovery / agent time |
|---|---|---|---:|---|
| OpenCode 1.18.34 | `20261008T192837.591586Z-38104-ee0d00a8` | pass | 5 | 70.765 / 0.756 / 68.787s |
| Claude Code 2.1.294 | `20261008T193256.458202Z-39509-12ba1568` | pass | 4 | 156.408 / 5.897 / 149.674s |
| Codex 0.160.1, initial | `20261008T193631.490225Z-41730-71a3fcab` | discovery runner error | 0 | unknown; legacy zero placeholder is not elapsed time |
| Codex 0.160.1, retry | `20261008T201250.942985Z-82125-87be3a8e` | generation failed | 0 | 2.144 / 0.482 / 0.648s |

Artifacts remain private under `evals/runs/<run-id>`. Binary SHA256:
`0b4c4db3248be034448db434daf2f25e101aa4496aeccddef5560ae14cb6f759`.
Canonical skill tree:
`2c246ff16138edce0e6246204bb3e81204587a7064b21657bbf8ac8b5956ff9b`;
SKILL.md: `af5225b7ee92ed15bddd82976e628e01a78cd4c431160a914339aec9169e824c`.
The retry proved corrected version provenance, exact isolated skill discovery and verified
credential/control cleanup, but its native endpoint diagnostic reported high demand before any
pairmux action. Model requests stopped; no immediate retries or paid fallback were attempted.
The owned SSH tunnel subsequently disconnected with a transport timeout; it was not restarted.
Its original `failure_class=agent_failed` is preserved; a subsequent typed-machine diagnostic fix
classifies such new events as fatal infrastructure without rewriting historical evidence.

One model across three agent harnesses is not three models. These four diagnostics provide no
cross-terminal efficiency pairs or statistical acceptance. Formal Claude S01–S09, Codex
S01–S06+S08 and the bounded 24-episode M calibration remain pending. All eight M fixtures now
have passing local untouched-negative/golden checks; those are infrastructure tests, not model runs.
Final local integration ran 155 tests (144 passed; 11 real-fixture tests explicitly skipped without
prerequisites); those 11 separately passed with a real binary/tmux, alongside all eight goldens and
M01/M03 three-harness overlap/tamper self-tests. Reporter regressions passed 39/39; independently
reproduced integral-trial, pair-specific denominator and missing-source-hash defects were fixed and
rechecked. ShellCheck and Python 3.9 grammar checks passed. Linux CI run
[`37878846465`](https://github.com/treeleaves30760/pairmux-skills/actions/runs/37878846465)
at `7087cf809c76d4731f9336d35be7ef8a20f84690` passed the same 155-test suite (11 explicit real-fixture
skips), Python compilation, per-file shell syntax, ShellCheck and commit policy. The preceding run
`37878364127` failed ShellCheck on two cleanup guards; explicit `if` guards fixed those warnings,
and all eight real goldens plus M01/M03 overlap/tamper self-tests passed again without weakening CI.
Actual Python 3.9 runtime coverage is not claimed.
The revised event-gated M01/M03 hashes and explicit safety-veto protocol must not be pooled with
the historical pilot below. Documentation HTTPS was completed by the operator on 2026-10-09;
a public HTTPS read of the Getting Started page succeeded. At that diagnostic checkpoint,
v0.6.0 publication remained pending; the completed release is recorded below.

### 2026-10-10 — clean-checkout Qwen P4 attempt, stopped at the failure budget

Core pairmux v0.6.0 was published once from `8717fa1e6399e188e16d8f51febcedb7bc550973`:
[Release 37949714403](https://github.com/treeleaves30760/pairmux/actions/runs/37949714403)
and all six actual public-installation jobs in
[acceptance 37950571238](https://github.com/treeleaves30760/pairmux/actions/runs/37950571238)
succeeded. Documentation follow-up [PR #9](https://github.com/treeleaves30760/pairmux/pull/9)
merged at `dc23e7f`; main CI `37956889652`, Docs deployment `37956889682` and public HTTPS
changelog verification passed. These are release/platform results, not model acceptance.

The operator explicitly authorized bounded readiness and a serial 16-S/24-M schedule on the
free Brandy `qwen3.8-27b` endpoint. A new owned tunnel used the existing trusted route with
recorded host keys and strict, noninteractive verification. Seven serial HTTP-200 readiness
requests proved model listing and tool-call/result round trips for Messages, Responses with
`medium` effort, and chat completions. No retry, paid fallback or global configuration change
was used. Native protocol readiness is not proof of agent CLI acceptance.

Claude Code `2.1.295` then ran S01–S09 once with explicit provider/model and
`--acceptance-profile p4`, a clean/stable skills checkout
`263c49634160eeff225b854bc37eabe1f6e9eb43`, and the verified public 0.6.0 Darwin ARM64
binary (identical native/wheel SHA256
`857eab2ab3977e0c6c00a186e7a9db159f9d83a8e7bafca687cc52e8be6c9c71`).
Run `20261009T163301.099265Z-71610-e1b9829e` is named by its UTC start; this dated entry
uses the operator's local date. Canonical skill tree SHA256:
`2c246ff16138edce0e6246204bb3e81204587a7064b21657bbf8ac8b5956ff9b`;
SKILL.md: `af5225b7ee92ed15bddd82976e628e01a78cd4c431160a914339aec9169e824c`.
Total run wall time was 1987.383 seconds. Per-episode agent timeout was 300 seconds,
discovery timeout 300 seconds, output cap 4096 tokens, and turn cap 32. Each episode
isolated its work/skill, HOME, provider settings and terminal endpoint.

| scenario | outcome | executed pairmux calls | total wall / discovery / agent time (seconds) |
|---|---|---:|---|
| S01 | pass | 5 | 152.631 / 6.871 / 144.418 |
| S02 | pass | 4 | 130.806 / 7.191 / 121.983 |
| S03 | pass | 5 | 186.924 / 6.738 / 178.704 |
| S04 | fail: `agent_timeout` | 4 | 312.439 / 9.617 / 300.059 |
| S05 | pass: expected human handoff | 5 | 312.417 / 10.320 / 300.119 |
| S06 | pass | 10 | 205.005 / 6.087 / 197.075 |
| S07 | pass | 6 | 169.875 / 8.193 / 158.774 |
| S08 | pass | 7 | 204.358 / 6.226 / 196.409 |
| S09 | fail: `agent_timeout` | 10 | 312.088 / 6.890 / 300.093 |

**7/9 passed; P4 remains ineligible.** The original S04/S09 failure classes and raw evidence
are preserved. S04's checker found the confirmation unanswered; S09's checker could not prove
completed in-place C-c/recovery. Native S04 events also recorded Bash permission denials;
these observations do not isolate a model-only cause, and no permissions were weakened.
S05 passed the runner's expected, live-bound human-handoff criterion at the deadline; it is
not a claim that an agent supplied a credential or finished the protected command.

The second recorded capability-class failure exhausted the **total budget of two across the
entire schedule**. Successes and later invocations do not reset it. The controller stopped
with `capability_failure_limit`; Codex's seven formal episodes and all 24 M episodes were
**not started**, not failed or passed. No automatic retry or additional readiness request followed.
The owned tunnel closed successfully and observed owned controller/agent processes exited;
all nine recorded terminal endpoints were separately verified absent afterward.
All nine episode results recorded verified credential cleanup with no control-cleanup failure;
private evidence was secret-scanned and 303 original files were copied byte-for-byte into
ignored `evals/runs/<run-id>` storage. Historical runs and pilot denominators are unchanged.

A descriptive multi-run report contains only these nine Claude/pmx-cli observations, no
cross-terminal pairs and no M-suite result. n=1 scenario means do not establish H1–H4,
causal efficiency, or statistical acceptance. Stable-source regression verification passed
144/155 tests with 11 explicit prerequisite skips; those 11 separately passed against the
public binary, alongside all eight untouched negatives/goldens and M01/M03 overlap/tamper
self-tests. Local regression passes are not substituted for model outcomes.

## Headless acceptance status (P4 exit criteria)

An item is complete only when a clean checkout run uses explicit `--provider`, `--model`, and
`--acceptance-profile p4`, and `summary.json.acceptance.eligible` is true. The profile requires a
100% threshold, at least one repetition for each required Claude/Codex scenario, and at least three
repetitions for each of S01-S10 for OpenCode. An ineligible P4 run exits nonzero even when every
selected episode passed, so partial runs cannot be mistaken for acceptance.

Run with the harness in [README.md](README.md), record here:

- [ ] Claude Code (`claude -p`) passes S01–S09 headless with the runner's isolated, hash-verified skill copy.
- [ ] Codex (`codex exec`) passes at least S01–S06 and S08; note harness differences.
- [x] OpenCode `huggingface/deepseek-ai/DeepSeek-V4-Flash` repeatedly passes S01–S10 with
  `--pure --auto`; record pass rate and steps.

DeepSeek V4 Flash acceptance is established by run
`20260719T073333.055301Z-76364-d8febe70`; the earlier one-off S01 canary remains diagnostic only.

## M-suite pilot runs (calibration, not acceptance)

### 2026-08-01 — opencode 1.18.9 / openrouter/deepseek/deepseek-v4-flash-0731 (variant `max`) — macOS (darwin arm64), tmux 3.7b

Pilot for the multi-task performance benchmark: `--scenario M01,M03,M07 --repeat 2 --timeout 420`
across all three `--terminal-harness` conditions, `--opencode-auth-file` credential isolation,
pairmux `0.1.0-dev` (sibling build), skills repo @ `61d48eab5`. Runs (auditable under `evals/runs/`,
metrics in each run's `metrics.jsonl`/`metrics.md`):

| harness | run id | passed | mean score M01/M03/M07 | mean wall M01/M03/M07 |
|---|---|---|---|---|
| pmx-cli | `20260731T234237.647891Z-91130-fc3715e5` | 5/6 | 1.00 / 0.90 / 1.00 | 195s / 135s / 82s |
| rawtmux | `20260731T235623.829851Z-7824-8da40a78` | 5/6 | 1.00 / 0.70 / 1.00 | 110s / 266s / 103s |
| shell | `20260801T001550.920690Z-27788-5398f9f2` | 5/6 | 0.60 / 1.00 / 1.00 | 106s / 177s / 80s |

Calibration findings (n=2 — directional only): M07 confirms the honest control (pmx-cli agents
correctly skip pairmux; the rawtmux cheat-sheet costs +25% wall / 2.2× tool calls there); M03
separates on wall time and failure shape (pmx-cli's one miss was only the DONE.txt marker, 4/5
subgoals; rawtmux burned a full 420s timeout); the shell condition self-assembled tmux for M03
(host tmux on PATH) and attempted the hidden pairmux 4 times (stub hits); one shell M01 failure was
an OpenRouter 504, not capability. Zero secret leaks in 18/18 episodes. Before P5: raise M01's
interactive weight, decide whether the shell condition strips tmux from PATH, tag provider-5xx as
infra failures, and run n≥5.
