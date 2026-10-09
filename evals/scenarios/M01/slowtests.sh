#!/usr/bin/env bash
# M01 fixture: 42 real checks across 18 batches; a live readiness checkpoint.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -I "$here/bigserver.py" --suite
