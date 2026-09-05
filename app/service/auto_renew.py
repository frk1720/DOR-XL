import os
import random
import time
from datetime import datetime, timedelta, timezone

import requests

from app.client.ciam import get_new_token
from app.client.engsel import get_balance, get_package, send_api_request
from app.client.purchase.balance import settlement_balance
from app.type_dict import PaymentItem


# ---------------------------------------------------------------------------
# 🔒 TOKEN CACHE IN-MEMORY PER ACCOUNT (TTL 8 MENIT / 480 DETIK)
# ---------------------------------------------------------------------------
# Key: subscriber_id (str), Value: dict dengan tokens, obtained_at, expires_at
# Digunakan untuk menghindari call get_new_token() berulang ke CIAM XL tiap 30s.
# Hanya refresh token saat TTL habis atau saat error 401 (token invalid).
# ---------------------------------------------------------------------------
_TOKEN_CACHE = {}
DEFAULT_TTL_SECONDS = 480  # 8 menit sesuai lifespan id_token


def _get_cached_token(subscriber_id: str, api_key: str) -> dict | None:
    """
    Return cached tokens if still valid (< TTL).
    If cache expired or missing, return None to trigger refresh.
    """
    global _TOKEN_CACHE
    
    if not subscriber_id:
        return None
    
    entry = _TOKEN_CACHE.get(subscriber_id)
    if not entry:
        return None
    
    now = datetime.now(timezone.utc)
    if now >= entry["expires_at"]:
        # TTL sudah kadaluwarsa, hapus dari cache dan return None
        print(f"[{__name__}] Token expired for sub_id {subscriber_id[:8]}...")
        del _TOKEN_CACHE[subscriber_id]
        return None
    
    return entry.get("tokens")


def _set_cache_token(subscriber_id: str, tokens: dict):
    """
    Set new token into memory cache with TTL expiry.
    """
    global _TOKEN_CACHE
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=DEFAULT_TTL_SECONDS)
    
    _TOKEN_CACHE[subscriber_id] = {
        "tokens": tokens,
        "obtained_at": now,
        "expires_at": expires_at,
    }
    print(f"[{__name__}] Token cached for sub_id {subscriber_id[:8]}... (valid until ~{expires_at.strftime('%H:%M:%S')} UTC)")


def _clear_cache_token(subscriber_id: str):
    """
    Clear specific account's token from cache.
    Called when token is detected as invalid.
    """
    global _TOKEN_CACHE
    if subscriber_id in _TOKEN_CACHE:
        del _TOKEN_CACHE[subscriber_id]


def _get_fresh_tokens(api_key: str, refresh_token: str, subscriber_id: str) -> dict:
    """Minta token baru ke CIAM lalu simpan ke cache. Throw bila gagal."""
    tokens = get_new_token(api_key, refresh_token, subscriber_id)
    if not tokens:
        raise RuntimeError("CIAM tidak mengembalikan token baru")
    _set_cache_token(subscriber_id, tokens)
    return tokens


def _obtain_tokens(api_key: str, refresh_token: str, subscriber_id: str) -> dict:
    """Ambil token: pakai cache bila masih segar (<8 mnt), refresh bila perlu.

    Return dict tokens. Fungsi ini TIDAK menyentuh Supabase (hemat write I/O).
    """
    cached = _get_cached_token(subscriber_id, api_key)
    if cached:
        return cached
    return _get_fresh_tokens(api_key, refresh_token, subscriber_id)


QUOTA_PATH = "api/v8/packages/quota-details"
IG_THRESHOLD = 0  # Backward-compat constant; runtime threshold diambil dari env.
PURCHASE_COOLDOWN_SECONDS = 30 * 60


