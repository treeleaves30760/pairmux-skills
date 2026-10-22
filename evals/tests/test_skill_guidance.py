"""Model-free regression checks for the canonical skill's safety and CLI contracts."""

from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "pairmux"


class SkillGuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        cls.refs = {
            name: (SKILL / "references" / f"{name}.md").read_text(encoding="utf-8")
            for name in ("commands", "interactive", "collaboration", "troubleshooting")
        }
        cls.install = (ROOT / "install-map.md").read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.guidance = "\n".join([cls.main, *cls.refs.values()])

    def test_main_stays_concise_with_progressive_disclosure(self) -> None:
        self.assertTrue(self.main.startswith("---\nname: pairmux\ndescription: >-\n"))
        self.assertLessEqual(len(self.main.splitlines()), 220)
        for name in self.refs:
            self.assertIn(f"(references/{name}.md)", self.main)

    def test_backend_and_shell_precedence_are_explicit(self) -> None:
        commands = self.refs["commands"]
        self.assertIn("`PAIRMUX_SHELL` > `SHELL` > OS fallback", commands)
        self.assertIn("real file", commands)
        for detail in ("Windows", "3.2", "both", "already running"):
            self.assertIn(detail, commands)
        self.assertIn("native Windows", self.readme)
        self.assertIn("POSIX", self.readme)

    def test_running_shell_waits_for_completion_without_losing_prompts(self) -> None:
        loop = self.main.split("## The golden loop", 1)[1].split("## Iron rules", 1)[0]
        self.assertIn("pairmux wait build --done --idle 800", loop)
        self.assertIn("future completion", self.main)
        self.assertIn("Answer a prompt once", self.main)
        self.assertIn("Prefer event-aware bounded observation", self.main)
        self.assertIn("pairmux send <name> --key C-c", self.main)
        self.assertIn("pairmux wait <name> --idle 800", self.main)
        self.assertNotIn("--key C-\\", self.guidance)

    def test_startup_loop_orders_submission_observation_and_health_gate(self) -> None:
        loop = self.main.split("## The golden loop", 1)[1].split("## Iron rules", 1)[0]
        ordered_steps = (
            "Submit the command first",
            "Estimate time to first meaningful signal",
            "initial observation generally 30s",
            "Examine returned output/status",
            "Verify healthy startup before unrelated work or a long wait",
        )
        positions = [loop.index(step) for step in ordered_steps]
        self.assertEqual(positions, sorted(positions))
        for detail in (
            "shorter for fast tasks",
            "A bounded run counts",
            "no extra wait if it returned enough evidence",
            "unknown/silent is not healthy",
            "--done --idle 800 --timeout 30s",
        ):
            self.assertIn(detail, loop)

    def test_startup_policy_is_consistent_across_guidance_surfaces(self) -> None:
        surfaces = {
            "main": self.main,
            **{name: self.refs[name] for name in ("commands", "collaboration", "troubleshooting")},
            "readme": self.readme,
            "fallback": self.install.split("## Fallback:", 1)[1],
        }
        for name, text in surfaces.items():
            with self.subTest(document=name):
                normalized = " ".join(text.split()).lower()
                for detail in (
                    "first meaningful signal",
                    "30s",
                    "shorter",
                    "returned output/status",
                    "unrelated work or a long wait",
                    "unknown/silent is not healthy",
                    "brief sleep is only a fallback when no suitable blocking observation is available",
                    "excluded from the 30s startup rule",
                    "600s",
                    "intentional passive listening",
                ):
                    self.assertIn(detail, normalized)
                self.assertRegex(normalized, r"(?:not|never) repeated blind polling")
                self.assertNotIn("never sleep", normalized)
                self.assertNotIn("subscribe, don't poll", normalized)
                self.assertNotIn("run it and keep waiting", normalized)

    def test_ordinary_wait_hints_do_not_automatically_escalate(self) -> None:
        commands = " ".join(self.refs["commands"].split())
        self.assertIn("CLI default `60s`", commands)
        self.assertIn("overall deadline (default `300s`)", commands)
        self.assertIn("A `timeout` is not a failure", commands)
        self.assertIn("longer hint is not automatic escalation", commands)
        self.assertIn("no suitable blocking observation", commands)
        self.assertIn("never read secret spans", commands)
        self.assertIn("with the longer deadline in `next`", commands)

    def test_startup_examples_use_explicit_short_deadlines(self) -> None:
        for name, text in (("main", self.main), ("interactive", self.refs["interactive"])):
            for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
                for line in block.splitlines():
                    if not re.match(r"pairmux (?:run|wait) ", line) or "--human" in line:
                        continue
                    with self.subTest(document=name, command=line):
                        timeout = re.search(r"--timeout (\d+)s\b", line)
                        self.assertIsNotNone(timeout)
                        if timeout is not None:
                            self.assertGreater(int(timeout.group(1)), 0)
                            self.assertLessEqual(int(timeout.group(1)), 30)
        subscriptions = self.refs["collaboration"].split("## Subscribing", 1)[1].split("## Notes from", 1)[0]
        self.assertLess(subscriptions.index("after verified startup"), subscriptions.index("--timeout 600s"))
        self.assertIn("intentional passive listening", subscriptions)

    def test_planning_evals_cover_startup_evidence_and_exceptions(self) -> None:
        suite = json.loads((ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(suite["skill_name"], "pairmux")
        ids = [case["id"] for case in suite["evals"]]
        self.assertEqual(len(ids), len(set(ids)))
        names = [case["name"] for case in suite["evals"]]
        self.assertEqual(len(names), len(set(names)))
        cases = {case["name"]: case for case in suite["evals"]}
        for name in ("windows-program-readiness", "nested-worker-note", "human-handoff-boundaries"):
            self.assertIn(name, cases)
        required_coverage = {
            "slow-build-startup-before-context-switch": ("first meaningful signal", "30s", "unknown", "healthy startup"),
            "ready-in-initial-run-no-extra-wait": ("redundant", "already-printed", "alive"),
            "credential-passive-and-fallback-waits": ("--human --notify", "300s", "30s", "600s", "brief fallback sleep", "sensitive"),
        }
        for name, details in required_coverage.items():
            with self.subTest(case=name):
                case = cases[name]
                self.assertIn("do not execute", case["prompt"].lower())
                self.assertEqual(case["files"], [])
                self.assertTrue(case["expected_output"])
                self.assertGreaterEqual(len(case["expectations"]), 4)
                expectations = " ".join(case["expectations"])
                for detail in details:
                    self.assertIn(detail, expectations)

    def test_program_terminal_does_not_gain_shell_completion_from_sentinel_mode(self) -> None:
        commands = self.refs["commands"]
        self.assertIn("`run` and `wait --done` reject program terminals", commands)
        self.assertIn('`mode:"sentinel"`', commands)
        self.assertIn("`running` or `dead`", commands)
        self.assertIn("pairmux wait repl --idle 800", self.refs["interactive"])
        self.assertIn("not proof", self.refs["interactive"])

    def test_nested_notes_address_the_creator_supplied_owner(self) -> None:
        collaboration = self.refs["collaboration"]
        self.assertIn("pairmux --socket team note worker", collaboration)
        self.assertIn("pairmux --socket team wait worker --note", collaboration)
        self.assertIn("child endpoint", collaboration)
        self.assertIn("creator", collaboration)
        self.assertNotIn('pairmux note "$PAIRMUX_NAME"', self.guidance)
        self.assertNotRegex(self.guidance, r"PAIRMUX_(?:PARENT|OWNER)_SOCKET")

    def test_handoff_does_not_promise_redaction_or_auto_peek(self) -> None:
        collaboration = self.refs["collaboration"]
        for detail in ("human-done", "note text", "dead", "not redaction", "journal"):
            self.assertIn(detail, collaboration)
        self.assertIn("Never put credentials in notes", collaboration)
        self.assertIn("Do not automatically `peek`", collaboration)
        self.assertIn("one valid explicit timeout of at least 300s", self.main)
        self.assertIn("immediately reissue", self.main)
        self.assertIn("pairmux wait repl --idle 800", collaboration)
        self.assertIn("replay that same note", collaboration)
        self.assertIn("Do not spin or send a dummy key", collaboration)
        self.assertNotRegex(self.guidance, r"--human` (?:never returns|returns no) `output`")

    def test_post_handoff_completion_can_replay_the_whole_command_span(self) -> None:
        for text in (self.main, *[self.refs[name] for name in ("commands", "collaboration", "interactive")]):
            normalized = " ".join(text.split())
            self.assertIn("whole command span", normalized)
            self.assertIn("may replay earlier human input", normalized)
            self.assertNotIn("only when remaining output is known safe", normalized)
            self.assertNotIn("only when later output is known safe", normalized)
        for name in ("commands", "collaboration"):
            normalized = " ".join(self.refs[name].split())
            self.assertIn("next `run` settles the pending completion", normalized)
            self.assertIn("`send` acknowledges notes but does not settle", normalized)

    def test_pattern_and_output_contracts_are_scoped(self) -> None:
        self.assertIn("Pattern waits observe future output only", self.main)
        commands = self.refs["commands"]
        for detail in ("help", "plain text", "JSON-RPC", "derived terminal status", "`issues`"):
            self.assertIn(detail, commands)
        self.assertNotIn("Every non-interactive command speaks", commands)

    def test_installer_is_offline_executable_bundled_and_replaces_managed_files(self) -> None:
        for text in (self.install, self.readme):
            with self.subTest(document="install-map" if text == self.install else "README"):
                for detail in ("five", "build time", "offline", "SHA-256", "replaces", "preserves"):
                    self.assertIn(detail, text)
                self.assertIn("fresh executable", text)
        for detail in ("current working directory", "legacy", ".codex/skills/", "dev", "refuses"):
            self.assertIn(detail, self.install)
        self.assertIn("configuration directory already exists", self.install)
        self.assertNotRegex(self.install, re.escape("When a shell command is **slow**"))


if __name__ == "__main__":
    unittest.main()
