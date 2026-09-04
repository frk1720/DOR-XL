#!/bin/bash
# Rotate DOR-XL worker.log daily at 00:00 WIB (17:00 UTC).
# - Copy current log to worker.log.old (keep last 24h history)
# - Truncate worker.log to zero (keeps inode & fd valid for running worker)
# - Write a start marker with WIB timestamp
#
# Installed at /home/ubuntu/DOR-XL/deploy/OCI/rotate_worker_log.sh
# Triggered by systemd: dor-worker-logrotate.{service,timer}

LOG="/home/ubuntu/DOR-XL/worker.log"
OLD="/home/ubuntu/DOR-XL/worker.log.old"

if [ -f "$LOG" ]; then
  cp "$LOG" "$OLD"
  truncate -s 0 "$LOG"
  echo "[$(TZ=Asia/Jakarta date '+%Y-%m-%d %H:%M:%S %Z')] === NEW 24H LOG CYCLE STARTED ===" >> "$LOG"
fi

exit 0
