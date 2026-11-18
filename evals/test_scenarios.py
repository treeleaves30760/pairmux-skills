#!/usr/bin/env python3
"""Infrastructure self-test for the M suite — zero model cost, macOS/Linux/Windows.

For each scenario (default: every M*), in an isolated copy:
  1. negative: setup, then check on the untouched fixture MUST fail;
  2. golden:   setup, run golden.py (the reference pairmux solution), then check MUST pass with
               every subgoal green.
Then M01/M03's protocol regressions (golden.py --self-test) run. EVAL_TIME_SCALE shrinks fixture
sleeps (default 0.15 here; real runs use 1).

    python evals/test_scenarios.py [M01 M03 ...]
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

EVALS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS_DIR))
import evallib  # noqa: E402

SHARED = ("evallib.py", "termsupport.py")
SELF_TESTED = ("M01", "M03")


def control(script: Path, *args: str, log: Path, cwd: Path, timeout: float = 600) -> bool:
    with open(log, "wb") as handle:
        try:
            completed = subprocess.run(evallib.python_argv(script, *args), cwd=cwd,
                                       stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            handle.write(f"\n[test_scenarios] {script.name} timed out after {timeout}s\n".encode())
            return False
    return completed.returncode == 0


def indent(path: Path, tail: int | None = None) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if tail is not None:
        lines = lines[-tail:]
    return "\n".join("    " + line for line in lines)


def cleanup_scenario(scen_dir: Path) -> None:
    """Stop this copy's own endpoint and scripted humans; never touch any other server."""
    exports, _prepends = evallib.parse_env_file(scen_dir / "env.sh")
    socket = exports.get("PAIRMUX_SOCKET")
    if socket:
        env = dict(os.environ, **exports)
        evallib.stop_endpoint(socket, env, evallib.effective_backend(env))
    private_dirs = [scen_dir]
    config = scen_dir / ".mig-config"
    if config.is_file():
        match = re.search(r"^MIG_TMP=(.+)$", config.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            private_dirs.append(Path(match.group(1).strip()))
    for root in private_dirs:
        for pid_file in root.rglob("human.pid") if root.is_dir() else ():
            try:
                evallib.terminate_pid(int(pid_file.read_text().strip()))
            except (OSError, ValueError):
                pass
    for root in private_dirs[1:]:
        evallib.remove_tree(root)


def main(argv: list[str]) -> int:
    os.environ.setdefault("EVAL_TIME_SCALE", "0.15")
    if not os.environ.get("PAIRMUX_REAL_BIN"):
        for candidate in evallib.sibling_pairmux_candidates():
            if evallib.is_executable(candidate):
                os.environ["PAIRMUX_REAL_BIN"] = str(candidate.resolve())
                break
    scenarios = argv or sorted(path.name for path in (EVALS_DIR / "scenarios").glob("M[0-9]*")
                               if path.is_dir())
    if not scenarios:
        print("no M scenarios found", file=sys.stderr)
        return 1
    failures = 0
    for scen in scenarios:
        tmp = Path(tempfile.mkdtemp(prefix="pmx-scen-test-"))
        root = tmp / "evals"
        (root / "scenarios").mkdir(parents=True)
        for name in SHARED:
            shutil.copy2(EVALS_DIR / name, root / name)
        shutil.copytree(EVALS_DIR / "scenarios" / scen, root / "scenarios" / scen,
                        ignore=shutil.ignore_patterns("__pycache__", "state", "env.sh", "subgoals.json"))
        scen_dir = root / "scenarios" / scen
        ok = False
        try:
            print(f"== {scen}: negative (untouched fixture must fail check) ==", flush=True)
            if not control(scen_dir / "setup.py", log=scen_dir / "setup.log", cwd=scen_dir):
                print(f"FAIL [{scen}] setup.py errored", file=sys.stderr)
                print(indent(scen_dir / "setup.log", 40), file=sys.stderr)
                failures += 1
                continue
            if control(scen_dir / "check.py", log=scen_dir / "check-negative.log", cwd=scen_dir):
                print(f"FAIL [{scen}] check.py passed on an untouched fixture", file=sys.stderr)
                print(indent(scen_dir / "check-negative.log"), file=sys.stderr)
                failures += 1
                continue
            cleanup_scenario(scen_dir)

            print(f"== {scen}: golden (reference solution must pass check) ==", flush=True)
            if not control(scen_dir / "setup.py", log=scen_dir / "setup.log", cwd=scen_dir):
                print(f"FAIL [{scen}] setup.py errored", file=sys.stderr)
                print(indent(scen_dir / "setup.log", 40), file=sys.stderr)
                failures += 1
                continue
            if not control(scen_dir / "golden.py", log=scen_dir / "golden.log", cwd=scen_dir):
                print(f"FAIL [{scen}] golden.py errored", file=sys.stderr)
                print(indent(scen_dir / "golden.log", 40), file=sys.stderr)
                failures += 1
                continue
            if not control(scen_dir / "check.py", log=scen_dir / "check-golden.log", cwd=scen_dir):
                print(f"FAIL [{scen}] check.py rejected the golden run", file=sys.stderr)
                print(indent(scen_dir / "check-golden.log"), file=sys.stderr)
                failures += 1
                continue
            for line in (scen_dir / "check-golden.log").read_text(encoding="utf-8").splitlines():
                if line.startswith("score:"):
                    print(f"   {scen} golden {line}")
            ok = True
            print(f"OK {scen}", flush=True)
        finally:
            cleanup_scenario(scen_dir)
            if ok:
                try:
                    evallib.remove_tree(tmp)
                except OSError:
                    print(f"warning: could not remove {tmp}", file=sys.stderr)

    for scen in scenarios:
        if scen in SELF_TESTED:
            print(f"== {scen}: logical overlap and tamper regressions ==", flush=True)
            completed = subprocess.run(evallib.python_argv(
                EVALS_DIR / "scenarios" / scen / "golden.py", "--self-test"))
            if completed.returncode != 0:
                failures += 1

    if failures:
        print(f"test-scenarios: {failures} scenario(s) failed", file=sys.stderr)
        return 1
    print(f"test-scenarios: all {len(scenarios)} scenario(s) validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
