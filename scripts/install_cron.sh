#!/usr/bin/env bash
# Install the Foundever hourly job.
# Manila time (Asia/Manila, UTC+8): minute 09, from 8:09 AM through 12:09 AM.
# 1:09 AM through 7:09 AM are outside the window.
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
CRON_TZ=Asia/Manila
9 0,8-23 * * * ${RUNNER} >> ${LOG_FILE} 2>&1
EOF

echo "Installed Foundever cron for Asia/Manila hours 0,8-23 at minute 09."
crontab -l
