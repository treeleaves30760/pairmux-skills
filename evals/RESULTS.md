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

---

## Headless acceptance status (P4 exit criteria)

These remain pending until a clean checkout run uses explicit `--provider`, `--model`, and
`--acceptance-profile p4`, and `summary.json.acceptance.eligible` is true. The profile requires a
100% threshold, at least one repetition for each required Claude/Codex scenario, and at least three
repetitions for each of S01-S10 for OpenCode. An ineligible P4 run exits nonzero even when every
selected episode passed, so partial runs cannot be mistaken for acceptance.

Run with the harness in [README.md](README.md), record here:

- [ ] Claude Code (`claude -p`) passes S01–S09 headless with the runner's isolated, hash-verified skill copy.
- [ ] Codex (`codex exec`) passes at least S01–S06 and S08; note harness differences.
- [ ] OpenCode `huggingface/deepseek-ai/DeepSeek-V4-Flash` repeatedly passes S01–S10 with
  `--pure --auto`; record pass rate and steps.

DeepSeek V4 Flash acceptance is still pending. A one-off S01 smoke/canary, even if successful, does
not establish the required repeated S01–S10 pass rate or step-count baseline.
