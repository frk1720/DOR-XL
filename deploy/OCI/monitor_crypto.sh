#!/usr/bin/env bash
# monitor_crypto.sh - Pantau ketersediaan crypto service me-crypto.mashu.lol
#
# Dipakai di VM OCI (129.225.2.6) untuk mendeteksi kapan service pulih.
# nslookup TIDAK terpasang di VM, jadi kita pakai python3 socket + urllib
# (stdlib, tidak butuh dependency tambahan).
#
# Perilaku:
#   - Baris status ber-timestamp di-append ke log.
#   - echo ke stdout (kron mengirim stdout ke mail bila dijadwalkan via cron).
#   - exit 0 jika UP, exit 1 jika DOWN.
#   - Opsional: kirim pesan Telegram saat transisi DOWN -> UP (pakai env
#     TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).
#
# Variabel env yang bisa di-set:
#   MONITOR_LOG_DIR   default $HOME/dor-xl/monitor
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   untuk notifikasi pulih (opsional)

set -u

DOMAIN="me-crypto.mashu.lol"
BASE="https://me-crypto.mashu.lol"
URL_PATH="/api/890/encryptsign"   # endpoint yang paling sering dipakai worker
LOG_DIR="${MONITOR_LOG_DIR:-$HOME/dor-xl/monitor}"
LOG_FILE="$LOG_DIR/crypto_health.log"
STATE_FILE="$LOG_DIR/.crypto_state"
PY="python3"
# Token & chat id dibaca dari env bila ada (tidak di-hardcode)
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

mkdir -p "$LOG_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }

# --- DNS check -------------------------------------------------------------
DNS="DOWN"
DNS_IP=""
DNS_IP=$("$PY" -c "import socket,sys
try:
    print(socket.gethostbyname('$DOMAIN'))
except Exception:
    sys.exit(1)" 2>/dev/null)
[ -n "$DNS_IP" ] && DNS="UP"

# --- HTTP reachability -------------------------------------------------------
# Server yang hidup (walaupun balas 4xx/5xx) berarti "UP": kita hanya mau tahu
# apakah host-nya menjawab / DNS-nya resolve lagi.
HTTP="DOWN"
HTTP_CODE=""
HTTP_CODE=$("$PY" -c "import urllib.request,sys
try:
    r=urllib.request.urlopen('$BASE$URL_PATH', timeout=15)
    print(r.status)
except Exception:
    sys.exit(1)" 2>/dev/null)
[ -n "$HTTP_CODE" ] && HTTP="UP"

# --- aggregate --------------------------------------------------------------
STATUS="UP"
if [ "$DNS" != "UP" ] || [ "$HTTP" != "UP" ]; then
    STATUS="DOWN"
fi

LINE="$(ts) status=$STATUS dns=$DNS(${DNS_IP:-none}) http=$HTTP(${HTTP_CODE:-none})"
echo "$LINE" | tee -a "$LOG_FILE"

# Jaga ukuran log (simpan ~2000 baris terakhir)
tail -n 2000 "$LOG_FILE" > "$LOG_FILE.tmp" 2>/dev/null && mv "$LOG_FILE.tmp" "$LOG_FILE"

# --- notifikasi transisi DOWN -> UP -----------------------------------------
PREV=""
[ -f "$STATE_FILE" ] && PREV="$(cat "$STATE_FILE" 2>/dev/null)"
if [ "$STATUS" != "$PREV" ]; then
    echo "$STATUS" > "$STATE_FILE"
    if [ "$STATUS" = "UP" ] && [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        MSG="[DOR-XL] Crypto service ${DOMAIN} PULIH (dns=${DNS_IP:-?}, http=${HTTP_CODE:-?})"
        TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" TELEGRAM_CHAT_ID="$TELEGRAM_CHAT_ID" MSG="$MSG" \
            "$PY" -c "import os,urllib.request,urllib.parse
tok=os.environ['TELEGRAM_BOT_TOKEN']; cid=os.environ['TELEGRAM_CHAT_ID']
text=os.environ.get('MSG','')
data=urllib.parse.urlencode({'chat_id':cid,'text':text}).encode()
req=urllib.request.Request('https://api.telegram.org/bot'+tok+'/sendMessage', data=data)
urllib.request.urlopen(req, timeout=10)" >/dev/null 2>&1 || true
    fi
fi

[ "$STATUS" = "UP" ] && exit 0 || exit 1
