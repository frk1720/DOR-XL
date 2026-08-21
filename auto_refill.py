import time
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from app.service.auth import AuthInstance
from app.client.engsel import send_api_request, get_family, get_package, get_balance
from app.client.purchase.balance import settlement_balance
from app.type_dict import PaymentItem
from app.service.bookmark import BookmarkInstance
from app.menus.util import format_quota_byte, clear_screen

DEFAULT_IG_FAMCODE = "7658c955-a0b9-405f-bb17-de7f43d1a946"
DEFAULT_IG_VARIANT = "Bonus Xtra Combo Plus 10GB"
DEFAULT_IG_ORDER = 6
DEFAULT_CHECK_INTERVAL = 120  # 2 minutes in seconds

XTRA_COMBO_PLUS_FAMCODE = "23b71540-8785-4abe-816d-e9b4efa48f95"
XTRA_COMBO_PLUS_ORDER = 35
XTRA_COMBO_PLUS_REWRITE_PRICE = 30000  # 30k rewrite


def get_ig_bookmark_config():
    """
    Search bookmark.json for Instagram package.
    Falls back to default config if not found.
    """
    bookmarks = BookmarkInstance.get_bookmarks()
    for bm in bookmarks:
        fam_name = bm.get("family_name", "").lower()
        opt_name = bm.get("option_name", "").lower()
        if "instagram" in opt_name or "instagram" in fam_name:
            return {
                "family_code": bm.get("family_code", DEFAULT_IG_FAMCODE),
                "family_name": bm.get("family_name", "Kuota Aplikasi Xtra Combo Plus 10GB"),
                "is_enterprise": bm.get("is_enterprise", False) or False,
                "variant_name": bm.get("variant_name", DEFAULT_IG_VARIANT),
                "option_name": bm.get("option_name", "Instagram 10GB"),
                "order": bm.get("order", DEFAULT_IG_ORDER)
            }

    return {
        "family_code": DEFAULT_IG_FAMCODE,
        "family_name": "Kuota Aplikasi Xtra Combo Plus 10GB",
        "is_enterprise": False,
        "variant_name": DEFAULT_IG_VARIANT,
        "option_name": "Instagram 10GB",
        "order": DEFAULT_IG_ORDER
    }


def get_quota_details(api_key: str, id_token: str):
    """
    Fetch all active quotas from API.
    """
    path = "api/v8/packages/quota-details"
    payload = {
        "is_enterprise": False,
        "lang": "en",
        "family_member_id": ""
    }
    res = send_api_request(api_key, path, payload, id_token, "POST")
    if not res or res.get("status") != "SUCCESS":
        return None
    return res.get("data", {}).get("quotas", [])


def check_xtra_combo_plus_status(quotas: list):
    """
    Check if main Xtra Combo Plus package is active and not expired.
    Returns (is_active, expired_at, name).
    """
    now_ts = int(time.time())
    for q in quotas:
        name = q.get("name", "")
        # Check quota name or group name for Xtra Combo Plus (excluding Bonus IG)
        if "xtra combo plus" in name.lower() and "bonus" not in name.lower():
            expired_at = q.get("expired_at", 0)
            if expired_at > now_ts:
                return True, expired_at, name
            else:
                return False, expired_at, name

    # If not found in active quotas, it's considered expired/inactive
    return False, 0, None


def check_instagram_quota_from_list(quotas: list):
    """
    Check current remaining Instagram quota from quotas list.
    Returns (remaining_bytes, total_bytes, quota_name, is_found).
    """
    for q in quotas:
        q_name = q.get("name", "").lower()
        group_name = q.get("group_name", "").lower()
        for b in q.get("benefits", []):
            b_name = b.get("name", "").lower()
            if "instagram" in b_name or "instagram" in q_name or "instagram" in group_name:
                remaining = b.get("remaining", 0)
                total = b.get("total", 0)
                return remaining, total, q.get("name", "Bonus Instagram"), True

    # If no Instagram package active, it is considered 0 / not found
    return 0, 0, None, False


