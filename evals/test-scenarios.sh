#!/bin/sh
# Thin POSIX wrapper kept for existing callers. The zero-cost M-suite golden self-test is
# implemented once, cross-platform, in test_scenarios.py (on Windows: python evals\test_scenarios.py).
exec python3 "$(dirname "$0")/test_scenarios.py" "$@"
