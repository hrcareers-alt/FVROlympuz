#!/usr/bin/env bash
# Write the Google service account to a 0600 file for cron, which does not
# inherit the agent environment. Accepts either a JSON file path or raw JSON
# in GOOGLE_APPLICATION_CREDENTIALS. Never prints credential contents.
set -euo pipefail

CRED_DIR="${HOME}/.config/fvrolympuz"
CRED_FILE="${CRED_DIR}/service_account.json"
mkdir -p "${CRED_DIR}"
chmod 700 "${CRED_DIR}"

raw="${GOOGLE_APPLICATION_CREDENTIALS:-}"
if [[ -n "${raw}" && -f "${raw}" ]]; then
  cp "${raw}" "${CRED_FILE}"
elif [[ "${raw}" == \{* ]]; then
  printf '%s\n' "${raw}" > "${CRED_FILE}"
elif [[ ! -s "${CRED_FILE}" ]]; then
  echo "Google service account credentials are missing." >&2
  exit 1
fi

chmod 600 "${CRED_FILE}"
printf '%s\n' "${CRED_FILE}"
