#!/bin/bash
set -euo pipefail

python3 -m cnc_control.selftest.cli "$@"

