#!/usr/bin/env bash
# Run foundever_automation.py with the prepared service-account file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="${HOME}/.venvs/fvrolympuz/bin/python"
if [[ ! -x "${VENV_PY}" ]]; then
  echo "Python environment is missing at ${VENV_PY}." >&2
  exit 1
fi

CRED_FILE="$(bash "${ROOT}/scripts/prepare_credentials.sh")"
export GOOGLE_APPLICATION_CREDENTIALS="${CRED_FILE}"
cd "${ROOT}"
exec "${VENV_PY}" foundever_automation.py
