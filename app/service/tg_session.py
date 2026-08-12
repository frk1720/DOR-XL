import os
import json
import time
import threading

from app.client.ciam import get_new_token
from app.client.engsel import get_profile

SESSION_FILE = "tg_sessions.json"
if os.environ.get("VERCEL"):
    SESSION_FILE = "/tmp/tg_sessions.json"

_lock = threading.Lock()


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
    so users stay logged in across bot restarts.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.sessions = {}  # telegram_user_id -> session dict
        store = _load_store()
        for uid, u in store["users"].items():
            self.sessions[int(uid)] = {
                "refresh_token": u.get("refresh_token"),
                "tokens": None,
                "profile": u.get("profile"),
                "last_refresh": 0,
                "pending_contact": None,
                "pending_wallet": None,
            }

    # ---------- persistence ----------
    def _persist(self, uid: int):
        store = _load_store()
        sess = self.sessions.get(uid)
        if sess and sess.get("refresh_token"):
            store["users"][str(uid)] = {
                "refresh_token": sess["refresh_token"],
                "profile": sess.get("profile"),
            }
        else:
            store["users"].pop(str(uid), None)
        _save_store(store)

    # ---------- session helpers ----------
    def get_session(self, uid: int) -> dict:
        if uid not in self.sessions:
            self.sessions[uid] = {
                "refresh_token": None,
                "tokens": None,
                "profile": None,
                "last_refresh": 0,
                "pending_contact": None,
                "pending_wallet": None,
            }
        return self.sessions[uid]

    def is_logged_in(self, uid: int) -> bool:
        return bool(self.sessions.get(uid, {}).get("refresh_token"))

    def login(self, uid: int, tokens: dict, number: str = ""):
        sess = self.get_session(uid)
        sess["refresh_token"] = tokens["refresh_token"]
        sess["tokens"] = tokens
        profile_data = get_profile(self.api_key, tokens["access_token"], tokens["id_token"])
        if profile_data and "profile" in profile_data:
            p = profile_data["profile"]
            sess["profile"] = {
                "number": p.get("msisdn") or number,
                "subscriber_id": p.get("subscriber_id", ""),
                "subscription_type": p.get("subscription_type", ""),
            }
        elif number:
            sess["profile"] = {
                "number": number,
                "subscriber_id": "",
                "subscription_type": "",
            }
        sess["last_refresh"] = int(time.time())
        self._persist(uid)
        return sess

    def logout(self, uid: int):
        self.sessions.pop(uid, None)
        self._persist(uid)

    def get_tokens(self, uid: int) -> dict | None:
        """Return valid tokens for a telegram user, refreshing when needed."""
        with _lock:
            sess = self.sessions.get(uid)
            if not sess or not sess.get("refresh_token"):
                return None

            need_refresh = (
                sess.get("tokens") is None
                or (int(time.time()) - sess.get("last_refresh", 0)) > 300
            )
            if need_refresh:
                subscriber_id = ""
                if sess.get("profile"):
                    subscriber_id = sess["profile"].get("subscriber_id", "")
                tokens = get_new_token(self.api_key, sess["refresh_token"], subscriber_id)
                if not tokens:
                    return None
                sess["tokens"] = tokens
                sess["refresh_token"] = tokens["refresh_token"]
                sess["last_refresh"] = int(time.time())
                self._persist(uid)

            return sess["tokens"]

    def get_profile_info(self, uid: int) -> dict | None:
        sess = self.sessions.get(uid)
        if not sess:
            return None
        return sess.get("profile")


TgSessionInstance = None


def init_tg_sessions(api_key: str) -> TgSessionManager:
    global TgSessionInstance
    TgSessionInstance = TgSessionManager(api_key)
    return TgSessionInstance
