#!/usr/bin/env bash
# Generic guarded transition. Arguments begin with current version/sequence,
# target version/sequence, followed by one authorized workflow phase.
set -Eeuo pipefail
umask 077
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 -B "$HERE/upgrade-workflow.py" --transition "$@"
