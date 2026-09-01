"""
worker.py - Always-on adaptive IG quota polling + auto-renew worker.

Dipakai di Render.com Background Worker (start command: python worker.py).

Loop tak berujung:
  1. Ambil nomor aktif dari Supabase lewat run_auto_renew() (sudah punya lock
     anti double-process, cooldown 30 menit, dan try/except per nomor).
  2. Polling adaptif: 10 menit normal, tapi 3 menit bila ada nomor sehat yang
     sisa kuotanya sudah di bawah WORKER_CRITICAL_MB.
  3. Auto-renew: terjadi saat sisa kuota <= RENEW_THRESHOLD_MB (default 0 =
     perilaku lama, renew hanya saat habis).

Environment variables:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY  (wajib, dipakai oleh auto_renew)
  USER_API_KEY atau API_KEY                 (wajib, API XL)
  WORKER_POLL_NORMAL    default 600   detik (10 menit)
  WORKER_POLL_CRITICAL  default 180   detik (3 menit)
  WORKER_CRITICAL_MB    default 100   MB (ambang polling kritis)
  RENEW_THRESHOLD_MB    default 0     MB (ambang pembelian; >0 = renew sebelum habis)

Flag CLI:
  --once  jalankan satu siklus lalu berhenti (dipakai untuk smoke test).
"""
import os
import sys
import time
import signal
from datetime import datetime, timedelta, timezone

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


def _poll_interval(min_remaining: "int | None") -> int:
    """Return interval polling (detik) berdasarkan sisa kuota terendah."""
    if min_remaining is not None and min_remaining < _critical_bytes():
        return _env_int("WORKER_POLL_CRITICAL", 180)
    return _env_int("WORKER_POLL_NORMAL", 600)


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

    for r in results:
        status = r.get("status")
        if status == "ok":
            ok += 1
            try:
                near.append(int(r.get("remaining", 0) or 0))
            except (TypeError, ValueError):
                pass
        elif status == "purchased":
            purchased += 1
        elif status == "error":
            errored += 1
        else:
            skipped += 1

    min_remaining = min(near) if near else None
    interval = _poll_interval(min_remaining)

    parts = [f"{ok} ok", f"{purchased} renew"]
    if errored:
        parts.append(f"{errored} error")
    if skipped:
        parts.append(f"{skipped} skip")
    detail = f"{total} diproses | " + ", ".join(parts)
    if min_remaining is not None:
        detail += f" | sisa min {min_remaining // (1024 * 1024)} MB"
    else:
        detail += " | tidak ada nomor sehat"
    detail += f" -> interval {interval // 60} m"

    print(f"[{_now()}] [worker] {detail}")
    return interval


def main() -> int:
    api_key = os.getenv("USER_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        print(f"[{_now()}] [worker] USER_API_KEY (atau API_KEY) belum diset. Berhenti.")
        return 1

    if "--once" in sys.argv:
        tick(api_key)
        return 0

    normal = _env_int("WORKER_POLL_NORMAL", 600)
    critical = _env_int("WORKER_POLL_CRITICAL", 180)
    print(
        f"[{_now()}] [worker] IG worker start | polling normal {normal // 60} m,"
        f" kritis {critical // 60} m, ambang {_critical_bytes() // (1024 * 1024)} MB"
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
