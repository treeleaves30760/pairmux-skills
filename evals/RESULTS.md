# Eval results

Log every eval run here: the machine, date, agent/model version, and per-scenario pass/fail.

## Format

```
### <date> — <agent/model> — <machine>
tmux <ver>, pairmux <ver>
| scenario | result | steps | notes |
| S01 | pass | 2 | ... |
...
pass rate: N/10
```

`result` = `check.sh` exit (pass = 0). `steps` = number of pairmux commands the agent issued
(lower is better for the same outcome). Note any harness quirks (e.g. Codex differences).

---

### 2026-07-19 — author self-test (human acting as the agent per SKILL.md) — macOS (darwin 25.5.0)

tmux 3.7b, pairmux 0.1.0-dev. Method: for each scenario, ran `setup.sh`, then issued exactly the
pairmux commands the skill dictates (no shortcuts), then ran `check.sh`. This validates that the
checks are passable with correct behavior and that they fail on a virgin/incorrect environment. It is
**not** a substitute for the headless Claude Code / Codex acceptance runs (see below) — it confirms the
scenarios, checks, and skill guidance are internally consistent.

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

### Pending — headless acceptance runs (P4 exit criteria)

Run with the harness in [README.md](README.md), record here:

- [ ] Claude Code (`claude -p`) passes S01–S09 headless, skill installed at `~/.claude/skills/pairmux/`.
- [ ] Codex (`codex exec`) passes at least S01–S06 and S08; note harness differences.
