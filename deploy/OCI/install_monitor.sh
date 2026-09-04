#!/usr/bin/env bash
# install_monitor.sh - Pasang cron monitor crypto service di VM OCI.
#
# Menjadwalkan monitor_crypto.sh tiap 5 menit. Idempotent: menjalankan ulang
# tidak membuat cron duplikat.
#
# Jalankan di VM:  bash install_monitor.sh
# Bisa di-override: MONITOR_SCRIPT, MONITOR_LOG_DIR

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_SCRIPT="${MONITOR_SCRIPT:-$SCRIPT_DIR/monitor_crypto.sh}"
LOG_DIR="${MONITOR_LOG_DIR:-$HOME/dor-xl/monitor}"

if [ ! -f "$MONITOR_SCRIPT" ]; then
    echo "ERROR: monitor_crypto.sh tidak ditemukan di $MONITOR_SCRIPT" >&2
    exit 1
fi

chmod +x "$MONITOR_SCRIPT" || true
mkdir -p "$LOG_DIR"

# Kron tiap 5 menit; buang baris lama yang menyebut monitor_crypto.sh agar idempotent.
CRON_LINE="*/5 * * * * $MONITOR_SCRIPT >/dev/null 2>&1"
( crontab -l 2>/dev/null | grep -v 'monitor_crypto.sh' ; echo "$CRON_LINE" ) | crontab -

echo "=== Monitor crypto terpasang di VM ==="
echo "Script : $MONITOR_SCRIPT"
echo "Cron   : $CRON_LINE"
echo "Log    : $LOG_DIR/crypto_health.log"
echo "Uji    : $MONITOR_SCRIPT; echo \"exit=$?\""
echo ""
echo "Cek cron: crontab -l"
