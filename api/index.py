import sys
import os
import requests

from flask import Flask, request, jsonify

# Menambahkan parent directory agar bisa mengimpor modul `app` dan `bot`.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Lazy import `bot` & service. `import bot` mengeksekusi kode top-level yang
# dulu memanggil verify_api_key() (network call ke me-crypto.mashu.lol) dan
# melempar SystemExit/ValueError bila env var hilang — di cold-start Vercel itu
# memunculkan halaman FUNCTION_INVOCATION_FAILED dan mematikan /api/cron.
# Kita pindahkan import ke lazy loader + tangkap BaseException agar endpoint
# tetap responsif dan misconfig bisa didiagnosis lewat /api/health.
# ---------------------------------------------------------------------------

_bot_module = None
_bot_import_error = None
_bot_attempted = False


def _get_bot():
    global _bot_module, _bot_import_error, _bot_attempted
    if _bot_attempted:
        return _bot_module, _bot_import_error
    _bot_attempted = True
    try:
        import bot  # noqa: F401
        _bot_module = bot
        _bot_import_error = None
    except BaseException as exc:  # SystemExit juga tertangkap di sini
        _bot_module = None
        _bot_import_error = f"{exc.__class__.__name__}: {exc}"
    return _bot_module, _bot_import_error


_services_loaded = False
_run_auto_renew = None
_load_session_rows = None
_service_import_error = None


def _get_services():
    global _services_loaded, _run_auto_renew, _load_session_rows, _service_import_error
    if _services_loaded:
        return _run_auto_renew, _load_session_rows, _service_import_error
    _services_loaded = True
    try:
        from app.service.auto_renew import run_auto_renew
        from app.service.tg_session import _load_session_rows
        _run_auto_renew = run_auto_renew
        _load_session_rows = _load_session_rows
        _service_import_error = None
    except BaseException as exc:
        _run_auto_renew = None
        _load_session_rows = None
        _service_import_error = f"{exc.__class__.__name__}: {exc}"
    return _run_auto_renew, _load_session_rows, _service_import_error


def _env_summary() -> dict:
    """Status boolean env var yang dibutuhkan — TANPA membocorkan nilainya."""
    keys = [
        "BOT_TOKEN", "API_KEY", "USER_API_KEY", "BASE_API_URL",
        "BASE_CIAM_URL", "BASIC_AUTH", "AX_DEVICE_ID", "AX_FP", "UA",
        "AES_KEY_ASCII", "CRON_SECRET", "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "XDATA_KEY", "X_API_BASE_SECRET",
    ]
    return {k: bool(os.getenv(k)) for k in keys}


def _notify_telegram(chat_id, text: str) -> None:
    """Kirim notifikasi via Telegram API secara mandiri (tidak butuh bot.py)."""
    token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print(f"[auto-refill] BOT_TOKEN belum diset; skip notifikasi chat {chat_id}")
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"[auto-refill] Gagal kirim notifikasi {chat_id}: {exc.__class__.__name__}")


app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Bot is running on Vercel!"})


@app.route('/api/health', methods=['GET'])
def health():
    """Diagnosis lingkungan tanpa auth: status import + boolean env (bukan nilai)."""
    bot, bot_err = _get_bot()
    _, _, svc_err = _get_services()
    return jsonify({
        "ok": True,
        "bot_imported": bot is not None,
        "bot_import_error": bot_err,
        "service_imported": _run_auto_renew is not None,
        "service_import_error": svc_err,
        "env": _env_summary(),
    }), 200


@app.route('/api/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({"status": "ok"}), 200

    bot, bot_err = _get_bot()
    if bot is None:
        return jsonify({"error": "bot unavailable", "detail": bot_err}), 503

    try:
        bot.handle_update(update)
    except Exception as e:
        print(f"Error handling update: {e}")
    return jsonify({"status": "ok"}), 200


@app.route('/api/cron/auto-refill', methods=['GET', 'POST'])
def auto_refill():
    expected = os.getenv("CRON_SECRET")
    supplied = request.headers.get("Authorization", "")
    if not expected or supplied != f"Bearer {expected}":
        return jsonify({"error": "Unauthorized"}), 401

    run_auto_renew, _, svc_err = _get_services()
    if run_auto_renew is None:
        return jsonify({"error": "service unavailable", "detail": svc_err}), 503

    api_key = os.getenv("USER_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        return jsonify({
            "error": "API key tidak tersedia",
            "detail": "Set USER_API_KEY (atau API_KEY) di Vercel env.",
        }), 503

    try:
        results = run_auto_renew(api_key)
        for result in results:
            chat_id = result.get("notify_chat_id")
            if chat_id and result.get("status") in {"purchased", "error"}:
                if result["status"] == "purchased":
                    balance_remaining = result.get("balance_remaining")
                    balance_text = (
                        f"Rp {balance_remaining:,}"
                        if isinstance(balance_remaining, int)
                        else "Tidak tersedia"
                    )
                    text = (
                        f"✅ Auto-renew berhasil untuk {result['number']}\n"
                        f"Paket: {result['package']}\n"
                        f"Harga: Rp {result['price']:,}\n"
                        f"Sisa pulsa: {balance_text}"
                    )
                else:
                    text = f"❌ Auto-renew gagal untuk {result['number']}: {result['error']}"
                _notify_telegram(chat_id, text)
        return jsonify({"status": "ok", "processed": len(results), "results": results}), 200
    except Exception as exc:
        print(f"Auto-refill error: {exc}")
        return jsonify({"error": "Auto-refill failed"}), 500
@app.route('/api/diag/session', methods=['GET'])
def diag_session():
    """Diagnostik persistensi session Telegram (terproteksi CRON_SECRET).

    Hanya mengembalikan metadata non-sensitif; refresh token tidak dibocorkan.
    """
    expected = os.getenv("CRON_SECRET")
    supplied = request.headers.get("Authorization", "")
    if not expected or supplied != f"Bearer {expected}":
        return jsonify({"error": "Unauthorized"}), 401

    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        return jsonify({"supabase_configured": False, "rows": None}), 200

    _, load_session_rows, svc_err = _get_services()
    if load_session_rows is None:
        return jsonify({"error": "service unavailable", "detail": svc_err}), 503

    try:
        rows = load_session_rows(875037027)
    except Exception as exc:
        return jsonify({"error": "session check failed"}), 500

    return jsonify({
        "supabase_configured": True,
        "rows": [
            {
                "number": r.get("number"),
                "active": r.get("active"),
                "has_refresh_token": bool(r.get("refresh_token")),
                "profile_keys": sorted((r.get("profile") or {}).keys()),
            }
            for r in rows
        ],
    }), 200

# Vercel akan membaca variabel `app` ini secara otomatis
