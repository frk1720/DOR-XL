"""
worker.py - Always-on adaptive IG quota polling + auto-renew worker.

Dijalankan di VPS Oracle Cloud (OCI Always Free, Ubuntu, /home/ubuntu/DOR-XL)
via systemd (dor-worker.service, Restart=always). Perintah manual: python worker.py

Loop tak berujung:
  1. Ambil nomor aktif dari Supabase lewat run_auto_renew() (sudah punya lock
     anti double-process, cooldown 30 menit, dan try/except per nomor).
  2. Polling adaptif + jitter acak (mode stealth anti-bot):
       - Normal   : WORKER_POLL_NORMAL detik (default 600); bila <= 60 maka
                    dipakai jitter acak 28-35s.
       - Kritis   : WORKER_POLL_CRITICAL detik (default 180); bila <= 30 maka
                    dipakai jitter acak 13-18s. Kritis = ada nomor sehat dengan
                    sisa kuota < WORKER_CRITICAL_MB.
       - Dini hari (02:00-06:00 WIB): polling dilambatkan ke 300-420s (5-7 mnt)
         selama kuota aman, untuk memutus pola request 24 jam non-stop. Bila
         kuota kritis, interval tetap gesit agar auto-renew tidak telat.
  3. Auto-renew: terjadi saat sisa kuota <= RENEW_THRESHOLD_MB (default 0 =
     perilaku lama, renew hanya saat habis).
  4. Staggering antar akun: jeda acak 1.5-3.0s di run_auto_renew agar tidak
     terjadi burst request serempak ke API XL.

Environment variables:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY  (wajib, dipakai oleh auto_renew)
  USER_API_KEY atau API_KEY                 (wajib, API XL)
  WORKER_POLL_NORMAL    default 600   detik (normal; <=60 -> jitter 28-35s)
  WORKER_POLL_CRITICAL  default 180   detik (kritis; <=30 -> jitter 13-18s)
  WORKER_CRITICAL_MB    default 100   MB (ambang polling kritis)
  RENEW_THRESHOLD_MB    default 0     MB (ambang pembelian; >0 = renew sebelum habis)

Flag CLI:
  --once  jalankan satu siklus lalu berhenti (dipakai untuk smoke test).
  --help  tampilkan bantuan ini lalu keluar (dipakai untuk cek penggunaan).
"""
import os
import random
import sys
import time
import signal
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

WIB = timezone(timedelta(hours=7))


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _critical_bytes() -> int:
    mb = _env_int("WORKER_CRITICAL_MB", 100)
    return max(0, mb * 1024 * 1024)


def _now() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")


def _notify_telegram(chat_id, text: str) -> None:
    """Kirim notifikasi via Telegram API. Gagal-notif tidak boleh mematikan worker."""
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if not token:
        print(f"[{_now()}] [worker] TELEGRAM_BOT_TOKEN belum diset; skip notifikasi")
        return
    if not chat_id:
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=30)
        # Jika gagal parsing HTML (biasanya 400 Bad Request karena karakter < atau > di error)
        if resp.status_code == 400 and "parse_mode" in payload:
            payload.pop("parse_mode")
            resp = requests.post(url, json=payload, timeout=30)
            
        resp.raise_for_status()
        print(f"[{_now()}] [worker] Notifikasi terkirim ke chat {chat_id}")
    except Exception as exc:
        # Ekstrak detail error dari response jika ada, tanpa membocorkan token
        err_msg = str(exc)
        if hasattr(exc, 'response') and exc.response is not None:
            err_msg = f"{exc.response.status_code} - {exc.response.text}"
        print(f"[{_now()}] [worker] Gagal kirim notifikasi ke {chat_id}: {err_msg}")


_service = None
_service_error = None


def _get_run_auto_renew():
    """Import run_auto_renew secara lazy; retry setiap siklus bila gagal."""
    global _service, _service_error
    if _service is not None:
        return _service
    try:
        from app.service.auto_renew import run_auto_renew
        _service = run_auto_renew
        _service_error = None
    except BaseException as exc:  # SystemExit / ImportError tertangkap di sini
        _service = None
        _service_error = f"{exc.__class__.__name__}: {exc}"
    return _service


