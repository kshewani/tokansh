#!/usr/bin/env bash
# One phase only. Acknowledgement flags do not grant authorization.
# No environment file is sourced; credentials remain in existing MSP directories.
set -Eeuo pipefail
umask 077
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 -B "$HERE/upgrade-workflow.py" "$@"
