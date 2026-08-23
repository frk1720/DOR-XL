import os
import json
import time
import threading
from datetime import datetime, timezone

import requests

from app.client.ciam import get_new_token
from app.client.engsel import get_profile

SESSION_FILE = "tg_sessions.json"
if os.environ.get("VERCEL"):
    SESSION_FILE = "/tmp/tg_sessions.json"

_lock = threading.Lock()


def _sync_auto_renew_account(number: str, subscriber_id: str, refresh_token: str):
    """Update an existing auto-renew row without creating unconfigured rows."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key or not number or not refresh_token:
        return

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Accept-Profile": "public",
        "Content-Profile": "public",
        "Prefer": "return=representation",
    }
    try:
        response = requests.patch(
            f"{supabase_url.rstrip('/')}/rest/v1/auto_renew_accounts?number=eq.{number}",
            headers=headers,
            json={
                "subscriber_id": subscriber_id or "",
                "refresh_token": refresh_token,
                "last_error": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            timeout=10,
        )
        response.raise_for_status()
        rows = response.json() if response.content else []
        if not rows:
            print(f"[auto-renew sync] row nomor {number} tidak ditemukan di Supabase")
        else:
            print(f"[auto-renew sync] row nomor {number} berhasil diperbarui")
    except Exception as exc:
        # Login must still succeed when Supabase is temporarily unavailable.
        print(f"[auto-renew sync] gagal menyinkronkan {number}: {exc}")

def _supabase_headers():
    """Headers REST untuk service-role Supabase; None saat env belum diset."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        return None
    return supabase_url.rstrip("/"), {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Accept-Profile": "public",
        "Content-Profile": "public",
    }


