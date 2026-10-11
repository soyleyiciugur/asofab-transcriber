"""Google OAuth + Meet REST v2 + Drive v3 access.

Only read-only scopes are requested. Recordings are never modified.
Tokens are stored in the OS keyring when available, else in a user-only file.
Access tokens are never logged.
"""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Optional

import requests

from .config import app_dir

SCOPES = [
    "https://www.googleapis.com/auth/meetings.space.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
MEET = "https://meet.googleapis.com/v2"
DRIVE = "https://www.googleapis.com/drive/v3"
KEYRING_SERVICE = "asofab-transcriber"


class GoogleError(Exception):
    """User-presentable Google API failure."""

    def __init__(self, message: str, code: str = "error", status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


# ---------------------------------------------------------------- credentials


def client_secret_path() -> Path:
    return app_dir() / "client_secret.json"


def _token_file() -> Path:
    return app_dir() / "token.json"


def _store_token(data: str) -> None:
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, "oauth_token", data)
        return
    except Exception:
        pass
    p = _token_file()
    p.write_text(data, encoding="utf-8")
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def _load_token() -> Optional[str]:
    try:
        import keyring
        v = keyring.get_password(KEYRING_SERVICE, "oauth_token")
        if v:
            return v
    except Exception:
        pass
    p = _token_file()
    return p.read_text(encoding="utf-8") if p.exists() else None


def sign_out() -> None:
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, "oauth_token")
    except Exception:
        pass
    if _token_file().exists():
        _token_file().unlink()


def have_client_secret() -> bool:
    return client_secret_path().exists()


def install_client_secret(text: str) -> None:
    data = json.loads(text)
    if "installed" not in data:
        raise GoogleError(
            "This client_secret.json is not a Desktop-app OAuth client "
            "(it must contain an 'installed' section). Create a 'Desktop app' client.",
            "bad_client_secret")
    client_secret_path().write_text(text, encoding="utf-8")


def connect_interactive() -> None:
    """Runs the loopback OAuth flow; opens the system browser."""
    if not have_client_secret():
        raise GoogleError(
            "No Google OAuth client configured. Follow SETUP_GOOGLE.md and import client_secret.json.",
            "no_client_secret")
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path()), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", open_browser=True)
    _store_token(creds.to_json())


def _credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    raw = _load_token()
    if not raw:
        raise GoogleError("Not signed in to Google. Click 'Connect Google Account'.", "not_signed_in")
    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if not creds.valid:
        if creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                raise GoogleError(
                    "Google sign-in expired or was revoked. Reconnect your account. "
                    "(If the OAuth app is in 'Testing' mode, tokens expire after 7 days.)",
                    "token_expired")
            _store_token(creds.to_json())
        else:
            raise GoogleError("Google sign-in expired. Reconnect your account.", "token_expired")
    return creds


def is_signed_in() -> bool:
    try:
        _credentials()
        return True
    except Exception:  # missing libs or corrupt token must never break the status page
        return False


def _headers() -> dict:
    return {"Authorization": f"Bearer {_credentials().token}"}


def _explain(resp: requests.Response, what: str) -> GoogleError:
    try:
        err = resp.json().get("error", {})
        msg = err.get("message", resp.text[:200])
        reason = (err.get("errors") or [{}])[0].get("reason") or err.get("status", "")
    except Exception:
        msg, reason = resp.text[:200], ""
    s = resp.status_code
    if s == 401:
        return GoogleError("Google rejected the sign-in. Reconnect your account.", "unauthorized", s)
    if s == 403:
        if "has not been used" in msg or "disabled" in msg.lower():
            return GoogleError(
                f"{what}: the API is not enabled in your Google Cloud project. "
                "Enable 'Google Meet REST API' and 'Google Drive API' (see SETUP_GOOGLE.md).",
                "api_disabled", s)
        return GoogleError(
            f"{what}: permission denied. Only the meeting organizer/participants (or the file's "
            f"viewers) can read this. Google says: {msg}", "forbidden", s)
    if s == 404:
        return GoogleError(
            f"{what}: not found. It may be deleted, expired (Meet conference records have limited "
            "retention) or not shared with this Google account.", "not_found", s)
    if s == 429:
        return GoogleError(f"{what}: Google rate limit hit. Retry in a minute.", "rate_limited", s)
    return GoogleError(f"{what}: HTTP {s} {reason} {msg}", "http_error", s)


def _get(url: str, what: str, **params) -> dict:
    r = requests.get(url, headers=_headers(), params=params, timeout=60)
    if not r.ok:
        raise _explain(r, what)
    return r.json()


def _paged(url: str, key: str, what: str, **params) -> Iterator[dict]:
    token = None
    while True:
        p = dict(params)
        if token:
            p["pageToken"] = token
        data = _get(url, what, **p)
        for item in data.get(key, []):
            yield item
        token = data.get("nextPageToken")
        if not token:
            return


# ---------------------------------------------------------------------- Meet