def _renew_threshold_bytes() -> int:
    """Ambang pembelian (byte). Default 0 = perilaku lama (renew hanya saat habis).

    Diset lewat env RENEW_THRESHOLD_MB agar worker bisa renew proaktif sebelum
    kuota benar-benar habis. Default 0 menjaga perilaku cron Vercel tetap sama.
    """
    raw = os.environ.get("RENEW_THRESHOLD_MB", "0")
    try:
        return max(0, int(float(raw) * 1024 * 1024))
    except (TypeError, ValueError):
        return 0


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

    def record_transaction(self, account, status, amount=0, package_name=None, error=None):
        chat_id = str(account.get("notify_chat_id", "") or "").strip()
        if not chat_id:
            return
        payload = {
            "account_id": account.get("id"),
            "number": account.get("number", ""),
            "notify_chat_id": chat_id,
            "option_code": account.get("option_code", ""),
            "package_name": package_name,
            "status": status,
            "amount": int(amount or 0),
            "error": str(error)[:500] if error else None,
        }
        response = requests.post(
            f"{self.url}/rest/v1/auto_renew_transactions",
            headers={**self.headers, "Prefer": "return=minimal"},
            json=payload,
            timeout=20,
        )
        response.raise_for_status()

    def monthly_transaction_summary(self, chat_id, year, month):
        wib = timezone(timedelta(hours=7))
        start = datetime(year, month, 1, tzinfo=wib)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=wib)
        else:
            end = datetime(year, month + 1, 1, tzinfo=wib)
        response = requests.get(
            f"{self.url}/rest/v1/auto_renew_transactions",
            headers=self.headers,
            params=[
                ("select", "number,status,amount,package_name,occurred_at,error"),
                ("notify_chat_id", f"eq.{str(chat_id)}"),
                ("occurred_at", f"gte.{start.isoformat()}"),
                ("occurred_at", f"lt.{end.isoformat()}"),
                ("order", "occurred_at.desc"),
            ],
            timeout=20,
        )
        response.raise_for_status()
        rows = response.json()
        summary = {}
        for row in rows:
            number = row.get("number", "-")
            item = summary.setdefault(number, {"success": 0, "failed": 0, "spent": 0})
            status = row.get("status")
            if status == "success":
                item["success"] += 1
                item["spent"] += int(row.get("amount", 0) or 0)
            elif status == "failed":
                item["failed"] += 1
        return {
            "rows": rows,
            "by_number": summary,
            "success": sum(item["success"] for item in summary.values()),
            "failed": sum(item["failed"] for item in summary.values()),
            "spent": sum(item["spent"] for item in summary.values()),
        }
def _record_transaction_safely(store, account, status, amount=0, package_name=None, error=None):
    try:
        store.record_transaction(account, status, amount, package_name, error)
    except Exception as exc:
        print(f"Auto-renew transaction ledger error: {exc.__class__.__name__}")



def _looks_like_token_error(result) -> bool:
    """Deteksi indikator token invalid dari respons API.

    `send_api_request` mengembalikan string mentah (resp.text) saat decrypt
    gagal — bisa karena token invalid (401) atau error teknis lain. Fast-path
    ini hanya memicu refresh token bila string memuat penanda 401/token.
    """
    if isinstance(result, dict):
        status = str(result.get("status", "")).upper()
        return "UNAUTHORIZED" in status or "TOKEN" in status
    if isinstance(result, str):
        lowered = result.lower()
        markers = (
            "401",
            "unauthorized",
            "invalid token",
            "token expired",
            "session expired",
            "access_token",
            "id_token",
        )
        return any(marker in lowered for marker in markers)
    return False


def _quota_error_message(result) -> str:
    """Susun pesan error kuota dari penyebab asli, bukan frasa generik."""
    if isinstance(result, dict):
        status = str(result.get("status", "")).upper()
        # Dari engsel.send_api_request: decrypt gagal / body tidak valid
        if status == "DECRYPT_FAILED":
            detail = result.get("error") or "decrypt respons gagal"
            return f"Gagal ambil kuota: {detail}"
        detail = (
            result.get("message")
            or result.get("error")
            or result.get("error_description")
            or ""
        )
        if detail:
            return f"Gagal ambil kuota: API XL menolak (status={status}): {detail}"
        return f"Gagal ambil kuota: status tidak SUCCESS (status={status})"
    if isinstance(result, str):
        snippet = result[:200]
        return f"Gagal ambil kuota: respons tidak valid: {snippet}"
    return "Gagal ambil kuota: respons tidak dikenal"

