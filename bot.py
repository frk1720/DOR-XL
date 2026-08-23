"""Telegram bot for me-cli.

Jalankan dengan:  python bot.py
Membutuhkan BOT_TOKEN di file .env (dapatkan dari @BotFather).
"""

import calendar
import os
import re
import time
import requests
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    raise SystemExit(
        "BOT_TOKEN tidak ditemukan di .env. "
        "Buat bot di @BotFather lalu tambahkan BOT_TOKEN=<token> ke .env"
    )

# API_KEY di .env adalah static app key (dipakai encrypt.py/engsel.py untuk
# header x-api-key). Wajib ada, tapi BUKAN key yang dipakai untuk signature.
if not os.getenv("API_KEY"):
    raise SystemExit("API_KEY tidak ditemukan di .env")

# Import setelah load_dotenv agar env vars (BASE_API_URL dll) terbaca.
from app.client.ciam import get_otp, submit_otp, validate_contact
from app.client.engsel import (
    get_balance,
    get_family,
    get_package,
    get_tiering_info,
    get_transaction_history,
    dashboard_segments,
    send_api_request,
)
from app.client.famplan import get_family_data, validate_msisdn
from app.client.circle import (
    get_group_data,
    get_group_members,
    spending_tracker,
)
from app.client.encrypt import decrypt_circle_msisdn
from app.service.tg_session import init_tg_sessions
from app.service.auto_renew import SupabaseStore

from app.util import load_api_key, verify_api_key
from app.client.purchase.balance import settlement_balance
from app.client.purchase.qris import show_qris_payment
from app.client.purchase.ewallet import settlement_multipayment
from app.type_dict import PaymentItem

# API key milik user (dari @fykxt_bot) yang dipakai untuk signature/encrypt
# lewat crypto service. Disimpan di file api.key (sama seperti CLI).
API_KEY = load_api_key()
if not API_KEY or not verify_api_key(API_KEY):
    raise SystemExit(
        "API key tidak ditemukan atau tidak valid.\n"
        "Dapatkan dari bot @fykxt_bot (kirim /viewkey), lalu simpan ke file\n"
        "'api.key' di folder ini. Atau jalankan 'python main.py' sekali."
    )

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

sessions = init_tg_sessions(API_KEY)

# Global store for long callback data
import uuid
CALLBACK_STORE = {}

def get_short_id(data: str) -> str:
    short_id = str(uuid.uuid4())[:8]
    CALLBACK_STORE[short_id] = data
    return short_id

# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------


def tg_api(method: str, payload: dict) -> dict:
    resp = requests.post(f"{BASE_URL}/{method}", json=payload, timeout=45)
    return resp.json()


