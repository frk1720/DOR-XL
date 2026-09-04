#!/usr/bin/env bash
# smoke_worker.sh - Jalankan satu siklus worker (worker.py --once) dan rapi.
#
# Dipakai untuk mengetes kapan crypto service pulih: selama masih DOWN, log
# akan keluar "... 1 error ...". Begitu pulih, log menjadi "... 1 ok ...".
#
# Variabel env:
#   REPO_DIR      path repo (auto-detect dari lokasi skrip ini bila kosong)
#   PYTHON_BIN    path peluncur python (default: $REPO_DIR/.venv/bin/python)
#
# Jalankan di VM:  bash smoke_worker.sh
# (bisa dijadwalkan setiap beberapa jam lewat cron bila diinginkan)

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Deteksi repo berisi worker.py. Prioritas:
#   1. $REPO_DIR  (eksplisit)
#   2. kandidat path umum di $HOME
#   3. repo root (folder deploy/OCI diasumsikan di dalam repo)
REPO_DIR="${REPO_DIR:-}"
if [ -z "$REPO_DIR" ]; then
    for d in \
        "$HOME/DOR XL" "$HOME/DOR-XL" "$HOME/dor-xl" "$HOME/dor_xl" "$HOME/DOR_XL" \
        "$(cd "$SELF_DIR/../.." && pwd 2>/dev/null)"; do
        if [ -f "$d/worker.py" ]; then
            REPO_DIR="$d"
            break
        fi
    done
fi

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"

if [ -z "$REPO_DIR" ] || [ ! -f "$REPO_DIR/worker.py" ]; then
    echo "ERROR: worker.py tidak ditemukan. Set REPO_DIR=/path/ke/repo" >&2
    exit 2
fi
if [ ! -x "$PYTHON_BIN" ]; then
    echo "ERROR: python tidak ditemukan di $PYTHON_BIN (set PYTHON_BIN)" >&2
    exit 2
fi

echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] Smoke test worker (--once) ==="
echo "Repo  : $REPO_DIR"
echo "Python: $PYTHON_BIN"
echo ""

cd "$REPO_DIR"
"$PYTHON_BIN" worker.py --once
rc=$?

echo ""
echo "=== exit code = $rc ==="
echo "Lihat kolom last_error / last_status di Supabase (auto_renew_accounts) bila ada 'error'."
exit $rc