def _is_sleep_hours(wib_now=None) -> bool:
    """Deteksi jam dini hari (02:00 s.d. 06:00 WIB) untuk sleep mode otomatis.

    Memutus pola request 24 jam non-stop agar IP VPS tidak terlihat seperti
    background scraper oleh WAF XL.
    """
    wib_now = wib_now or datetime.now(WIB)
    hour = wib_now.hour
    return 2 <= hour < 6


def _sleep_hours_interval(min_remaining: "int | None") -> int:
    """Interval saat dini hari. Lambat (5-7 menit) bila kuota aman.

    Bila kuota kritis (< WORKER_CRITICAL_MB), tetap pakai interval kritis
    agar auto-renew tidak telat, karena memutus sambungan saat tidur = pulsa
    hangus percuma.
    """
    if min_remaining is not None and min_remaining < _critical_bytes():
        # Tetap gesit walau dini hari: kuota menipis butuh respon cepat.
        base = _env_int("WORKER_POLL_CRITICAL", 180)
        if base <= 30:
            return random.randint(13, 18)
        return random.randint(base - 2, base + 3)
    return random.randint(300, 420)


def _sleep_seconds(min_remaining: "int | None", interval: int) -> int:
    """Terapkan sleep-mode dini hari bila sedang jam 02:00-06:00 WIB."""
    if _is_sleep_hours():
        slowed = _sleep_hours_interval(min_remaining)
        if slowed > interval:
            print(
                f"[{_now()}] [worker] Dini hari terdeteksi: perlambat polling"
                f" {interval}s -> {slowed}s (mode tidur, putus pola 24 jam)"
            )
            return slowed
    return interval


def _poll_interval(min_remaining: "int | None") -> int:
    """Return interval polling (detik) berdasarkan sisa kuota terendah + jitter."""
    if min_remaining is not None and min_remaining < _critical_bytes():
        # KRITIS (< ambang): polling gesit 13-18 detik (acak) untuk tangkap
        # pembaruan kuota secepat mungkin saat download 5G agresif.
        base = _env_int("WORKER_POLL_CRITICAL", 180)
        if base <= 30:
            return random.randint(13, 18)
        return random.randint(base - 2, base + 3)

    # NORMAL (>= ambang): polling tenang + jitter natural (anti-bot pattern)
    base = _env_int("WORKER_POLL_NORMAL", 600)
    if base <= 60:
        return random.randint(28, 35)
    return random.randint(max(0, base - 30), base + 60)