def send_message(chat_id: int, text: str, parse_mode: str = "HTML", reply_markup: dict = None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    tg_api("sendMessage", payload)

MAIN_MENU = {
    "keyboard": [
        ["👤 Akun", "📊 Informasi"],
        ["📦 Paket", "🧾 Riwayat"],
        ["🔎 Cari Paket", "⚙️ Bantuan"],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}
ACCOUNT_MENU = {
    "keyboard": [
        ["🔐 Login", "💰 Status"],
        ["📋 Akun Tersimpan", "🔄 Ganti Akun"],
        ["🚪 Logout", "⬅️ Menu Utama"],
    ],
    "resize_keyboard": True,
}
INFO_MENU = {
    "keyboard": [
        ["📦 Paket Aktif", "🧾 Riwayat XL"],
        ["📊 Auto-renew", "🔔 Notifikasi"],
        ["👨‍👩‍👧 Family Plan", "⭕ Circle"],
        ["⬅️ Menu Utama"],
    ],
    "resize_keyboard": True,
}
PACKAGE_MENU = {
    "keyboard": [
        ["🔥 Paket Hot", "📁 Family Code"],
        ["🔑 Option Code", "✅ Validasi Nomor"],
        ["⬅️ Menu Utama"],
    ],
    "resize_keyboard": True,
}


def _show_menu(chat_id: int, text: str, keyboard: dict = MAIN_MENU):
    send_message(chat_id, text, reply_markup=keyboard)


def _ask_menu_input(chat_id: int, uid: int, action: str, prompt: str):
    sessions.get_session(uid)["pending_action"] = action
    send_message(chat_id, prompt, reply_markup=MAIN_MENU)



def _run_menu_handler(chat_id: int, uid: int, handler):
    try:
        handler(chat_id, uid, "")
    except Exception as exc:
        print(f"Menu handler error: {exc.__class__.__name__}")
        send_message(chat_id, "Terjadi kesalahan. Coba lagi nanti.", reply_markup=MAIN_MENU)
def _run_menu_handler_with_args(chat_id: int, uid: int, handler, args: str):
    try:
        handler(chat_id, uid, args)
    except Exception as exc:
        print(f"Menu input error: {exc.__class__.__name__}")
        send_message(chat_id, "Terjadi kesalahan. Coba lagi nanti.", reply_markup=MAIN_MENU)



# ---------------------------------------------------------------------------
# Bot commands
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "<b>me-cli Bot</b>\n\n"
    "<b>Akun</b>\n"
    "/login &lt;nomor&gt; — Login dengan nomor XL (contoh: /login 6281234567890)\n"
    "/status — Cek saldo &amp; info akun\n"
    "/accounts — Lihat semua akun tersimpan\n"
    "/switch &lt;nomor&gt; — Ganti akun aktif\n"
    "/logout [nomor] — Keluar dari akun\n\n"
    "<b>Info</b>\n"
    "/paket — Lihat paket aktif\n"
    "/riwayat — Riwayat transaksi XL\n"
    "/auto_riwayat [YYYY-MM] — Ringkasan pembelian auto-renew\n"
    "/notifikasi — Notifikasi terbaru\n"
    "/family — Info Family Plan/Akrab\n"
    "/circle — Info Circle\n\n"
    "<b>Pencarian Paket</b>\n"
    "/hot — Lihat paket 🔥 HOT 🔥\n"
    "/familycode &lt;kode&gt; — Lihat paket berdasarkan family code\n"
    "/optioncode &lt;kode&gt; — Detail paket berdasarkan option code\n"
    "/validate &lt;nomor&gt; — Validasi nomor msisdn\n\n"
    "/help — Tampilkan pesan ini"
)


def _need_login(chat_id: int, uid: int):
    """Return tokens jika user login, selain itu kirim pesan & return None."""
    tokens = sessions.get_tokens(uid)
    if not tokens:
        hint = ""
        if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
            hint = (
                "\n\nℹ️ Supabase session persistence belum aktif di server; "
                "pastikan SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY terset."
            )
        send_message(chat_id, "Anda belum login. Gunakan /login &lt;nomor&gt;." + hint)
        return None
    return tokens


def _fmt_quota(b) -> str:
    try:
        b = int(b)
    except (TypeError, ValueError):
        return str(b)
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.2f} GB"
    if b >= 1024 ** 2:
        return f"{b / 1024 ** 2:.2f} MB"
    if b >= 1024:
        return f"{b / 1024:.2f} KB"
    return f"{b} B"


def cmd_start(chat_id: int, _uid: int, _args: str):
    _show_menu(chat_id, "<b>me-cli Bot</b>\nPilih layanan dari menu di bawah.")


def cmd_help(chat_id: int, _uid: int, _args: str):
    _show_menu(chat_id, HELP_TEXT)


def cmd_login(chat_id: int, uid: int, args: str):
    contact = args.strip()
    if not contact:
        send_message(chat_id, "Gunakan: /login &lt;nomor&gt;\nContoh: /login 6281234567890")
        return

    if not validate_contact(contact):
        send_message(chat_id, "Nomor tidak valid. Harus diawali 628 dan maksimal 14 digit.")
        return

    try:
        subscriber_id = get_otp(contact)
    except RuntimeError as exc:
        print(f"[OTP] {exc}")
        send_message(chat_id, f"Gagal mengirim OTP: {exc}")
        return
    if not subscriber_id:
        send_message(chat_id, "Gagal mengirim OTP. Coba lagi nanti.")
        return

    sess = sessions.get_session(uid)
    sess["pending_contact"] = contact
    send_message(
        chat_id,
        f"OTP telah dikirim ke <b>{contact}</b>.\n"
        "Balas dengan kode OTP 6 digit.",
    )


def handle_otp(chat_id: int, uid: int, code: str) -> bool:
    """Proses pesan yang tampak seperti kode OTP. Return True jika ditangani."""
    sess = sessions.get_session(uid)
    contact = sess.get("pending_contact")
    if not contact:
        return False
    if not re.fullmatch(r"\d{6}", code):
        return False

    tokens = submit_otp(API_KEY, "SMS", contact, code)
    if not tokens:
        send_message(chat_id, "OTP salah atau kedaluwarsa. Coba /login lagi.")
        sess["pending_contact"] = None
        return True

    sessions.login(uid, tokens, contact)
    sess["pending_contact"] = None

    profile = sessions.get_profile_info(uid) or {}
    number = profile.get("number", contact)
    send_message(chat_id, f"✅ Login berhasil untuk <b>{number}</b>!")
    return True


