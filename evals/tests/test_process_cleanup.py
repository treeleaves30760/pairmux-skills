#!/usr/bin/env python3
"""Model-free process cleanup regressions using only an owned sleeping child."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("pairmux_eval_process_run", Path(__file__).resolve().parents[1] / "run.py")
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class ProcessCleanupTests(unittest.TestCase):
    def test_timeout_observer_exception_reaps_the_owned_child(self) -> None:
        children = []
        original_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            return child

        def observer(_process):
            raise RuntimeError("synthetic timeout observer failure")

        with tempfile.TemporaryDirectory(prefix="pairmux-process-test-") as tmp:
            root = Path(tmp)
            try:
                with mock.patch.object(runner.subprocess, "Popen", side_effect=spawn):
                    with self.assertRaisesRegex(RuntimeError, "synthetic timeout observer failure"):
                        runner.run_process(
                            [sys.executable, "-I", "-B", "-c", "import time; time.sleep(30)"],
                            cwd=root, env={"PATH": os.environ.get("PATH", "")},
                            stdout_path=root / "stdout", stderr_path=root / "stderr",
                            timeout=0.05, cleanup_group=True, timeout_observer=observer,
                        )
                self.assertEqual(len(children), 1)
                self.assertIsNotNone(children[0].poll(), "exception left the agent child alive")
            finally:
                for child in children:
                    if child.poll() is None:
                        runner.terminate_process_group(child, grace_seconds=0.1)
                    child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
