#!/bin/bash
# bootstrap_venv.sh — Create venv and install dependencies for UNO-Q Remote Control
#
# Environment constraints on Arduino UNO-Q (Debian 13):
#   - System python is PEP 668 protected: no direct `pip install`
#   - No ensurepip available: can't create venv with built-in pip
#   - No passwordless sudo
#
# Strategy:
#   1. Create empty venv with --without-pip
#   2. Bootstrap pip into venv via curl get-pip.py
#   3. Install dependencies from requirements.txt
#   4. Retry every network-dependent step (phone hotspot is flaky)
#
# Usage:
#   chmod +x scripts/bootstrap_venv.sh
#   ./scripts/bootstrap_venv.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="${PROJECT_DIR}/.venv"
PYTHON="${VENV_DIR}/bin/python"
PIP="${VENV_DIR}/bin/pip"
MAX_RETRIES=5
RETRY_DELAY=5

log()  { echo "[bootstrap] $(date '+%H:%M:%S') $*"; }
retry() {
    local n=1
    local cmd="$*"
    while [ $n -le $MAX_RETRIES ]; do
        log "Attempt $n/$MAX_RETRIES: $cmd"
        if eval "$cmd"; then
            log "SUCCESS on attempt $n"
            return 0
        fi
        if [ $n -lt $MAX_RETRIES ]; then
            log "FAILED — retrying in ${RETRY_DELAY}s..."
            sleep $RETRY_DELAY
        fi
        n=$((n + 1))
    done
    log "FATAL: all $MAX_RETRIES attempts failed for: $cmd"
    return 1
}

# ---------------------------------------------------------------------------
# Step 1: Create empty venv
# ---------------------------------------------------------------------------
log "Step 1/3: Creating venv at ${VENV_DIR} (without pip)..."
if [ -d "${VENV_DIR}" ]; then
    log "venv already exists, removing..."
    rm -rf "${VENV_DIR}"
fi
python3 -m venv --without-pip "${VENV_DIR}"
log "venv created."

# ---------------------------------------------------------------------------
# Step 2: Bootstrap pip via get-pip.py
# ---------------------------------------------------------------------------
log "Step 2/3: Bootstrapping pip into venv..."
GETPIP="${PROJECT_DIR}/.cache/get-pip.py"
mkdir -p "${PROJECT_DIR}/.cache"
retry "curl -sSfL https://bootstrap.pypa.io/get-pip.py -o ${GETPIP}"
"${PYTHON}" "${GETPIP}" --no-cache-dir
log "pip bootstrapped: $(${PIP} --version)"

# ---------------------------------------------------------------------------
# Step 3: Install project dependencies
# ---------------------------------------------------------------------------
log "Step 3/3: Installing dependencies from requirements.txt..."
retry "${PIP} install --no-cache-dir -r ${PROJECT_DIR}/requirements.txt"

log "Dependencies installed:"
"${PIP}" list 2>/dev/null | grep -E 'msgpack|PyYAML' || true

log ""
log "============================================"
log "Bootstrap complete!"
log "Python:  ${PYTHON}"
log "Pip:     ${PIP}"
log "Use:     ${PYTHON} -m backend.web   (example)"
log "============================================"
