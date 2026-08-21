import time
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from app.client.ciam import get_new_token
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


def _quota_bytes(value):
    """Convert API quota values to bytes without crashing on malformed data."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _instagram_quota_matches(quotas: list):
    """Return every benefit explicitly identified as Instagram."""
    matches = []
    for quota in quotas or []:
        quota_name = str(quota.get("name", ""))
        for benefit in quota.get("benefits", []) or []:
            benefit_name = str(benefit.get("name", ""))
            if "instagram" not in benefit_name.lower():
                continue
            matches.append({
                "quota_name": quota_name or "Bonus Instagram",
                "benefit_name": benefit_name or "Instagram",
                "remaining": _quota_bytes(benefit.get("remaining")),
                "total": _quota_bytes(benefit.get("total")),
            })
    return matches


def check_instagram_quota_from_list(quotas: list):
    """
    Check all Instagram-related benefits from the quota list.
    If multiple entries exist, an entry with remaining quota wins over an
    exhausted entry, preventing a false refill from the first match.
    """
    matches = _instagram_quota_matches(quotas)
    if matches:
        selected = max(matches, key=lambda item: item["remaining"])
        return (
            selected["remaining"],
            selected["total"],
            selected["quota_name"],
            True,
        )

    # If no Instagram package is present in the active quota response, it is
    # considered 0 / not found, preserving the existing auto-refill policy.
    return 0, 0, None, False


def print_quota_diagnostics(quotas: list):
    """Print quota names and benefits without exposing authentication data."""
    print("\n=== DIAGNOSTIK KUOTA (READ-ONLY) ===")
    if not quotas:
        print("Tidak ada quota aktif pada response API.")
        return

    for index, quota in enumerate(quotas, 1):
        print(f"[{index}] {quota.get('name', '-')} | group={quota.get('group_name', '-')} | expired_at={quota.get('expired_at', '-')}")
        for benefit in quota.get("benefits", []) or []:
            print(
                f"    - {benefit.get('name', '-')} | "
                f"remaining={_quota_bytes(benefit.get('remaining'))} | "
                f"total={_quota_bytes(benefit.get('total'))} | "
                f"type={benefit.get('data_type', '-')}"
            )

    matches = _instagram_quota_matches(quotas)
    print(f"Match Instagram: {len(matches)}")
    for match in matches:
        print(
            f"    -> {match['quota_name']} / {match['benefit_name']} | "
            f"{format_quota_byte(match['remaining'])} / {format_quota_byte(match['total'])}"
        )


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

    package_option = pkg_detail.get("package_option", {})
    price = _quota_bytes(package_option.get("price"))
    if price <= 0:
        print("[Refill Error] Harga paket tidak valid.")
        return False

    balance_data = get_balance(api_key, tokens.get("id_token"))
    current_balance = _quota_bytes((balance_data or {}).get("remaining"))
    if current_balance < price:
        print(f"[Refill Error] Pulsa tidak mencukupi: Rp {current_balance:,} < Rp {price:,}.")
        return False

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


def _local_accounts():
    """Load every locally logged-in account without exposing its tokens."""
    AuthInstance.load_tokens()
    return [
        account for account in AuthInstance.refresh_tokens
        if account.get("number") and account.get("refresh_token")
    ]


def _refresh_local_account(account):
    """Refresh one local account and persist only the rotated token."""
    tokens = get_new_token(
        AuthInstance.api_key,
        account["refresh_token"],
        account.get("subscriber_id", ""),
    )
    if not tokens or not tokens.get("id_token"):
        raise RuntimeError("CIAM tidak mengembalikan token yang valid")

    account["refresh_token"] = tokens.get("refresh_token", account["refresh_token"])
    AuthInstance.write_tokens_to_file()
    return tokens


def process_local_account(account, ig_config, allow_purchase=True):
    """Process one account; callers decide whether purchases are allowed."""
    number = account["number"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now_str}] Nomor {number}: memeriksa status paket & kuota...")

    try:
        tokens = _refresh_local_account(account)
        id_token = tokens["id_token"]

        bal_data = get_balance(AuthInstance.api_key, id_token)
        current_balance = _quota_bytes((bal_data or {}).get("remaining"))
        print(f"[{now_str}] Nomor {number}: sisa pulsa Rp {current_balance:,}")

        quotas = get_quota_details(AuthInstance.api_key, id_token)
        if quotas is None:
            print(f"[{now_str}] Nomor {number}: gagal mengambil data kuota.")
            return False

        xcp_active, xcp_expired_at, xcp_name = check_xtra_combo_plus_status(quotas)
        if not xcp_active:
            exp_dt_str = (
                datetime.fromtimestamp(xcp_expired_at).strftime("%Y-%m-%d %H:%M:%S")
                if xcp_expired_at else "Tidak Ada"
            )
            print(f"[{now_str}] Nomor {number}: Xtra Combo Plus tidak aktif (Expired: {exp_dt_str}).")
            if not allow_purchase:
                print(f"[{now_str}] Nomor {number}: mode diagnostik, tidak membeli paket induk.")
            elif current_balance >= XTRA_COMBO_PLUS_REWRITE_PRICE:
                print(f"[{now_str}] Nomor {number}: membeli ulang Xtra Combo Plus.")
                if buy_xtra_combo_plus_package(AuthInstance.api_key, tokens):
                    time.sleep(10)
            else:
                print(f"[{now_str}] Nomor {number}: pulsa tidak cukup untuk Xtra Combo Plus.")
            return True

        exp_dt_str = datetime.fromtimestamp(xcp_expired_at).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] Nomor {number}: paket induk [{xcp_name}] aktif sampai {exp_dt_str}.")

        remaining, total, quota_name, is_found = check_instagram_quota_from_list(quotas)
        if not is_found:
            print(f"[{now_str}] Nomor {number}: kuota Instagram tidak ditemukan.")
            print(f"[{now_str}] Nomor {number}: pembelian dibatalkan untuk mencegah salah beli.")
        elif remaining <= 0:
            print(f"[{now_str}] Nomor {number}: kuota Instagram HABIS (0 B / {format_quota_byte(total)}).")
            if not allow_purchase:
                print(f"[{now_str}] Nomor {number}: mode diagnostik, tidak membeli add-on.")
            else:
                print(f"[{now_str}] Nomor {number}: memulai refill Instagram menggunakan pulsa.")
                if refill_instagram_package(AuthInstance.api_key, tokens, ig_config):
                    time.sleep(10)
        else:
            print(
                f"[{now_str}] Nomor {number}: kuota Instagram masih ada "
                f"({format_quota_byte(remaining)} / {format_quota_byte(total)}). Aman."
            )
        return True
    except Exception as exc:
        print(f"[{now_str}] Nomor {number}: gagal diproses: {exc}")
        return False


def start_auto_refill_loop(interval_seconds: int = DEFAULT_CHECK_INTERVAL):
    """Monitor every local account sequentially in one process."""
    accounts = _local_accounts()
    if not accounts:
        print("Error: Belum ada akun lokal yang login.")
        return

    ig_config = get_ig_bookmark_config()
    clear_screen()
    print("=" * 65)
    print("      🤖 AUTO REFILL MULTI-NOMOR LOKAL 🤖      ")
    print("=" * 65)
    print(f"Jumlah Nomor      : {len(accounts)}")
    print(f"Nomor             : {', '.join(str(a['number']) for a in accounts)}")
    print(f"Xtra Combo Fam    : {XTRA_COMBO_PLUS_FAMCODE} (Option {XTRA_COMBO_PLUS_ORDER}, Rewrite Rp {XTRA_COMBO_PLUS_REWRITE_PRICE})")
    print(f"Instagram Paket   : {ig_config['variant_name']} - {ig_config['option_name']}")
    print(f"Check Interval    : {interval_seconds} detik ({interval_seconds // 60} menit)")
    print("Pemrosesan akun    : sequential, satu per satu")
    print("Tekan Ctrl+C untuk menghentikan monitoring.")
    print("=" * 65)

    try:
        while True:
            accounts = _local_accounts()
            if not accounts:
                print("Tidak ada akun lokal yang dapat diproses.")
                return

            for account in accounts:
                process_local_account(account, ig_config, allow_purchase=True)

            print(f"\nMenunggu {interval_seconds} detik hingga siklus berikutnya...\n")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\n\nMonitoring auto refill dihentikan oleh pengguna.")


if __name__ == "__main__":
    accounts = _local_accounts()
    if "--diagnose-quota" in sys.argv:
        if not accounts:
            print("Error: Belum ada akun lokal yang login.")
            sys.exit(1)

        ig_config = get_ig_bookmark_config()
        print("=" * 65)
        print("      DIAGNOSTIK KUOTA MULTI-NOMOR (READ-ONLY)      ")
        print("=" * 65)
        print(f"Jumlah Nomor: {len(accounts)}")
        for account in accounts:
            process_local_account(account, ig_config, allow_purchase=False)
        print("\nTidak ada pembelian yang dipanggil.")
        sys.exit(0)

    start_auto_refill_loop()