def get_quota_details(api_key, id_token, subscriber_id=None, refresh_token=None, _retry=True):
    """Ambil data kuota dari API XL.

    Self-healing: bila id_token sudah invalid di tengah polling (<8 mnt TTL),
    helper ini otomatis meminta token baru ke CIAM lalu mencoba sekali lagi,
    tanpa perlu menunggu siklus berikutnya.
    """
    result = send_api_request(
        api_key,
        QUOTA_PATH,
        {"is_enterprise": False, "lang": "en", "family_member_id": ""},
        id_token,
        "POST",
    )
    if isinstance(result, dict) and result.get("status") == "SUCCESS":
        return result.get("data", {}).get("quotas", [])

    # --- Token invalid / perlu refresh ---
    if _retry and subscriber_id and refresh_token and _looks_like_token_error(result):
        _clear_cache_token(subscriber_id)
        fresh = _get_fresh_tokens(api_key, refresh_token, subscriber_id)
        return get_quota_details(api_key, fresh["id_token"], _retry=False)

    if not isinstance(result, dict) or result.get("status") != "SUCCESS":
        raise RuntimeError(_quota_error_message(result))
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

def purchase_cooldown_remaining(last_purchase_at, now=None):
    """Return cooldown seconds remaining after the last successful purchase."""
    if last_purchase_at in (None, ""):
        return 0
    try:
        purchased_at = last_purchase_at
        if not isinstance(purchased_at, datetime):
            text = str(purchased_at).strip()
            try:
                purchased_at = datetime.fromtimestamp(float(text), tz=timezone.utc)
            except ValueError:
                purchased_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if purchased_at.tzinfo is None:
            purchased_at = purchased_at.replace(tzinfo=timezone.utc)
        current_time = now or datetime.now(timezone.utc)
        elapsed = (current_time - purchased_at).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return PURCHASE_COOLDOWN_SECONDS
    return min(PURCHASE_COOLDOWN_SECONDS, max(0, int(PURCHASE_COOLDOWN_SECONDS - elapsed + 0.999999)))

def _xtra_combo_plus_3gb_available(quotas, api_key=None, tokens=None):
    """Check the active main package, resolving names through quota details."""
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

    def quota_expiry(quota):
        """Read expiry only from the quota record, never from its benefits."""
        for field in (
            "expired_at",
            "quota_expired_at",
            "package_expired_at",
            "expiry_date",
            "valid_until",
        ):
            value = quota.get(field)
            if value not in (None, ""):
                return value
        return None

    for quota in quotas or []:
        detail = None
        metadata = " ".join(package_metadata(quota)).lower()
        compact_metadata = "".join(metadata.split())
        matches_main_name = "bonus" not in compact_metadata and "xtracomboplus" in compact_metadata
        matches_3gb = "3gb" in compact_metadata or "3 gb" in metadata

        if not matches_main_name or not matches_3gb:
            option_code = next(
                (
                    quota.get(field)
                    for field in ("quota_code", "package_option_code", "option_code")
                    if quota.get(field)
                ),
                None,
            )
            if option_code and api_key and tokens:
                detail = get_package(api_key, tokens, str(option_code))
                detail_metadata = " ".join(package_metadata(detail or {})).lower()
                detail_compact = "".join(detail_metadata.split())
                matches_main_name = (
                    "bonus" not in detail_compact
                    and "xtracomboplus" in detail_compact
                )
                matches_3gb = "3gb" in detail_compact or "3 gb" in detail_metadata

        if not matches_main_name or not matches_3gb:
            continue
        if expiry_state(quota_expiry(quota)) is not False:
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
    if __import__("os").getenv("DRY_RUN"):
        print("DRY RUN: payload valid, enkripsi OK")
        return option.get("name", "Instagram add-on"), price, None


    if __import__("os").getenv("DRY_RUN"):
        print("DRY RUN: payload valid, enkripsi OK")
        return option.get("name", "Instagram add-on"), price, None


    result = settlement_balance(
        api_key, tokens, [item], family.get("payment_for") or "BUY_PACKAGE",
        ask_overwrite=False, overwrite_amount=price,
    )
    if not result or result.get("status") != "SUCCESS":
        message = result.get("message", "Pembelian gagal") if isinstance(result, dict) else "Pembelian gagal"
        raise RuntimeError(message)

    # A successful purchase remains successful if the follow-up balance read
    # is unavailable; the notification will report the balance as unavailable.
    try:
        balance_after = get_balance(api_key, tokens["id_token"])
        try:
            remaining_after = int((balance_after or {}).get("remaining"))
        except (TypeError, ValueError):
            remaining_after = None
    except Exception:
        remaining_after = None
    return option.get("name", "Instagram add-on"), price, remaining_after


