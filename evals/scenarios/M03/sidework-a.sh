#!/usr/bin/env bash
# M03 fixture: reindex twelve shards, including real work during human handoff.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$here/fake-sudo-migrate.sh" --sidework a