def cmd_logout(chat_id: int, uid: int, args: str):
    num = args.strip()
    if sessions.logout(uid, num):
        if num:
            send_message(chat_id, f"Nomor {num} berhasil dihapus dari perangkat ini.")
        else:
            send_message(chat_id, "Akun yang aktif berhasil dihapus dari perangkat ini.")
    else:
        send_message(chat_id, "Gagal logout. Nomor tidak ditemukan di perangkat ini.")

def cmd_accounts(chat_id: int, uid: int, _args: str):
    accounts = sessions.get_all_accounts(uid)
    if not accounts:
        send_message(chat_id, "Belum ada akun yang tersimpan. Gunakan /login &lt;nomor&gt;.")
        return
        
    sess = sessions.get_session(uid)
    active = sess.get("active_number")
    
    lines = ["<b>Daftar Akun Tersimpan:</b>\n"]
    for i, (num, acc) in enumerate(accounts.items(), 1):
        sub = acc.get("profile", {}).get("subscription_type", "-")
        mark = "✅" if num == active else ""
        lines.append(f"{i}. {num} ({sub}) {mark}")
        
    lines.append("\nGanti akun dengan: /switch &lt;nomor&gt;")
    send_message(chat_id, "\n".join(lines))

def cmd_switch(chat_id: int, uid: int, args: str):
    num = args.strip()
    if not num:
        send_message(chat_id, "Gunakan: /switch &lt;nomor&gt;")
        return
        
    if sessions.switch_account(uid, num):
        send_message(chat_id, f"✅ Berhasil ganti akun! Sekarang menggunakan <b>{num}</b>.")
    else:
        send_message(chat_id, f"Nomor {num} tidak ditemukan di daftar akun Anda. Cek /accounts.")

def _fmt_benefit_line(ben: dict) -> str | None:
    """Format satu benefit jadi (nama, sisa/total) atau None jika tidak valid."""
    dt = ben.get("data_type", "")
    rem = ben.get("remaining", 0) or 0
    tot = ben.get("total", 0) or 0
    name = ben.get("name", "-")
    if dt == "DATA":
        return f"{name}: {_fmt_quota(rem)} / {_fmt_quota(tot)}"
    if dt == "VOICE":
        return f"{name}: {rem // 60} / {tot // 60} menit"
    if dt == "TEXT":
        return f"{name}: {rem} / {tot} SMS"
    return f"{name}: {rem} / {tot}"


def _fmt_quota_blocks(quotas: list) -> list:
    """Format seluruh paket aktif: nama, tanggal kadaluarsa, dan tiap benefit."""
    blocks = []
    for idx, q in enumerate(quotas, 1):
        lines = [f"{idx}. <b>{q.get('name', '-')}</b>"]
        expired_at = q.get("expired_at")
        if expired_at:
            lines.append(f"   📆 {time.strftime('%d-%m-%Y', time.localtime(expired_at))}")
        for ben in q.get("benefits", []) or []:
            formatted = _fmt_benefit_line(ben)
            if formatted:
                lines.append(f"   • {formatted}")
        blocks.append("\n".join(lines))
    return blocks


def _fetch_quotas(api_key: str, tokens: dict):
    """Ambil daftar quota aktif; return None saat gagal."""
    res = send_api_request(
        api_key,
        "api/v8/packages/quota-details",
        {"is_enterprise": False, "lang": "en", "family_member_id": ""},
        tokens["id_token"],
        "POST",
    )
    if not isinstance(res, dict) or res.get("status") != "SUCCESS":
        return None
    return res.get("data", {}).get("quotas", [])


