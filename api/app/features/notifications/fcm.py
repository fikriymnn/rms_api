import logging
import threading
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from app.core.config import settings

log = logging.getLogger("rms.fcm")
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_lock = threading.Lock()
_creds: service_account.Credentials | None = None


def is_configured() -> bool:
    path = settings.fcm_service_account_file
    return bool(path) and Path(path).is_file()


def _credentials() -> service_account.Credentials:
    global _creds
    with _lock:
        if _creds is None:
            _creds = service_account.Credentials.from_service_account_file(
                settings.fcm_service_account_file, scopes=[_SCOPE]
            )
        if not _creds.valid:
            _creds.refresh(Request())
        return _creds


def build_message(item: dict) -> dict:
    return {
        "message": {
            "token": item["token"],
            "notification": {"title": item["title"], "body": item["body"]},
            "data": {
                k: str(v) for k, v in item["data"].items()
            },  # FCM hanya menerima string
            "android": {
                "priority": "HIGH",
                "notification": {"channel_id": item["channel"]},
            },
        }
    }


def send(item: dict) -> str:
    """Kembalikan 'ok', 'invalid' (token sudah mati: hapus), atau 'error'."""
    try:
        creds = _credentials()
        r = requests.post(
            f"https://fcm.googleapis.com/v1/projects/{creds.project_id}/messages:send",
            headers={"Authorization": f"Bearer {creds.token}"},
            json=build_message(item),
            timeout=10,
        )
    except Exception:
        log.exception("FCM: gagal mengirim")
        return "error"
    if r.status_code == 200:
        return "ok"
    try:
        err = r.json().get("error", {})
    except ValueError:
        err = {}
    text = str(err.get("message", "")).lower()
    if (
        r.status_code == 404
        or err.get("status") in ("NOT_FOUND", "UNREGISTERED")
        or (r.status_code == 400 and "registration token" in text)
    ):
        return "invalid"
    log.warning("FCM menolak (%s): %s", r.status_code, r.text[:300])
    return "error"
