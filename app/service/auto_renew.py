import os
from datetime import datetime, timezone

import requests

from app.client.ciam import get_new_token
from app.client.engsel import get_balance, get_package, send_api_request
from app.client.purchase.balance import settlement_balance
from app.type_dict import PaymentItem


QUOTA_PATH = "api/v8/packages/quota-details"
IG_THRESHOLD = 0  # Keep existing behavior: purchase only at zero/not found.


class SupabaseStore:
    def __init__(self):
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def claim_accounts(self):
        response = requests.post(
            f"{self.url}/rest/v1/rpc/claim_auto_renew_accounts",
            headers=self.headers,
            json={"p_lock_seconds": 300},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def update_account(self, account_id, values):
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        response = requests.patch(
            f"{self.url}/rest/v1/auto_renew_accounts?id=eq.{account_id}",
            headers={**self.headers, "Prefer": "return=minimal"},
            json=values,
            timeout=20,
        )
        response.raise_for_status()


def get_quota_details(api_key, id_token):
    result = send_api_request(
        api_key,
        QUOTA_PATH,
        {"is_enterprise": False, "lang": "en", "family_member_id": ""},
        id_token,
        "POST",
    )
    if not isinstance(result, dict) or result.get("status") != "SUCCESS":
        raise RuntimeError("Gagal mengambil data kuota")
    return result.get("data", {}).get("quotas", [])


def _instagram_quota_matches(quotas):
    matches = []
    for quota in quotas or []:
        quota_name = str(quota.get("name", ""))
        for benefit in quota.get("benefits", []) or []:
            benefit_name = str(benefit.get("name", ""))
            if "instagram" not in benefit_name.lower():
                continue
            try:
                remaining = int(benefit.get("remaining", 0) or 0)
            except (TypeError, ValueError):
                remaining = 0
            matches.append((remaining, quota_name or "Instagram"))
    return matches


def instagram_remaining(quotas):
    matches = _instagram_quota_matches(quotas)
    if not matches:
        return 0, False
    return max(remaining for remaining, _ in matches), True

def _xtra_combo_plus_3gb_available(quotas):
    """Return whether the active quota list contains the 3GB main package."""
    now_ts = int(datetime.now(timezone.utc).timestamp())

    def expiry_state(expiry):
        """Return True/False when known, otherwise None for unknown expiry."""
        if expiry in (None, "", 0, "0"):
            return None
        try:
            expiry_number = float(expiry)
        except (TypeError, ValueError):
            text = str(expiry).strip()
            parsed = None
            for date_format in (
                "%Y-%m-%d %H:%M:%S",
                "%d-%m-%Y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%d-%m-%Y",
                "%d/%m/%Y",
            ):
                try:
                    parsed = datetime.strptime(text, date_format).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            if parsed is None:
                try:
                    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                except (TypeError, ValueError, OverflowError):
                    return None
            expiry_number = parsed.timestamp()
        if expiry_number > 10_000_000_000:
            expiry_number /= 1000
        return expiry_number > now_ts

    def package_metadata(value):
        """Yield package-level scalar fields while excluding benefit records."""
        if isinstance(value, dict):
            for key, nested in value.items():
                if key == "benefits":
                    continue
                if isinstance(nested, (dict, list)):
                    yield from package_metadata(nested)
                elif nested not in (None, ""):
                    yield str(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from package_metadata(nested)

    def package_expiry(value):
        """Yield expiry values from package metadata, never from benefits."""
        if isinstance(value, dict):
            for key, nested in value.items():
                if key == "benefits":
                    continue
                if "expir" in key.lower() or "valid_until" in key.lower():
                    if nested not in (None, "") and not isinstance(nested, (dict, list)):
                        yield nested
                elif isinstance(nested, (dict, list)):
                    yield from package_expiry(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from package_expiry(nested)

    for quota in quotas or []:
        metadata = " ".join(package_metadata(quota)).lower()
        compact_metadata = "".join(metadata.split())
        if "bonus" in compact_metadata or "xtracomboplus" not in compact_metadata:
            continue

        has_3gb_marker = "3gb" in compact_metadata or "3 gb" in metadata
        if not has_3gb_marker:
            for value in (
                quota.get("total"),
                quota.get("quota_total"),
                quota.get("quota_allocated"),
                quota.get("allocation"),
            ):
                try:
                    size = float(value)
                except (TypeError, ValueError):
                    continue
                if 2_850_000_000 <= size <= 3_250_000_000 or 2_800 <= size <= 3_300:
                    has_3gb_marker = True
                    break
        if not has_3gb_marker:
            continue

        package_expiry_values = list(package_expiry(quota))
        if not package_expiry_values:
            package_expiry_values = [quota.get("expired_at"), quota.get("quota_expired_at")]
        states = [expiry_state(value) for value in package_expiry_values]
        if False not in states:
            return True
    return False


def buy_addon(api_key, tokens, option_code):
    package = get_package(api_key, tokens, option_code)
    if not package:
        raise RuntimeError("Kode paket Instagram tidak ditemukan")

    option = package.get("package_option", {})
    family = package.get("package_family", {})
    price = int(option.get("price", 0) or 0)
    if price <= 0:
        raise RuntimeError("Harga paket tidak valid")

    balance = get_balance(api_key, tokens["id_token"])
    current_balance = int((balance or {}).get("remaining", 0) or 0)
    if current_balance < price:
        raise RuntimeError(f"Pulsa tidak cukup: Rp {current_balance:,} < Rp {price:,}")

    item = PaymentItem(
        item_code=option_code,
        product_type="",
        item_price=price,
        item_name=option.get("name", "Instagram add-on"),
        tax=0,
        token_confirmation=package.get("token_confirmation", ""),
    )
    result = settlement_balance(
        api_key, tokens, [item], family.get("payment_for") or "BUY_PACKAGE",
        ask_overwrite=False, overwrite_amount=price,
    )
    if not result or result.get("status") != "SUCCESS":
        message = result.get("message", "Pembelian gagal") if isinstance(result, dict) else "Pembelian gagal"
        raise RuntimeError(message)
    return option.get("name", "Instagram add-on"), price


def process_account(store, account, api_key):
    account_id = account["id"]
    result_prefix = {"number": account.get("number"), "notify_chat_id": account.get("notify_chat_id")}
    try:
        refresh_token = str(account.get("refresh_token", "") or "").strip()
        subscriber_id = str(account.get("subscriber_id", "") or "").strip()
        if not refresh_token:
            raise RuntimeError("refresh_token di Supabase kosong")
        if not subscriber_id:
            raise RuntimeError("subscriber_id di Supabase kosong")

        tokens = get_new_token(api_key, refresh_token, subscriber_id)
        if not tokens:
            raise RuntimeError("CIAM tidak mengembalikan token baru")

        quotas = get_quota_details(api_key, tokens["id_token"])
        remaining, found = instagram_remaining(quotas)
        store.update_account(account_id, {
            "refresh_token": tokens.get("refresh_token", account["refresh_token"]),
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
        })

        if not found:
            if not _xtra_combo_plus_3gb_available(quotas):
                message = "Paket induk Xtra Combo Plus 3GB tidak tersedia; add-on tidak dibeli"
                store.update_account(account_id, {
                    "locked_until": None,
                    "last_status": "quota_unavailable",
                    "last_error": message,
                })
                return {
                    **result_prefix,
                    "status": "quota_unavailable",
                    "remaining": 0,
                    "purchase_skipped": True,
                    "reason": "main_package_unavailable",
                }

            package_name, price = buy_addon(api_key, tokens, account["option_code"])
            store.update_account(account_id, {
                "locked_until": None,
                "last_purchase_at": datetime.now(timezone.utc).isoformat(),
                "last_status": "purchased",
                "last_error": None,
            })
            return {
                **result_prefix,
                "status": "purchased",
                "package": package_name,
                "price": price,
                "trigger": "quota_unavailable",
            }

        if remaining > IG_THRESHOLD:
            store.update_account(account_id, {"locked_until": None, "last_status": "ok", "last_error": None})
            return {**result_prefix, "status": "ok", "remaining": remaining}

        package_name, price = buy_addon(api_key, tokens, account["option_code"])
        store.update_account(account_id, {
            "locked_until": None,
            "last_purchase_at": datetime.now(timezone.utc).isoformat(),
            "last_status": "purchased",
            "last_error": None,
        })
        return {**result_prefix, "status": "purchased", "package": package_name, "price": price}
    except Exception as exc:
        store.update_account(account_id, {"locked_until": None, "last_status": "error", "last_error": str(exc)[:500]})
        return {**result_prefix, "status": "error", "error": str(exc)}




def run_auto_renew(api_key):
    store = SupabaseStore()
    accounts = store.claim_accounts()
    return [process_account(store, account, api_key) for account in accounts]