def cmd_status(chat_id: int, uid: int, _args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    profile = sessions.get_profile_info(uid) or {}
    number = profile.get("number", "-")
    sub_type = profile.get("subscription_type", "-")

    balance = get_balance(API_KEY, tokens["id_token"]) or {}
    remaining = balance.get("remaining", "-")
    expired_at = balance.get("expired_at")
    expired_str = (
        time.strftime("%Y-%m-%d", time.localtime(expired_at)) if expired_at else "-"
    )

    lines = [
        f"📱 <b>{number}</b> ({sub_type})",
        f"💰 Pulsa: Rp {remaining}",
        f"📅 Aktif sampai: {expired_str}",
    ]

    if sub_type == "PREPAID":
        tiering = get_tiering_info(API_KEY, tokens) or {}
        lines.append(
            f"⭐ Points: {tiering.get('current_point', 0)} | Tier: {tiering.get('tier', 0)}"
        )

    quotas = _fetch_quotas(API_KEY, tokens)
    if quotas is None:
        lines.append("\nℹ️ Detail paket tidak tersedia saat ini.")
    elif quotas:
        lines.append("")
        lines.append("<b>Paket aktif:</b>")
        lines.extend(_fmt_quota_blocks(quotas))
    else:
        lines.append("\nℹ️ Tidak ada paket aktif.")

    send_message(chat_id, "\n".join(lines))


def cmd_paket(chat_id: int, uid: int, _args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    quotas = _fetch_quotas(API_KEY, tokens)
    if quotas is None:
        send_message(chat_id, "Gagal mengambil paket. Coba lagi nanti.")
        return
    if not quotas:
        send_message(chat_id, "Tidak ada paket aktif.")
        return

    send_message(chat_id, "\n\n".join(_fmt_quota_blocks(quotas)))


def cmd_riwayat(chat_id: int, uid: int, _args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    data = get_transaction_history(API_KEY, tokens) or {}
    history = data.get("list", [])[:31]
    if not history:
        send_message(chat_id, "Tidak ada riwayat transaksi.")
        return

    lines = []
    for t in history:
        ts = t.get("timestamp", 0)
        waktu = time.strftime("%d %b %Y %H:%M", time.localtime(ts - 7 * 3600))
        lines.append(
            f"• <b>{t.get('title', '-')}</b> — {t.get('price', '-')}\n"
            f"  {waktu} WIB | {t.get('payment_status', '-')}"
        )
    send_message(chat_id, "\n".join(lines))

def cmd_auto_riwayat(chat_id: int, _uid: int, args: str):
    period = args.strip()
    if period:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
            send_message(chat_id, "Gunakan: /auto_riwayat [YYYY-MM]\nContoh: /auto_riwayat 2026-08")
            return
        year, month = (int(value) for value in period.split("-"))
    else:
        now = datetime.now(timezone(timedelta(hours=7)))
        year, month = now.year, now.month
        period = f"{year:04d}-{month:02d}"

    try:
        summary = SupabaseStore().monthly_transaction_summary(chat_id, year, month)
    except Exception as exc:
        print(f"Auto-renew history error: {exc.__class__.__name__}")
        send_message(chat_id, "Gagal mengambil riwayat auto-renew. Coba lagi nanti.")
        return

    if not summary["by_number"]:
        send_message(chat_id, f"Tidak ada transaksi auto-renew Instagram pada {period}.")
        return

    last_day = calendar.monthrange(year, month)[1]
    lines = [
        "📊 <b>Riwayat Auto-renew Instagram</b>",
        f"Periode: {period}-01 s/d {period}-{last_day:02d}",
        f"Total sukses: <b>{summary['success']}x</b>",
        f"Total gagal: <b>{summary['failed']}x</b>",
        f"Total pulsa terpakai: <b>Rp {summary['spent']:,}</b>",
        "",
        "<b>Per nomor:</b>",
    ]
    for number, item in sorted(summary["by_number"].items()):
        lines.append(
            f"• <b>{number}</b> — sukses {item['success']}x, "
            f"gagal {item['failed']}x, pulsa Rp {item['spent']:,}"
        )
    send_message(chat_id, "\n".join(lines))



def cmd_notifikasi(chat_id: int, uid: int, _args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    res = dashboard_segments(API_KEY, tokens) or {}
    notifs = res.get("data", {}).get("notification", {}).get("data", [])
    if not notifs:
        send_message(chat_id, "Tidak ada notifikasi.")
        return

    lines = []
    for n in notifs[:10]:
        status = "✅" if n.get("is_read") else "🔵"
        brief = n.get("brief_message", "-")
        ts = n.get("timestamp", "")
        lines.append(f"{status} <b>{brief}</b>\n   {ts}")
    unread = sum(1 for n in notifs if not n.get("is_read"))
    header = f"🔔 <b>Notifikasi</b> (total {len(notifs)}, belum dibaca {unread})\n\n"
    send_message(chat_id, header + "\n".join(lines))


def cmd_family(chat_id: int, uid: int, _args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    res = get_family_data(API_KEY, tokens) or {}
    if res.get("status") != "SUCCESS":
        send_message(chat_id, "Anda tidak terdaftar di Family Plan/Akrab.")
        return

    data = res.get("data", {})
    send_message(chat_id, "<b>Family Plan/Akrab</b>\n\n" + _fmt_generic(data))


def cmd_circle(chat_id: int, uid: int, _args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    group_res = get_group_data(API_KEY, tokens) or {}
    if group_res.get("status") != "SUCCESS":
        send_message(chat_id, "Gagal mengambil data Circle.")
        return

    group_data = group_res.get("data", {})
    group_id = group_data.get("group_id", "")
    if not group_id:
        send_message(chat_id, "Anda tidak tergabung di Circle manapun.")
        return

    group_name = group_data.get("group_name", "N/A")
    group_status = group_data.get("group_status", "N/A")
    owner_name = group_data.get("owner_name", "N/A")

    members_res = get_group_members(API_KEY, tokens, group_id) or {}
    members_data = members_res.get("data", {})
    members = members_data.get("members", [])

    package = members_data.get("package", {})
    benefit = package.get("benefit", {})
    remaining = _fmt_quota(benefit.get("remaining", 0))
    allocation = _fmt_quota(benefit.get("allocation", 0))

    lines = [
        f"⭕ <b>{group_name}</b> ({group_status})",
        f"Owner: {owner_name}",
        f"Paket: {package.get('name', 'N/A')} | {remaining} / {allocation}",
        "",
        "<b>Members:</b>",
    ]
    for m in members:
        try:
            msisdn = decrypt_circle_msisdn(API_KEY, m.get("msisdn", "")) or "<No Number>"
        except Exception:
            msisdn = "<No Number>"
        role = "Parent" if m.get("member_role") == "PARENT" else "Member"
        used = _fmt_quota(m.get("allocation", 0) - m.get("remaining", 0))
        alloc = _fmt_quota(m.get("allocation", 0))
        lines.append(
            f"• {msisdn} ({m.get('member_name', '-')}) — {role}\n"
            f"  Usage: {used} / {alloc} | {m.get('status', '-')}"
        )

    send_message(chat_id, "\n".join(lines))


def cmd_familycode(chat_id: int, uid: int, args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    family_code = args.strip()
    if not family_code:
        send_message(chat_id, "Gunakan: /familycode &lt;kode&gt;")
        return

    data = get_family(API_KEY, tokens, family_code)
    if not data:
        send_message(chat_id, f"Family code <b>{family_code}</b> tidak ditemukan.")
        return

    family = data.get("package_family", {})
    title = f"📁 <b>{family.get('name', family_code)}</b>\n"
    if family.get("family_description"):
        title += f"{family['family_description']}\n"

    lines = [title]
    for variant in data.get("package_variants", []):
        vname = variant.get("name", "")
        for opt in variant.get("package_options", []):
            name = opt.get("name", "-")
            price = opt.get("price", 0)
            opt_code = opt.get("package_option_code", "")
            lines.append(
                f"• <b>{name}</b>{' (' + vname + ')' if vname else ''}\n"
                f"  Rp {price:,} | code: <code>{opt_code}</code>"
            )

    if len(lines) == 1:
        send_message(chat_id, title + "\nTidak ada paket di family ini.")
        return

    lines.append("\nDetail paket: /optioncode &lt;kode&gt;")
    send_message(chat_id, "\n".join(lines))


def cmd_optioncode(chat_id: int, uid: int, args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    option_code = args.strip()
    if not option_code:
        send_message(chat_id, "Gunakan: /optioncode &lt;kode&gt;")
        return

    package = get_package(API_KEY, tokens, option_code)
    if not package:
        send_message(chat_id, f"Option code <b>{option_code}</b> tidak ditemukan.")
        return

    po = package.get("package_option", {})
    family = package.get("package_family", {})
    variant = package.get("package_detail_variant", {})

    lines = [
        f"📦 <b>{po.get('name', '-')}</b>",
        f"Family: {family.get('name', '-')}",
        f"Variant: {variant.get('name', '-')}",
        f"Harga: Rp {po.get('price', 0):,}",
        f"Masa aktif: {po.get('validity', '-')}",
    ]
    
    short_id = get_short_id(option_code)
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "Beli (Pulsa)", "callback_data": f"buy_pulsa|{short_id}"}],
            [{"text": "Beli (QRIS)", "callback_data": f"buy_qris|{short_id}"}],
            [
                {"text": "Beli (DANA)", "callback_data": f"buy_ewallet|DANA|{short_id}"},
                {"text": "Beli (OVO)", "callback_data": f"buy_ewallet|OVO|{short_id}"}
            ]
        ]
    }
    send_message(chat_id, "\n".join(lines), reply_markup=keyboard)


def cmd_validate(chat_id: int, uid: int, args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    msisdn = args.strip()
    if not msisdn:
        send_message(chat_id, "Gunakan: /validate &lt;nomor&gt;\nContoh: /validate 6281234567890")
        return

    res = validate_msisdn(API_KEY, tokens, msisdn) or {}
    if res.get("status") != "SUCCESS":
        send_message(chat_id, f"Gagal validasi {msisdn}.")
        return

    send_message(chat_id, f"<b>Validasi {msisdn}</b>\n\n" + _fmt_generic(res.get("data", {})))


def _fmt_generic(data, depth: int = 0) -> str:
    """Format dict/list jadi teks rapi untuk Telegram (generik)."""
    pad = "  " * depth
    if isinstance(data, dict):
        lines = []
        for k, v in data.items():
            key = k.replace("_", " ")
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}<b>{key}:</b>")
                lines.append(_fmt_generic(v, depth + 1))
            else:
                lines.append(f"{pad}{key}: {v}")
        return "\n".join(lines)
    if isinstance(data, list):
        if not data:
            return f"{pad}-"
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(_fmt_generic(item, depth + 1))
                lines.append(f"{pad}---")
            else:
                lines.append(f"{pad}• {item}")
        return "\n".join(lines)
    return f"{pad}{data}"


COMMANDS = {
    "/start": cmd_start,
    "/help": cmd_help,
    "/login": cmd_login,
    "/logout": cmd_logout,
    "/accounts": cmd_accounts,
    "/switch": cmd_switch,
    "/status": cmd_status,
    "/paket": cmd_paket,
    "/packages": cmd_paket,
    "/riwayat": cmd_riwayat,
    "/history": cmd_riwayat,
    "/auto_riwayat": cmd_auto_riwayat,
    "/auto-riwayat": cmd_auto_riwayat,
    "/notifikasi": cmd_notifikasi,
    "/notif": cmd_notifikasi,
    "/family": cmd_family,
    "/circle": cmd_circle,
    "/familycode": cmd_familycode,
    "/optioncode": cmd_optioncode,
    "/validate": cmd_validate,
    "/hot": lambda c, u, a: cmd_hot(c, u, a),
}

def cmd_hot(chat_id: int, uid: int, _args: str):
    tokens = _need_login(chat_id, uid)
    if not tokens:
        return
    url = "https://me.mashu.lol/pg-hot.json"
    try:
        response = requests.get(url, timeout=30)
        hot_packages = response.json()
    except Exception:
        send_message(chat_id, "Gagal mengambil data hot package.")
        return

    lines = ["🔥 <b>Paket Hot</b> 🔥\n"]
    keyboard = {"inline_keyboard": []}

    for idx, p in enumerate(hot_packages):
        lines.append(f"{idx+1}. {p['family_name']} - {p['variant_name']} - {p['option_name']}")
        row = [{"text": f"Pilih {idx+1}", "callback_data": f"hot_select|{idx}"}]
        keyboard["inline_keyboard"].append(row)

    send_message(chat_id, "\n".join(lines), reply_markup=keyboard)

def execute_buy(chat_id: int, tokens: dict, option_code: str, method: str, provider: str = "", wallet_number: str = ""):
    package = get_package(API_KEY, tokens, option_code)
    if not package:
        send_message(chat_id, f"Gagal memuat paket {option_code}.")
        return

    po = package.get("package_option", {})
    family = package.get("package_family", {})
    price = po.get("price", 0)
    payment_for = family.get("payment_for", "BUY_PACKAGE")
    if not payment_for:
        payment_for = "BUY_PACKAGE"

    items = [
        PaymentItem(
            item_code=option_code,
            product_type="",
            item_price=price,
            item_name=po.get("name", "Paket"),
            tax=0,
            token_confirmation=package.get("token_confirmation", ""),
        )
    ]

    send_message(chat_id, "Memproses pembelian... Mohon tunggu.")

    try:
        if method == "pulsa":
            res = settlement_balance(
                API_KEY, tokens, items, payment_for,
                ask_overwrite=False, overwrite_amount=price
            )
            if res and res.get("status") == "SUCCESS":
                send_message(chat_id, "✅ Pembelian berhasil menggunakan Pulsa!")
            else:
                msg = res.get("message", "Unknown error") if res else "Failed"
                send_message(chat_id, f"❌ Pembelian gagal: {msg}")
        
        elif method == "qris":
            res = show_qris_payment(
                API_KEY, tokens, items, payment_for,
                ask_overwrite=False, overwrite_amount=price
            )
            if res:
                qris_url = f"https://ki-ar-kod.netlify.app/?data={res}"
                send_message(chat_id, f"✅ Silahkan bayar QRIS di link berikut:\n{qris_url}")
            else:
                send_message(chat_id, "❌ Gagal membuat QRIS.")
                
        elif method == "ewallet":
            res = settlement_multipayment(
                API_KEY, tokens, items, wallet_number, provider, payment_for,
                ask_overwrite=False, overwrite_amount=price
            )
            if res and res.get("status") == "SUCCESS":
                if provider != "OVO":
                    deeplink = res.get("data", {}).get("deeplink", "")
                    send_message(chat_id, f"✅ Silahkan bayar melalui link berikut:\n{deeplink}")
                else:
                    send_message(chat_id, "✅ Silahkan buka aplikasi OVO untuk menyelesaikan pembayaran.")
            else:
                msg = res.get("message", "Unknown error") if res else "Failed"
                send_message(chat_id, f"❌ Pembelian gagal: {msg}")

    except Exception as e:
        send_message(chat_id, f"Terjadi kesalahan: {e}")

def handle_callback_query(cq: dict):
    uid = cq.get("from", {}).get("id")
    message = cq.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    data = cq.get("data", "")
    cb_id = cq.get("id")

    tg_api("answerCallbackQuery", {"callback_query_id": cb_id})

    if not chat_id or not uid:
        return

    tokens = _need_login(chat_id, uid)
    if not tokens:
        return

    if data.startswith("buy_pulsa|"):
        _, short_id = data.split("|", 1)
        option_code = CALLBACK_STORE.get(short_id)
        if not option_code:
            send_message(chat_id, "Sesi kedaluwarsa. Silakan ulangi /optioncode.")
            return
        execute_buy(chat_id, tokens, option_code, "pulsa")
    elif data.startswith("buy_qris|"):
        _, short_id = data.split("|", 1)
        option_code = CALLBACK_STORE.get(short_id)
        if not option_code:
            send_message(chat_id, "Sesi kedaluwarsa. Silakan ulangi /optioncode.")
            return
        execute_buy(chat_id, tokens, option_code, "qris")
    elif data.startswith("buy_ewallet|"):
        _, provider, short_id = data.split("|", 2)
        option_code = CALLBACK_STORE.get(short_id)
        if not option_code:
            send_message(chat_id, "Sesi kedaluwarsa. Silakan ulangi /optioncode.")
            return
        if provider in ["DANA", "OVO"]:
            sess = sessions.get_session(uid)
            sess["pending_wallet"] = {
                "provider": provider,
                "option_code": option_code
            }
            send_message(chat_id, f"Ketik nomor {provider} kamu (contoh: 08123456789):")
    elif data.startswith("hot_select|"):
        _, idx_str = data.split("|", 1)
        idx = int(idx_str)
        url = "https://me.mashu.lol/pg-hot.json"
        try:
            response = requests.get(url, timeout=30)
            hot_packages = response.json()
            if idx >= len(hot_packages):
                return
            selected = hot_packages[idx]
            family_code = selected["family_code"]
            is_enterprise = selected.get("is_enterprise", False)
            family_data = get_family(API_KEY, tokens, family_code, is_enterprise)
            if not family_data:
                send_message(chat_id, "Gagal mengambil data family.")
                return
            option_code = None
            for variant in family_data.get("package_variants", []):
                if variant["name"] == selected["variant_name"]:
                    for option in variant.get("package_options", []):
                        if option["order"] == selected["order"]:
                            option_code = option["package_option_code"]
                            break
            if option_code:
                cmd_optioncode(chat_id, uid, option_code)
            else:
                send_message(chat_id, "Paket tidak ditemukan di server XL.")
        except Exception:
            send_message(chat_id, "Gagal mengambil data hot package.")


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------


MENU_ACTIONS = {
    "👤 Akun": ("menu", ACCOUNT_MENU, "Pilih layanan akun."),
    "📊 Informasi": ("menu", INFO_MENU, "Pilih informasi yang ingin dilihat."),
    "📦 Paket": ("menu", PACKAGE_MENU, "Pilih layanan paket."),
    "🔎 Cari Paket": ("menu", PACKAGE_MENU, "Pilih metode pencarian paket."),
    "⚙️ Bantuan": ("handler", cmd_help, ""),
    "🧾 Riwayat": ("handler", cmd_riwayat, ""),
    "⬅️ Menu Utama": ("menu", MAIN_MENU, "Pilih layanan dari menu utama."),
    "🔐 Login": ("input", "login", "Masukkan nomor XL diawali 628 (contoh: 6281234567890):"),
    "💰 Status": ("handler", cmd_status, ""),
    "📋 Akun Tersimpan": ("handler", cmd_accounts, ""),
    "🔄 Ganti Akun": ("input", "switch", "Masukkan nomor akun yang ingin diaktifkan:"),
    "🚪 Logout": ("handler", cmd_logout, ""),
    "📦 Paket Aktif": ("handler", cmd_paket, ""),
    "🧾 Riwayat XL": ("handler", cmd_riwayat, ""),
    "📊 Auto-renew": ("handler", cmd_auto_riwayat, ""),
    "🔔 Notifikasi": ("handler", cmd_notifikasi, ""),
    "👨‍👩‍👧 Family Plan": ("handler", cmd_family, ""),
    "⭕ Circle": ("handler", cmd_circle, ""),
    "🔥 Paket Hot": ("handler", cmd_hot, ""),
    "📁 Family Code": ("input", "familycode", "Masukkan family code paket:"),
    "🔑 Option Code": ("input", "optioncode", "Masukkan option code paket:"),
    "✅ Validasi Nomor": ("input", "validate", "Masukkan nomor yang ingin divalidasi (diawali 628):"),
}


def handle_menu_text(chat_id: int, uid: int, text: str) -> bool:
    """Tangani tombol Reply Keyboard dan input lanjutan dari tombol."""
    action = MENU_ACTIONS.get(text)
    sess = sessions.get_session(uid)

    if action:
        kind, value, prompt = action
        sess["pending_action"] = None
        if kind == "menu":
            _show_menu(chat_id, prompt, value)
        elif kind == "input":
            _ask_menu_input(chat_id, uid, value, prompt)
        else:
            _run_menu_handler(chat_id, uid, value)
        return True

    pending_action = sess.get("pending_action")
    if pending_action:
        sess["pending_action"] = None
        handler = COMMANDS.get(f"/{pending_action}")
        if handler:
            _run_menu_handler_with_args(chat_id, uid, handler, text)
        return True

    return False


def _handle_command(chat_id: int, uid: int, text: str):
    cmd, _, args = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    handler = COMMANDS.get(cmd)
    if handler:
        try:
            handler(chat_id, uid, args)
        except Exception as e:
            print(f"Command {cmd} error: {e.__class__.__name__}")
            send_message(chat_id, "Terjadi kesalahan. Coba lagi nanti.")
    else:
        send_message(chat_id, "Perintah tidak dikenal. Ketik /help.", reply_markup=MAIN_MENU)


def handle_update(update: dict):
    if "callback_query" in update:
        handle_callback_query(update["callback_query"])
        return

    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    text = (message.get("text") or "").strip()
    if not text:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    uid = message.get("from", {}).get("id")
    if chat_id is None or uid is None:
        return

    # Coba tangani sebagai OTP dulu jika user sedang menunggu login.
    if handle_otp(chat_id, uid, text):
        return

    # Check pending wallet for e-wallet payment
    sess = sessions.get_session(uid)
    pending_wallet = sess.get("pending_wallet")
    if pending_wallet:
        provider = pending_wallet["provider"]
        option_code = pending_wallet["option_code"]
        
        if text.startswith("08") and text.isdigit() and 10 <= len(text) <= 13:
            sess["pending_wallet"] = None
            tokens = _need_login(chat_id, uid)
            if tokens:
                execute_buy(chat_id, tokens, option_code, "ewallet", provider=provider, wallet_number=text)
            return
        elif text.lower() == 'batal':
            sess["pending_wallet"] = None
            send_message(chat_id, "Pembelian dibatalkan.")
            return
        else:
            send_message(chat_id, f"Nomor {provider} tidak valid. Pastikan dimulai dengan 08 dan panjang 10-13 digit.\nKetik 'batal' untuk membatalkan.")
            return

    if handle_menu_text(chat_id, uid, text):
        return

    if text.startswith("/"):
        _handle_command(chat_id, uid, text)
    else:
        send_message(chat_id, "Pilih layanan dari menu atau ketik /help.", reply_markup=MAIN_MENU)


def main():
    print("Bot sedang berjalan... (Ctrl+C untuk berhenti)")
    offset = 0
    while True:
        try:
            updates = tg_api("getUpdates", {
                "offset": offset,
                "timeout": 30,
                "allowed_updates": ["message", "callback_query"],
            })
            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                handle_update(update)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot dihentikan.")
