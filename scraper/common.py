"""Shared helpers for the venue scrapers."""
import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TZ = ZoneInfo("Europe/Berlin")
HEADERS = {
    "User-Agent": "MuenchenSpielplan/1.0 (private, non-commercial event calendar; daily fetch)",
    "Accept-Language": "de-DE,de;q=0.9",
}
MONTHS_DE = {
    "jan": 1, "feb": 2, "mär": 3, "mar": 3, "apr": 4, "mai": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12,
}

session = requests.Session()
session.headers.update(HEADERS)
# sites occasionally time out from GitHub's servers: retry connection errors and 5xx a few times
_retry = Retry(total=3, connect=3, read=2, backoff_factor=3, status_forcelist=(502, 503, 504), allowed_methods=None)
session.mount("https://", HTTPAdapter(max_retries=_retry))
session.mount("http://", HTTPAdapter(max_retries=_retry))


def get(url, **kw):
    r = session.get(url, timeout=kw.pop("timeout", 60), **kw)
    r.raise_for_status()
    return r


def soup(url, **kw):
    return BeautifulSoup(get(url, **kw).text, "html.parser")


def text(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def absolute(base, href):
    return urljoin(base, href) if href else None


def local_dt(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


def parse_iso(s):
    """ISO string, with or without offset, interpreted as Munich time."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=TZ)


def find_time(s):
    """First HH:MM / HH.MM in a string, as (h, m), or None."""
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def duration_from_range(s):
    """'19.30–20.50 Uhr' -> 80"""
    m = re.search(r"(\d{1,2})[:.](\d{2})\s*[–-]\s*(\d{1,2})[:.](\d{2})", s or "")
    if not m:
        return None
    a = int(m.group(1)) * 60 + int(m.group(2))
    b = int(m.group(3)) * 60 + int(m.group(4))
    return (b - a) % (24 * 60) or None


def year_for_month(month, today=None):
    """Listings without a year: months before the current one belong to next year."""
    today = today or datetime.now(TZ)
    return today.year + 1 if month < today.month - 1 else today.year


def event(venue_id, title, start, **f):
    """Build an event dict in the format the frontend reads."""
    iso = start.isoformat(timespec="seconds")
    key = f"{venue_id}|{title}|{iso}|{f.get('stage') or ''}"
    return {
        "id": hashlib.sha1(key.encode()).hexdigest()[:12],
        "venue_id": venue_id,
        "title": title.strip(),
        "subtitle": f.get("subtitle") or None,
        "start": iso,
        "time_tbd": f.get("time_tbd", False),
        "stage": f.get("stage") or None,
        "genre": f.get("genre") or None,
        "tags": f.get("tags") or [],
        "status": f.get("status") or "unknown",
        "price": f.get("price") or None,
        "student_price": f.get("student_price") or None,
        "duration_min": f.get("duration_min") or None,
        "image": f.get("image") or None,
        "url": f.get("url") or None,
        "ticket_url": f.get("ticket_url") or None,
        "description": f.get("description") or None,
        "source": "page",
    }
