#!/usr/bin/env bash
# M03 fixture: compact twelve event batches while the migration is handed off.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$here/fake-sudo-migrate.sh" --sidework b
