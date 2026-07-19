# Releasing pairmux-skills

This repository distributes a content-only Agent Skill. Its primary channel is
GitHub, including installation through `npx skills`. It does not produce a
Python package, `.deb`, or `.rpm`, so PyPI and APT do not apply here. Operating
system packaging belongs to the companion `pairmux` repository.

## Release checklist

1. Validate the canonical skill and model-free eval harness:

   ```sh
   skills-ref validate ./skills/pairmux
   DISABLE_TELEMETRY=1 npx --yes skills add . --list
   python3 -m unittest discover -s evals/tests -v
   python3 -m py_compile evals/run.py evals/pairmux_proxy.py evals/tests/mock_bin.py
   bash -n evals/lib.sh evals/scenarios/*/setup.sh evals/scenarios/*/check.sh
   shellcheck evals/lib.sh evals/scenarios/*/setup.sh evals/scenarios/*/check.sh
   ./scripts/validate-commit-subjects.sh --self-test
   ```

2. Copy `skills/pairmux/` into `../pairmux/skills/pairmux/`. The canonical and
   embedded directories must be byte-for-byte identical before the CLI release:

   ```sh
   rsync --archive --delete skills/pairmux/ ../pairmux/skills/pairmux/
   diff -ru skills/pairmux ../pairmux/skills/pairmux
   ```

3. Run the pairmux repository tests that cover `pairmux skill install` after
   the sync.
4. Move `ChangeLog.md` entries from `[Unreleased]` into a dated version and add
   comparison links.
5. Merge the release branch into `main`, create an annotated SemVer tag, and
   push both the branch and tag.
6. Verify the public installation path in a clean directory:

   ```sh
   DISABLE_TELEMETRY=1 npx --yes skills add \
     treeleaves30760/pairmux-skills --list
   ```

7. Record model/version evidence in `evals/RESULTS.md` only when the run has
   stable Git provenance and retained artifacts.

Use the same version as the corresponding pairmux CLI release when the skill
changes require new CLI behavior. Documentation-only or eval-only releases may
advance independently, but the changelog must state the compatible CLI range.