def tick(api_key: str) -> int:
    """Jalankan satu siklus auto-renew dan return interval tidur berikutnya."""
    normal = _env_int("WORKER_POLL_NORMAL", 600)
    run_auto_renew = _get_run_auto_renew()
    if run_auto_renew is None:
        print(f"[{_now()}] [worker] Service auto_renew tidak tersedia: {_service_error}")
        return normal

    try:
        results = run_auto_renew(api_key) or []
    except BaseException as exc:
        # Jangan pernah mematikan loop karena satu siklus gagal.
        print(f"[{_now()}] [worker] Siklus gagal ({exc.__class__.__name__}): {exc}")
        return normal

    total = len(results)
    ok = purchased = errored = skipped = 0
    near: list[int] = []
    quota_details: list[tuple[str, int]] = []
    error_details: list[str] = []
    skip_details: list[str] = []

    for r in results:
        status = r.get("status")
        chat_id = r.get("notify_chat_id")

        if status == "ok":
            ok += 1
            try:
                rem_bytes = int(r.get("remaining", 0) or 0)
                near.append(rem_bytes)
                rem_mb = rem_bytes // (1024 * 1024)
                quota_details.append((str(r.get("number")), rem_mb))
            except (TypeError, ValueError):
                pass
        elif status == "purchased":
            purchased += 1
            if chat_id:
                balance_remaining = r.get("balance_remaining")
                balance_text = f"Rp {balance_remaining:,}" if isinstance(balance_remaining, int) else "Tidak tersedia"
                text = (
                    f"✅ Auto-renew berhasil untuk {r.get('number')}\n"
                    f"Paket: {r.get('package')}\n"
                    f"Harga: Rp {r.get('price', 0):,}\n"
                    f"Sisa pulsa: {balance_text}"
                )
                _notify_telegram(chat_id, text)
        elif status == "error":
            errored += 1
            num = r.get("number") or "?"
            err = str(r.get("error") or "").strip()
            error_details.append(f"{num}: {err}" if err else num)
            # Hanya teror Telegram kalau pembelian paket benar-benar dicoba
            # (kuota <= threshold) dan gagal. Error polling rutin cukup di log
            # dan Supabase last_error.
            if chat_id and r.get("purchase_attempted"):
                text = f"❌ Auto-renew gagal untuk {r.get('number')}: {r.get('error')}"
                _notify_telegram(chat_id, text)
        else:
            skipped += 1
            num = r.get("number") or "?"
            st = r.get("status")
            if st == "quota_unavailable":
                skip_details.append(f"{num}: paket induk Xtra Combo Plus 3GB tidak tersedia")
            elif st == "purchase_cooldown":
                cd = r.get("cooldown_remaining")
                if isinstance(cd, (int, float)) and cd > 0:
                    skip_details.append(f"{num}: cooldown pembelian {int(cd)}s tersisa")
                else:
                    skip_details.append(f"{num}: cooldown pembelian")
            else:
                skip_details.append(f"{num}: status {st!r} tidak dikenal")

    min_remaining = min(near) if near else None
    interval = _poll_interval(min_remaining)
    interval = _sleep_seconds(min_remaining, interval)

    parts = [f"{ok} ok", f"{purchased} renew"]
    if errored:
        parts.append(f"{errored} error")
    if skipped:
        parts.append(f"{skipped} skip")
    detail = f"{total} diproses | " + ", ".join(parts)
    if skip_details:
        detail += " | skip: " + "; ".join(skip_details)
    if error_details:
        detail += " | error: " + "; ".join(error_details)

    min_mb = min_remaining // (1024 * 1024) if min_remaining is not None else None
    if min_mb is not None:
        detail += f" (min {min_mb} MB)"
    detail += f" -> tidur {interval}s"

    print(f"[{_now()}] [worker] {detail}")

    if quota_details:
        for i, (num, mb) in enumerate(quota_details):
            prefix = "  └─" if i == len(quota_details) - 1 else "  ├─"
            print(f"{prefix} {num} : {mb} MB")

    return interval


USAGE = """\
DOR-XL Auto-Renew IG Worker (always-on polling + auto-refill)

Usage:
  python worker.py [--once] [--help]

Options:
  --once      Jalankan satu siklus auto-renew lalu berhenti (smoke test).
  -h, --help  Tampilkan bantuan ini lalu keluar.
"""


def main() -> int:
    # --help / -h harus keluar bersih SEBELUM cek api_key / masuk loop,
    # supaya perintah bantu tidak tanpa sengaja menjalankan worker penuh.
    if "--help" in sys.argv or "-h" in sys.argv:
        print(USAGE)
        return 0

    api_key = os.getenv("USER_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        print(f"[{_now()}] [worker] USER_API_KEY (atau API_KEY) belum diset. Berhenti.")
        return 1

    if "--once" in sys.argv:
        tick(api_key)
        return 0

    normal = _env_int("WORKER_POLL_NORMAL", 600)
    critical = _env_int("WORKER_POLL_CRITICAL", 180)
    # Mode stealth: saat interval <= 60s, worker memakai jitter acak natural
    # (normal 28-35s, kritis 13-18s) agar tidak terlihat seperti bot statis.
    normal_desc = "28-35s (jitter)" if normal <= 60 else f"{max(0, normal - 30)}-{normal + 60}s"
    critical_desc = "13-18s (jitter)" if critical <= 30 else f"{critical - 2}-{critical + 3}s"
    print(
        f"[{_now()}] [worker] IG worker start | polling normal {normal_desc},"
        f" kritis {critical_desc}, ambang kritis {_critical_bytes() // (1024 * 1024)} MB,"
        f" sleep dini hari 02:00-06:00 WIB aktif"
    )

    stop = False

    def _stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    interval = normal
    while not stop:
        try:
            interval = tick(api_key)
        except BaseException as exc:
            print(f"[{_now()}] [worker] Error tak terduga ({exc.__class__.__name__}): {exc}")
        if stop:
            break
        time.sleep(interval)

    print(f"[{_now()}] [worker] Diminta berhenti.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
