#!/usr/bin/env bash
# Fixed M4.2 transition: 1.1/2 -> 1.2/3. One explicitly authorized phase only.
set -Eeuo pipefail
umask 077
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 -B "$HERE/upgrade-workflow.py" --m42 "$@"