def process_account(store, account, api_key):
    account_id = account["id"]
    result_prefix = {"number": account.get("number"), "notify_chat_id": account.get("notify_chat_id")}
    purchase_attempted = False
    transaction_recorded = False
    try:
        refresh_token = str(account.get("refresh_token", "") or "").strip()
        subscriber_id = str(account.get("subscriber_id", "") or "").strip()
        if not refresh_token:
            raise RuntimeError("refresh_token di Supabase kosong")
        if not subscriber_id:
            raise RuntimeError("subscriber_id di Supabase kosong")

        # Ambil token: pakai cache in-memory bila masih valid (<8 mnt), baru
        # sentuh CIAM kalau cache kosong/kedaluwarsa. Hemat banget request auth.
        tokens = _obtain_tokens(api_key, refresh_token, subscriber_id)
        if not tokens:
            raise RuntimeError("CIAM tidak mengembalikan token baru")

        quotas = get_quota_details(
            api_key,
            tokens["id_token"],
            subscriber_id=subscriber_id,
            refresh_token=refresh_token,
        )
        remaining, found = instagram_remaining(quotas)
        # Supabase hanya di-update ketika refresh token benar-benar berubah
        # (rotasi refresh token dari CIAM) + waktu cek terakhir. Kalau pakai
        # cache (token tidak disentuh), kita hemat satu operasi PATCH.
        patch_values = {"last_checked_at": datetime.now(timezone.utc).isoformat()}
        new_refresh_token = tokens.get("refresh_token")
        if new_refresh_token and new_refresh_token != account["refresh_token"]:
            patch_values["refresh_token"] = new_refresh_token
        store.update_account(account_id, patch_values)

        cooldown_remaining = purchase_cooldown_remaining(account.get("last_purchase_at"))

        if not found:
            if not _xtra_combo_plus_3gb_available(quotas, api_key, tokens):
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

            if cooldown_remaining:
                store.update_account(account_id, {
                    "locked_until": None,
                    "last_status": "purchase_cooldown",
                    "last_error": None,
                })
                return {
                    **result_prefix,
                    "status": "purchase_cooldown",
                    "remaining": 0,
                    "purchase_skipped": True,
                    "reason": "purchase_cooldown",
                    "cooldown_remaining": cooldown_remaining,
                }

            purchase_attempted = True
            package_name, price, balance_remaining = buy_addon(api_key, tokens, account["option_code"])
            _record_transaction_safely(store, account, "success", price, package_name)
            transaction_recorded = True
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
                "balance_remaining": balance_remaining,
                "trigger": "quota_unavailable",
            }

        if remaining > _renew_threshold_bytes():
            store.update_account(account_id, {"locked_until": None, "last_status": "ok", "last_error": None})
            return {**result_prefix, "status": "ok", "remaining": remaining}

        purchase_attempted = True
        package_name, price, balance_remaining = buy_addon(api_key, tokens, account["option_code"])
        _record_transaction_safely(store, account, "success", price, package_name)
        transaction_recorded = True
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
            "balance_remaining": balance_remaining,
        }
    except Exception as exc:
        if purchase_attempted and not transaction_recorded:
            _record_transaction_safely(store, account, "failed", error=exc)
        store.update_account(account_id, {"locked_until": None, "last_status": "error", "last_error": str(exc)[:500]})
        return {**result_prefix, "status": "error", "error": str(exc), "purchase_attempted": purchase_attempted}




def run_auto_renew(api_key):
    store = SupabaseStore()
    accounts = store.claim_accounts()

    results = []
    for index, account in enumerate(accounts):
        result = process_account(store, account, api_key)
        results.append(result)
        # Staggering / nafas antar akun agar tidak terjadi burst request
        # serempak. Jeda acak 1.5-3.0 detik antar nomor; cukup lama untuk
        # terlihat natural di mata WAF, cukup cepat untuk tetap responsif.
        if index < len(accounts) - 1:
            breath = random.uniform(1.5, 3.0)
            print(
                f"[{__name__}] Staggering: istirahat {breath:.1f}s"
                f" sebelum akun berikutnya ({index + 2}/{len(accounts)})"
            )
            time.sleep(breath)
    return results