def list_conference_records(meeting_code: str) -> list[dict]:
    flt = f'space.meeting_code = "{meeting_code}"'
    return list(_paged(f"{MEET}/conferenceRecords", "conferenceRecords",
                       "Searching conference records", filter=flt, pageSize=100))


def get_conference_record(name: str) -> dict:
    if not name.startswith("conferenceRecords/"):
        name = f"conferenceRecords/{name}"
    return _get(f"{MEET}/{name}", "Reading conference record")


def list_recordings(record: str) -> list[dict]:
    return list(_paged(f"{MEET}/{record}/recordings", "recordings", "Listing recordings"))


def list_participants(record: str) -> list[dict]:
    return list(_paged(f"{MEET}/{record}/participants", "participants", "Listing participants"))


def list_participant_sessions(participant: str) -> list[dict]:
    return list(_paged(f"{MEET}/{participant}/participantSessions", "participantSessions",
                       "Listing participant sessions"))


def list_transcripts(record: str) -> list[dict]:
    return list(_paged(f"{MEET}/{record}/transcripts", "transcripts", "Listing transcripts"))


def list_transcript_entries(transcript: str) -> list[dict]:
    return list(_paged(f"{MEET}/{transcript}/entries", "transcriptEntries",
                       "Reading transcript entries", pageSize=100))


def participant_label(p: dict) -> dict:
    """Normalise a participant into {name, display, kind, user}."""
    if "signedinUser" in p:
        u = p["signedinUser"]
        return {"name": p["name"], "display": u.get("displayName", ""), "kind": "signed_in",
                "user": u.get("user", "")}
    if "anonymousUser" in p:
        return {"name": p["name"], "display": p["anonymousUser"].get("displayName", ""),
                "kind": "anonymous", "user": ""}
    if "phoneUser" in p:
        return {"name": p["name"], "display": p["phoneUser"].get("displayName", ""),
                "kind": "phone", "user": ""}
    return {"name": p.get("name", ""), "display": "", "kind": "unknown", "user": ""}


def _parse_ts(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    s = re.sub(r"\.\d+", "", s).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def record_duration_s(rec: dict) -> Optional[float]:
    a, b = _parse_ts(rec.get("startTime")), _parse_ts(rec.get("endTime"))
    return (b - a).total_seconds() if a and b else None


def pick_best_record(records: list[dict], drive_meta: dict | None = None,
                     hint_date: str | None = None, hint_duration_s: float | None = None) -> dict | None:
    """Choose the conference record that best matches a date or duration hint.

    With no hints, return the most recent. Callers should show all candidates so
    the user can override the choice.
    """
    if not records:
        return None
    scored = []
    for r in records:
        score = 0.0
        start = _parse_ts(r.get("startTime"))
        dur = record_duration_s(r)
        if hint_date and start and start.date().isoformat() == hint_date:
            score += 10
        if hint_duration_s and dur:
            score += max(0.0, 5 - abs(dur - hint_duration_s) / 60.0)  # minutes off
        if drive_meta and start:
            created = _parse_ts(drive_meta.get("createdTime"))
            if created:
                delta_h = abs((created - start).total_seconds()) / 3600.0
                score += max(0.0, 8 - delta_h)
        scored.append((score, start or datetime.min.replace(tzinfo=None), r))
    scored.sort(key=lambda t: (t[0], str(t[1])), reverse=True)
    return scored[0][2]


# --------------------------------------------------------------------- Drive


def drive_file_meta(file_id: str) -> dict:
    return _get(f"{DRIVE}/files/{file_id}", "Reading Drive file", supportsAllDrives="true",
                fields="id,name,mimeType,size,createdTime,modifiedTime,videoMediaMetadata,trashed,owners")


def download_drive_file(file_id: str, dest: Path,
                        progress: Callable[[int, int], None] | None = None,
                        chunk: int = 8 * 1024 * 1024) -> Path:
    """Download with resume support. Writes to dest.part, then renames."""
    meta = drive_file_meta(file_id)
    if meta.get("trashed"):
        raise GoogleError("This Drive file is in the trash.", "deleted")
    total = int(meta.get("size", 0))
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    if dest.exists() and total and dest.stat().st_size == total:
        return dest
    if total and have > total:
        part.unlink()
        have = 0
    url = f"{DRIVE}/files/{file_id}"
    with open(part, "ab") as f:
        while not total or have < total:
            h = _headers()
            h["Range"] = f"bytes={have}-{have + chunk - 1}"
            r = requests.get(url, headers=h, params={"alt": "media", "supportsAllDrives": "true"},
                             timeout=120, stream=True)
            if r.status_code == 416:
                break
            if not r.ok:
                raise _explain(r, "Downloading recording")
            if r.status_code == 200 and have > 0:
                # Server ignored the Range header and is sending the whole file: start over.
                f.truncate(0)
                f.seek(0)
                have = 0
            n = 0
            for block in r.iter_content(1 << 20):
                f.write(block)
                n += len(block)
            have += n
            if progress:
                progress(have, total)
            if n == 0:
                break
    if total and part.stat().st_size != total:
        raise GoogleError("Download ended early. Run the stage again to resume.", "partial_download")
    part.replace(dest)
    return dest
