#!/usr/bin/env bash
# Install the Foundever hourly job.
# The host clock is UTC. Manila is UTC+8 with no daylight saving, and this
# cron does not apply CRON_TZ, so the hours below are UTC:
#   00:09 UTC = 8:09 AM Manila
#   16:09 UTC = 12:09 AM Manila
# 1:09 AM through 7:09 AM Manila (17:09–23:09 UTC) stay outside the window.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="${ROOT}/scripts/run_foundever.sh"
LOG_DIR="${HOME}/.config/fvrolympuz"
mkdir -p "${LOG_DIR}"
chmod 700 "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/foundever_automation.log"
touch "${LOG_FILE}"
chmod 600 "${LOG_FILE}"

crontab - <<EOF
9 0-16 * * * ${RUNNER} >> ${LOG_FILE} 2>&1
EOF

echo "Installed Foundever cron for 8:09 AM through 12:09 AM Manila (UTC hours 0-16, minute 09)."
crontab -l
