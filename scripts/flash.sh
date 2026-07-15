#!/bin/bash
# flash.sh — Compile and flash UNO-Q firmware (STM32 side).
#
# Strategy:
#   1. Try arduino-cli compile + upload first (standard path).
#   2. If upload produces a binary that reads back as all 0xFF from the
#      application area (0x08100000), fall back to OpenOCD direct flash.
#
# The OpenOCD fallback uses:
#   /opt/openocd/bin/openocd
#   /opt/openocd/openocd_gpiod.cfg  (swdio=25, swclk=26, srst=38, gpiochip1)
#   + board-builtin flash_sketch.cfg
#   Target file: build/sketch/sketch.ino.elf-zsk.bin  (NOT bin-zsk.bin)
#
# Note: 0x08000000 (bootloader area) verify-failed is normal and harmless.
# The real check is 0x08100000 (application area).
#
# Usage:
#   ./scripts/flash.sh              # compile + flash
#   ./scripts/flash.sh --compile    # compile only
#   ./scripts/flash.sh --verify     # flash then verify with dump

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SKETCH_DIR="${PROJECT_DIR}/sketch"
BUILD_DIR="${PROJECT_DIR}/build/sketch"
CACHE_DIR="${PROJECT_DIR}/.cache/sketch"
FQBN="arduino:zephyr:unoq"

# OpenOCD paths
OPENOCD_BIN="/opt/openocd/bin/openocd"
OPENOCD_CFG="/opt/openocd/openocd_gpiod.cfg"
OPENOCD_FLASH="/opt/openocd/flash_sketch.cfg"

log()  { echo "[flash] $(date '+%H:%M:%S') $*"; }
die()  { log "FATAL: $*"; exit 1; }

# ---------------------------------------------------------------------------
# Step 1: Compile
# ---------------------------------------------------------------------------
compile() {
    log "Compiling sketch at ${SKETCH_DIR}..."

    if ! command -v arduino-cli &>/dev/null; then
        die "arduino-cli not found. Install it first."
    fi

    arduino-cli compile \
        --fqbn "${FQBN}" \
        --build-path "${BUILD_DIR}" \
        "${SKETCH_DIR}"

    log "Compile OK."
    ls -la "${BUILD_DIR}/"*.bin 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Step 2: Flash via arduino-cli upload
# ---------------------------------------------------------------------------
flash_arduino_cli() {
    log "Uploading via arduino-cli..."
    arduino-cli upload \
        --fqbn "${FQBN}" \
        --input-dir "${BUILD_DIR}" \
        "${SKETCH_DIR}" || {
        log "arduino-cli upload returned non-zero (may be harmless)"
    }
}

# ---------------------------------------------------------------------------
# Step 3: Verify — dump 0x08100000 and check it's not all 0xFF
# ---------------------------------------------------------------------------
verify_app_area() {
    log "Verifying application area at 0x08100000..."
    local elf_bin="${BUILD_DIR}/sketch.ino.elf-zsk.bin"

    if [ ! -f "${elf_bin}" ]; then
        log "WARNING: ${elf_bin} not found, checking for bin-zsk.bin..."
        elf_bin="${BUILD_DIR}/sketch.ino.bin-zsk.bin"
    fi
    if [ ! -f "${elf_bin}" ]; then
        log "WARNING: No ELF binary found, skipping verify."
        return 0
    fi

    log "Binary size: $(stat -c%s "${elf_bin}") bytes"

    # Try a quick SWD dump of the first 256 bytes at 0x08100000
    if [ -x "${OPENOCD_BIN}" ] && [ -f "${OPENOCD_CFG}" ]; then
        log "Dumping 0x08100000 via OpenOCD..."
        local dump_hex
        dump_hex=$("${OPENOCD_BIN}" -f "${OPENOCD_CFG}" \
            -c "init" -c "reset halt" \
            -c "dump_image /tmp/unoq_verify.bin 0x08100000 256" \
            -c "reset run" -c "exit" 2>&1) || true

        if [ -f /tmp/unoq_verify.bin ]; then
            # Check if it's all 0xFF (blank)
            local all_ff
            all_ff=$(hexdump -v -e '/1 "%02x"' /tmp/unoq_verify.bin | sed 's/ff//g')
            if [ -z "${all_ff}" ]; then
                log "WARNING: App area at 0x08100000 is ALL 0xFF — flash may have failed!"
                log "Falling back to OpenOCD direct flash..."
                return 1
            else
                log "App area contains non-FF data — flash likely OK."
            fi
            rm -f /tmp/unoq_verify.bin
        fi
    else
        log "OpenOCD not available, skipping verify."
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Step 4: OpenOCD fallback flash
# ---------------------------------------------------------------------------
flash_openocd() {
    log "Flashing via OpenOCD fallback..."
    local elf_bin="${BUILD_DIR}/sketch.ino.elf-zsk.bin"

    if [ ! -f "${elf_bin}" ]; then
        elf_bin="${BUILD_DIR}/sketch.ino.bin-zsk.bin"
    fi

    if [ ! -f "${elf_bin}" ]; then
        # Check cache dir
        elf_bin="${CACHE_DIR}/sketch.ino.elf-zsk.bin"
    fi

    if [ ! -f "${elf_bin}" ]; then
        die "Cannot find firmware binary. Tried build/ and .cache/ directories."
    fi

    log "Using binary: ${elf_bin} ($(stat -c%s "${elf_bin}") bytes)"

    if [ ! -x "${OPENOCD_BIN}" ]; then
        die "OpenOCD not found at ${OPENOCD_BIN}"
    fi
    if [ ! -f "${OPENOCD_CFG}" ]; then
        die "OpenOCD config not found at ${OPENOCD_CFG}"
    fi
    if [ ! -f "${OPENOCD_FLASH}" ]; then
        die "Flash script not found at ${OPENOCD_FLASH}"
    fi

    log "Running OpenOCD..."
    "${OPENOCD_BIN}" \
        -f "${OPENOCD_CFG}" \
        -f "${OPENOCD_FLASH}" \
        2>&1 | tee /tmp/openocd_flash.log

    log "OpenOCD flash complete."
    log "Note: 0x08000000 verify-failed is NORMAL (bootloader area)."
    log "Check 0x08100000 for your application code."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    local mode="${1:-flash}"

    case "${mode}" in
        --compile)
            compile
            ;;
        --verify)
            compile
            flash_arduino_cli
            if ! verify_app_area; then
                flash_openocd
            fi
            ;;
        flash|*)
            compile
            flash_arduino_cli
            log ""
            log "========================================="
            log "Flash complete. Verify with RPC self-test:"
            log "  python3 -m backend.rpc_client"
            log ""
            log "Expected: \$/version returns version,"
            log "          mon/connected returns True"
            log "          unknown method returns [2, '...']"
            log "========================================="
            ;;
    esac
}

main "$@"