def _persist_session_row(uid: int, number: str, refresh_token: str, profile: dict, active: bool):
    """Upsert satu akun Telegram user ke Supabase; kegagalan tidak boleh memblokir login."""
    creds = _supabase_headers()
    if not creds or not number or not refresh_token:
        return
    url, headers = creds
    try:
        response = requests.post(
            f"{url}/rest/v1/rpc/upsert_tg_user_account",
            headers=headers,
            json={
                "p_telegram_id": str(uid),
                "p_number": number,
                "p_refresh_token": refresh_token,
                "p_profile": profile or {},
                "p_active": bool(active),
            },
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[tg-session sync] gagal upsert {number}: {exc.__class__.__name__}")


def _delete_session_row(uid: int, number: str):
    """Hapus satu akun dari Supabase; kegagalan tidak boleh memblokir logout."""
    creds = _supabase_headers()
    if not creds or not number:
        return
    url, headers = creds
    try:
        response = requests.delete(
            f"{url}/rest/v1/tg_user_accounts",
            headers=headers,
            params={"telegram_id": f"eq.{str(uid)}", "number": f"eq.{number}"},
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[tg-session sync] gagal delete {number}: {exc.__class__.__name__}")


def _load_session_rows(uid: int) -> list:
    """Ambil seluruh akun tersimpan milik satu Telegram user; return [] saat gagal."""
    creds = _supabase_headers()
    if not creds:
        return []
    url, headers = creds
    try:
        response = requests.get(
            f"{url}/rest/v1/tg_user_accounts",
            headers=headers,
            params={"telegram_id": f"eq.{str(uid)}", "select": "number,refresh_token,profile,active"},
            timeout=10,
        )
        response.raise_for_status()
        rows = response.json() or []
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        print(f"[tg-session sync] gagal load akun uid {uid}: {exc.__class__.__name__}")
        return []


def _load_store() -> dict:
    if not os.path.exists(SESSION_FILE):
        return {"users": {}}
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "users" not in data:
                data["users"] = {}
            return data
    except Exception:
        return {"users": {}}


def _save_store(store: dict):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


class TgSessionManager:
    """Per-Telegram-user session manager (multi-user safe).

    Keeps tokens in memory and persists refresh tokens to tg_sessions.json
    so users stay logged in across bot restarts. Supports multiple accounts.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.sessions = {}  # telegram_user_id -> session dict
        store = _load_store()
        for uid, u in store["users"].items():
            # Legacy migration
            if "refresh_token" in u:
                number = u.get("profile", {}).get("number", "unknown")
                u = {
                    "active_number": number,
                    "accounts": {
                        number: {
                            "refresh_token": u["refresh_token"],
                            "profile": u.get("profile"),
                        }
                    }
                }

            sess = {
                "active_number": u.get("active_number"),
                "accounts": {},
                "pending_contact": None,
                "pending_wallet": None,
                "pending_action": None,
            }
            for num, acc in u.get("accounts", {}).items():
                sess["accounts"][num] = {
                    "refresh_token": acc.get("refresh_token"),
                    "tokens": None,
                    "profile": acc.get("profile"),
                    "last_refresh": 0,
                }
            self.sessions[int(uid)] = sess

    # ---------- persistence ----------
    def _persist(self, uid: int):
        store = _load_store()
        sess = self.sessions.get(uid)
        if sess and sess.get("accounts"):
            u_store = {
                "active_number": sess.get("active_number"),
                "accounts": {}
            }
            for num, acc in sess["accounts"].items():
                if acc.get("refresh_token"):
                    u_store["accounts"][num] = {
                        "refresh_token": acc["refresh_token"],
                        "profile": acc.get("profile")
                    }
            store["users"][str(uid)] = u_store
        else:
            store["users"].pop(str(uid), None)
        _save_store(store)

    # ---------- session helpers ----------
    def get_session(self, uid: int) -> dict:
        if uid not in self.sessions:
            self.sessions[uid] = {
                "active_number": None,
                "accounts": {},
                "pending_contact": None,
                "pending_wallet": None,
                "pending_action": None,
            }
            self._hydrate_from_supabase(uid)
        return self.sessions[uid]

    def is_logged_in(self, uid: int) -> bool:
        sess = self.get_session(uid)
        active = sess.get("active_number")
        if not active or active not in sess.get("accounts", {}):
            return False
        return bool(sess["accounts"][active].get("refresh_token"))

    def login(self, uid: int, tokens: dict, number: str = ""):
        sess = self.get_session(uid)
        profile_data = get_profile(self.api_key, tokens["access_token"], tokens["id_token"])
        
        prof = {
            "number": number,
            "subscriber_id": "",
            "subscription_type": "",
        }
        if profile_data and "profile" in profile_data:
            p = profile_data["profile"]
            prof["number"] = p.get("msisdn") or number
            prof["subscriber_id"] = p.get("subscriber_id", "")
            prof["subscription_type"] = p.get("subscription_type", "")
            
        active_num = prof["number"]
        if not active_num:
            active_num = "unknown"
            
        sess["accounts"][active_num] = {
            "refresh_token": tokens["refresh_token"],
            "tokens": tokens,
            "profile": prof,
            "last_refresh": int(time.time()),
        }
        sess["active_number"] = active_num
        self._persist(uid)
        _persist_session_row(
            uid,
            active_num,
            tokens["refresh_token"],
            prof,
            active=True,
        )
        _sync_auto_renew_account(
            active_num,
            prof.get("subscriber_id", ""),
            tokens.get("refresh_token", ""),
        )
        return sess

    def get_all_accounts(self, uid: int) -> dict:
        sess = self.get_session(uid)
        return sess.get("accounts", {})
        
    def switch_account(self, uid: int, number: str) -> bool:
        sess = self.get_session(uid)
        if number in sess.get("accounts", {}):
            sess["active_number"] = number
            self._persist(uid)
            _persist_session_row(
                uid,
                number,
                sess["accounts"][number].get("refresh_token", ""),
                sess["accounts"][number].get("profile", {}),
                active=True,
            )
            return True
        return False

    def logout(self, uid: int, number: str = ""):
        sess = self.get_session(uid)
        if not number:
            number = sess.get("active_number")

        if number in sess.get("accounts", {}):
            del sess["accounts"][number]

            # Update active_number
            if sess.get("active_number") == number:
                if sess["accounts"]:
                    sess["active_number"] = list(sess["accounts"].keys())[0]
                else:
                    sess["active_number"] = None
            self._persist(uid)
            _delete_session_row(uid, number)
            return True
        return False

    def get_tokens(self, uid: int) -> dict | None:
        """Return valid tokens for a telegram user's active account, refreshing when needed."""
        with _lock:
            sess = self.sessions.get(uid)
            if not sess:
                return None
            active = sess.get("active_number")
            if not active or active not in sess.get("accounts", {}):
                return None
                
            acc = sess["accounts"][active]
            if not acc.get("refresh_token"):
                return None

            need_refresh = (
                acc.get("tokens") is None
                or (int(time.time()) - acc.get("last_refresh", 0)) > 300
            )
            if need_refresh:
                subscriber_id = acc.get("profile", {}).get("subscriber_id", "")
                tokens = get_new_token(self.api_key, acc["refresh_token"], subscriber_id)
                if not tokens:
                    return None
                acc["tokens"] = tokens
                acc["refresh_token"] = tokens["refresh_token"]
                acc["last_refresh"] = int(time.time())
                self._persist(uid)
                _persist_session_row(
                    uid,
                    active,
                    tokens["refresh_token"],
                    acc.get("profile", {}),
                    active=True,
                )
                _sync_auto_renew_account(
                    active,
                    acc.get("profile", {}).get("subscriber_id", ""),
                    tokens.get("refresh_token", ""),
                )

            return acc["tokens"]

    def get_profile_info(self, uid: int) -> dict | None:
        sess = self.sessions.get(uid)
        if not sess:
            return None
        active = sess.get("active_number")
        if not active or active not in sess.get("accounts", {}):
            return None
        return sess["accounts"][active].get("profile")


TgSessionInstance = None


def init_tg_sessions(api_key: str) -> TgSessionManager:
    global TgSessionInstance
    TgSessionInstance = TgSessionManager(api_key)
    return TgSessionInstance
