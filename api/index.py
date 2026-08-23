from flask import Flask, request, jsonify
import sys
import os

# Menambahkan parent directory agar bisa mengimpor bot.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot
from app.service.auto_renew import run_auto_renew
from app.service.tg_session import _load_session_rows

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Bot is running on Vercel!"})

@app.route('/api/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if update:
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

    try:
        results = run_auto_renew(bot.API_KEY)
        for result in results:
            chat_id = result.get("notify_chat_id")
            if chat_id and result.get("status") in {"purchased", "error"}:
                try:
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
                    bot.send_message(chat_id, text)
                except Exception as notify_error:
                    print(f"Notification error for {result.get('number')}: {notify_error}")
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

    rows = _load_session_rows(875037027)
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