def buy_xtra_combo_plus_package(api_key: str, tokens: dict):
    """
    Purchase Xtra Combo Plus package (Family: 23b71540-8785-4abe-816d-e9b4efa48f95, Option 35)
    with rewrite price Rp 30.000 using balance.
    """
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai proses pembelian Xtra Combo Plus (Family Code: {XTRA_COMBO_PLUS_FAMCODE}, No. {XTRA_COMBO_PLUS_ORDER})...")

    # 1. Fetch family data
    family_data = get_family(
        api_key,
        tokens,
        XTRA_COMBO_PLUS_FAMCODE,
        False
    )
    if not family_data:
        print("[Xtra Combo Plus Error] Gagal mengambil data family.")
        return False

    payment_for = family_data.get("package_family", {}).get("payment_for", "BUY_PACKAGE")
    if not payment_for:
        payment_for = "BUY_PACKAGE"

    package_variants = family_data.get("package_variants", [])
    option_code = None
    target_option = None
    target_variant_name = ""

    for variant in package_variants:
        for option in variant.get("package_options", []):
            if option.get("order") == XTRA_COMBO_PLUS_ORDER:
                target_option = option
                target_variant_name = variant.get("name", "")
                option_code = option.get("package_option_code")
                break
        if option_code:
            break

    if not option_code:
        print(f"[Xtra Combo Plus Error] Option order {XTRA_COMBO_PLUS_ORDER} tidak ditemukan di family {XTRA_COMBO_PLUS_FAMCODE}.")
        return False

    # 2. Get package detail (token_confirmation, etc.)
    pkg_detail = get_package(api_key, tokens, option_code)
    if not pkg_detail:
        print("[Xtra Combo Plus Error] Gagal mengambil detail package option.")
        return False

    orig_price = pkg_detail.get("package_option", {}).get("price", 0)
    token_confirmation = pkg_detail.get("token_confirmation", "")
    opt_name = target_option.get("name", "") if target_option else ""
    item_name = f"Xtra Combo Plus {target_variant_name} {opt_name}".strip()

    payment_items = [
        PaymentItem(
            item_code=option_code,
            product_type="",
            item_price=orig_price,
            item_name=item_name,
            tax=0,
            token_confirmation=token_confirmation,
        )
    ]

    print(f"Membeli paket: {item_name} | Harga Normal: Rp {orig_price} -> Rewrite: Rp {XTRA_COMBO_PLUS_REWRITE_PRICE}...")
    res = settlement_balance(
        api_key=api_key,
        tokens=tokens,
        items=payment_items,
        payment_for=payment_for,
        ask_overwrite=False,
        overwrite_amount=XTRA_COMBO_PLUS_REWRITE_PRICE
    )

    if res and res.get("status") == "SUCCESS":
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PEMBELIAN XTRA COMBO PLUS BERHASIL! Paket {item_name} (Rp {XTRA_COMBO_PLUS_REWRITE_PRICE}) aktif.")
        return True
    else:
        err_msg = res.get("message", "Unknown error") if isinstance(res, dict) else str(res)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PEMBELIAN XTRA COMBO PLUS GAGAL: {err_msg}")
        return False


def refill_instagram_package(api_key: str, tokens: dict, config: dict):
    """
    Purchase Instagram package using main balance (pulsa).
    """
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai proses refill paket Instagram...")

    # 1. Fetch package details via family
    family_data = get_family(
        api_key,
        tokens,
        config["family_code"],
        config["is_enterprise"]
    )
    if not family_data:
        print("[Refill Error] Gagal mengambil data family.")
        return False

    payment_for = family_data.get("package_family", {}).get("payment_for", "BUY_PACKAGE")
    if not payment_for:
        payment_for = "BUY_PACKAGE"

    package_variants = family_data.get("package_variants", [])
    option_code = None
    for variant in package_variants:
        if variant.get("name") == config["variant_name"]:
            for option in variant.get("package_options", []):
                if option.get("order") == config["order"]:
                    option_code = option.get("package_option_code")
                    break

    if not option_code:
        print("[Refill Error] Option code Instagram tidak ditemukan di family.")
        return False

    # 2. Get detailed package option info (token_confirmation, price, etc.)
    pkg_detail = get_package(api_key, tokens, option_code)
    if not pkg_detail:
        print("[Refill Error] Gagal mengambil detail package option.")
        return False

    price = pkg_detail.get("package_option", {}).get("price", 0)
    token_confirmation = pkg_detail.get("token_confirmation", "")
    item_name = f"{config['variant_name']} {config['option_name']}".strip()

    payment_items = [
        PaymentItem(
            item_code=option_code,
            product_type="",
            item_price=price,
            item_name=item_name,
            tax=0,
            token_confirmation=token_confirmation,
        )
    ]

    print(f"Membeli paket: {item_name} | Harga: Rp {price}...")
    res = settlement_balance(
        api_key=api_key,
        tokens=tokens,
        items=payment_items,
        payment_for=payment_for,
        ask_overwrite=False,
        overwrite_amount=price
    )

    if res and res.get("status") == "SUCCESS":
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] REFILL BERHASIL! Paket {item_name} berhasil dibeli.")
        return True
    else:
        err_msg = res.get("message", "Unknown error") if isinstance(res, dict) else str(res)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] REFILL GAGAL: {err_msg}")
        return False


