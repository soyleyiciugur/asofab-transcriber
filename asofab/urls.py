"""Parse Google Meet / Drive links and conference-record identifiers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

MEET_CODE_RE = re.compile(r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$")
DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")
CONF_RECORD_RE = re.compile(r"^(?:conferenceRecords/)?([A-Za-z0-9_-]{6,})$")


@dataclass
class ParsedLink:
    kind: str  # meet_code | drive_file | conference_record | unsupported
    value: str = ""
    explanation: str = ""


def parse_link(raw: str) -> ParsedLink:
    raw = (raw or "").strip()
    if not raw:
        return ParsedLink("unsupported", "", "Nothing was entered.")

    if raw.startswith("conferenceRecords/"):
        return ParsedLink(
            "conference_record", raw.split("/", 1)[1],
            "A Meet conference-record identifier: this names one historical meeting instance.")

    if "://" not in raw:
        low = raw.lower()
        if MEET_CODE_RE.match(low):
            return _meet(low)
        if DRIVE_ID_RE.match(raw):
            return _drive(raw)
        return ParsedLink("unsupported", "", "Could not recognise this as a Meet code, Drive ID or URL.")

    u = urlparse(raw)
    host = (u.hostname or "").lower()
    path = u.path

    if host == "meet.google.com":
        code = path.strip("/").split("/")[0].lower()
        if MEET_CODE_RE.match(code):
            return _meet(code)
        return ParsedLink("unsupported", "", "Meet URL without a valid meeting code (expected xxx-xxxx-xxx).")

    if host in ("drive.google.com", "docs.google.com"):
        m = re.search(r"/(?:file|document|presentation|spreadsheets)/d/([A-Za-z0-9_-]+)", path)
        if m:
            return _drive(m.group(1))
        q = parse_qs(u.query)
        for key in ("id", "fileId"):
            if key in q and q[key]:
                return _drive(q[key][0])
        m = re.search(r"/drive/(?:u/\d+/)?folders/", path)
        if m:
            return ParsedLink("unsupported", "", "This is a Drive folder, not a recording file. Open the recording and copy its link.")
        return ParsedLink("unsupported", "", "Unrecognised Drive URL shape.")

    return ParsedLink("unsupported", "", f"Unsupported host: {host or 'unknown'}")


def _meet(code: str) -> ParsedLink:
    return ParsedLink(
        "meet_code", code,
        "A Meet meeting URL identifies a meeting ROOM, not one recording. The app will search "
        "historical conference records for this code and pick the matching instance.")


def _drive(file_id: str) -> ParsedLink:
    return ParsedLink(
        "drive_file", file_id,
        "A Drive file link identifies one specific recording file (a historical recording).")
