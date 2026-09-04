#!/usr/bin/env bash
# install_worker_service.sh - Deteksi repo, lalu tulis unit systemd dor-worker.
#
# Ditulis agar TIDAK langsung mengaktifkan service. Setelah crypto service
# pulih (`worker.py --once` = 1 ok), jalankan:
#     sudo systemctl enable --now dor-worker.service
#
# Override via env:
#   REPO_DIR     path repo berisi worker.py (auto-detect bila kosong)
#   PYTHON_BIN   path peluncur python (auto-detect .venv bila kosong)
#   WORKER_NAME  nama unit (default dor-worker)
#
# Jalankan di VM:  bash install_worker_service.sh
# Butuh sudo untuk menulis ke /etc/systemd/system.

set -e

REPO_DIR="${REPO_DIR:-}"
PYTHON_BIN="${PYTHON_BIN:-}"
WORKER_NAME="${WORKER_NAME:-dor-worker}"

auto_detect() {
    for d in "$HOME/DOR XL" "$HOME/DOR-XL" "$HOME/dor-xl" "$HOME/dor_xl" "$HOME/DOR-XL" "$HOME/DOR_XL"; do
        if [ -f "$d/worker.py" ]; then
            printf '%s' "$d"
            return 0
        fi
    done
    return 0
}

if [ -z "$REPO_DIR" ]; then
    REPO_DIR="$(auto_detect)"
fi

if [ -z "$REPO_DIR" ] || [ ! -f "$REPO_DIR/worker.py" ]; then
    echo "ERROR: worker.py tidak ditemukan. Set REPO_DIR=/path/ke/repo" >&2
    echo "Contoh: REPO_DIR=/home/ubuntu/DOR\\ XL bash install_worker_service.sh" >&2
    exit 1
fi

ENV_FILE="$REPO_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env tidak ditemukan di $REPO_DIR" >&2
    echo "Pastikan SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, API_KEY, AES_KEY_ASCII, AX_FP_KEY, BASE_API_URL, UA ada di .env." >&2
    exit 1
fi

if [ -z "$PYTHON_BIN" ]; then
    if [ -x "$REPO_DIR/.venv/bin/python" ]; then
        PYTHON_BIN="$REPO_DIR/.venv/bin/python"
    elif [ -x "/usr/bin/python3" ]; then
        PYTHON_BIN="/usr/bin/python3"
    else
        echo "ERROR: python tidak ditemukan. Set PYTHON_BIN=/path/ke/python" >&2
        exit 1
    fi
fi

UNIT="/etc/systemd/system/${WORKER_NAME}.service"

# Substitusi template -> unit final.
sed -e "s|@REPO_DIR@|$REPO_DIR|g" \
    -e "s|@PYTHON@|$PYTHON_BIN|g" \
    -e "s|@ENV_FILE@|$ENV_FILE|g" \
    "$(dirname "${BASH_SOURCE[0]}")/dor-worker.service.template" | sudo tee "$UNIT" >/dev/null

sudo systemctl daemon-reload

echo "=== Unit $WORKER_NAME dibuat ==="
echo "Repo    : $REPO_DIR"
echo "Python  : $PYTHON_BIN"
echo "Env     : $ENV_FILE"
echo "Unit    : $UNIT"
echo ""
echo "Langkah berikutnya (hanya saat crypto service sudah pulih):"
echo "  1) Uji dulu satu siklus:  cd \"$REPO_DIR\" && .venv/bin/python worker.py --once"
echo "     -> target log '1 ok' / '0 error'."
echo "  2) Aktifkan:  sudo systemctl enable --now $WORKER_NAME"
echo "  3) Cek:       systemctl status $WORKER_NAME; journalctl -u $WORKER_NAME -f"