def start_auto_refill_loop(interval_seconds: int = DEFAULT_CHECK_INTERVAL):
    """
    Main loop:
    1. Checks Xtra Combo Plus status.
       - If expired / not active: DO NOT refill IG. Re-buy Xtra Combo Plus (Family 23b71540-8785-4abe-816d-e9b4efa48f95, Option 35, Rp 30k) IF balance is sufficient (>= 30k).
    2. If Xtra Combo Plus is active:
       - Check Instagram quota.
       - If Instagram quota is 0 / exhausted: Refill Instagram package using balance IF balance is sufficient.
    Loop runs every `interval_seconds` (default 120s / 2 mins).
    """
    active_user = AuthInstance.get_active_user()
    if not active_user:
        print("Error: Belum ada user yang login.")
        return

    ig_config = get_ig_bookmark_config()

    clear_screen()
    print("=" * 65)
    print("      🤖 AUTO REFILL KUOTA INSTAGRAM & XTRA COMBO PLUS 🤖      ")
    print("=" * 65)
    print(f"Nomor Aktif       : {active_user['number']}")
    print(f"Xtra Combo Fam    : {XTRA_COMBO_PLUS_FAMCODE} (Option {XTRA_COMBO_PLUS_ORDER}, Rewrite Rp {XTRA_COMBO_PLUS_REWRITE_PRICE})")
    print(f"Instagram Paket   : {ig_config['variant_name']} - {ig_config['option_name']}")
    print(f"Check Interval    : {interval_seconds} detik ({interval_seconds // 60} menit)")
    print("Tekan Ctrl+C untuk menghentikan monitoring.")
    print("=" * 65)

    try:
        while True:
            # Re-fetch active tokens (handles auto-token renewal if expired)
            active_user = AuthInstance.get_active_user()
            if not active_user:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] User session expired. Mencoba login ulang...")
                time.sleep(10)
                continue

            api_key = AuthInstance.api_key
            tokens = active_user["tokens"]
            id_token = tokens.get("id_token")

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{now_str}] Memeriksa status paket & kuota...")

            # 1. Check current balance
            bal_data = get_balance(api_key, id_token)
            current_balance = bal_data.get("remaining", 0) if bal_data else 0
            print(f"[{now_str}] Sisa Pulsa Saat Ini: Rp {current_balance:,}")

            # 2. Fetch active quotas
            quotas = get_quota_details(api_key, id_token)
            if quotas is None:
                print(f"[{now_str}] Gagal mengambil data kuota (koneksi/API error). Menunggu cek berikutnya...")
                time.sleep(interval_seconds)
                continue

            # 3. Check Xtra Combo Plus status
            xcp_active, xcp_expired_at, xcp_name = check_xtra_combo_plus_status(quotas)

            if not xcp_active:
                exp_dt_str = datetime.fromtimestamp(xcp_expired_at).strftime('%Y-%m-%d %H:%M:%S') if xcp_expired_at else "Tidak Ada"
                print(f"[{now_str}] ⚠️ PAKET XTRA COMBO PLUS EXPIRED / TIDAK AKTIF (Expired at: {exp_dt_str})!")
                print(f"[{now_str}] ⛔ JANGAN REFILL KUOTA INSTAGRAM KARENA INDUK EXPIRED.")

                # Check if balance is sufficient to buy Xtra Combo Plus (Rp 30.000)
                if current_balance >= XTRA_COMBO_PLUS_REWRITE_PRICE:
                    print(f"[{now_str}] 💰 Pulsa mencukupi (Rp {current_balance:,} >= Rp {XTRA_COMBO_PLUS_REWRITE_PRICE:,}).")
                    print(f"[{now_str}] >> MEMBELI KEMBALI XTRA COMBO PLUS (Option {XTRA_COMBO_PLUS_ORDER} @ Rp {XTRA_COMBO_PLUS_REWRITE_PRICE}) <<")
                    bought = buy_xtra_combo_plus_package(api_key, tokens)
                    if bought:
                        time.sleep(10)
                else:
                    print(f"[{now_str}] ❌ Pulsa TIDAK mencukupi untuk beli Xtra Combo Plus: Rp {current_balance:,} < Rp {XTRA_COMBO_PLUS_REWRITE_PRICE:,}.")
                    print(f"[{now_str}] Silakan isi pulsa terlebih dahulu.")

            else:
                exp_dt_str = datetime.fromtimestamp(xcp_expired_at).strftime('%Y-%m-%d %H:%M:%S')
                print(f"[{now_str}] ✅ Paket Induk [{xcp_name}] AKTIF sampai {exp_dt_str}.")

                # 4. Check Instagram Quota
                remaining, total, q_name, is_found = check_instagram_quota_from_list(quotas)

                if not is_found or remaining == 0:
                    if not is_found:
                        print(f"[{now_str}] Kuota Instagram: TIDAK DITEMUKAN / 0 B.")
                    else:
                        print(f"[{now_str}] Kuota Instagram HABIS: 0 B / {format_quota_byte(total)}.")

                    # Check if balance is sufficient for Instagram package (Rp 5.000)
                    if current_balance >= 5000:
                        print(f"[{now_str}] >> TRIGGER REFILL KUOTA INSTAGRAM MENGGUNAKAN PULSA <<")
                        refill_success = refill_instagram_package(api_key, tokens, ig_config)
                        if refill_success:
                            time.sleep(10)
                    else:
                        print(f"[{now_str}] ❌ Pulsa tidak mencukupi untuk refill Instagram (Pulsa: Rp {current_balance:,} < Rp 5.000).")
                else:
                    remaining_str = format_quota_byte(remaining)
                    total_str = format_quota_byte(total)
                    print(f"[{now_str}] Kuota Instagram masih ada: {remaining_str} / {total_str} (Aman).")

            print(f"Menunggu {interval_seconds} detik hingga pengecekan berikutnya...\n")
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        print("\n\nMonitoring auto refill dihentikan oleh pengguna.")


if __name__ == "__main__":
    start_auto_refill_loop()
