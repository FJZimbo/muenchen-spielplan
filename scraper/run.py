"""Scrape every venue and write site/data/events.json + status.json.

A venue that fails (or suddenly returns nothing) keeps its previous future events,
so one broken website never empties the programme.

    python scraper/run.py                 # all venues
    python scraper/run.py kammerspiele    # only these (others keep previous data)
"""
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import TZ  # noqa: E402
from images import add_images  # noqa: E402
from venues import SCRAPERS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
VENUES = json.loads((Path(__file__).parent / "venues.json").read_text())


def load_previous():
    try:
        return json.loads((OUT / "events.json").read_text())["events"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return []


def drop_hall_duplicates(events):
    """The Gasteig listing also contains the Philharmoniker's own Isarphilharmonie concerts.
    Keep the orchestra's entry (more detail) and drop the hall's copy."""
    orchestra = {e["start"] for e in events
                 if e["venue_id"] == "muenchner-philharmoniker" and "isarphilharmonie" in (e["stage"] or "").lower()}
    return [e for e in events if not (e["venue_id"] == "isarphilharmonie" and e["start"] in orchestra)]


def main(only):
    today = datetime.now(TZ).date().isoformat()
    previous = [e for e in load_previous() if e["start"][:10] >= today]
    events, status = [], {}
    for v in VENUES:
        vid = v["id"]
        old = [e for e in previous if e["venue_id"] == vid]
        if only and vid not in only:
            events += old
            continue
        try:
            new = [e for e in SCRAPERS[vid]() if e["start"][:10] >= today and e["title"]]
            if not new:
                raise RuntimeError("no events found (page layout changed?)")
            events += new
            status[vid] = {"ok": True, "count": len(new)}
            print(f"  ok   {vid:24} {len(new):4} events")
        except Exception as exc:  # keep going; report at the end
            events += old
            status[vid] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                           "kept_previous": bool(old), "count": len(old)}
            print(f"  FAIL {vid:24} {exc}  (kept {len(old)} previous)")
            traceback.print_exc(limit=2, file=sys.stderr)

    # same performance listed twice -> keep one
    unique = {e["id"]: e for e in events}
    events = drop_hall_duplicates(list(unique.values()))
    unique = {e["id"]: e for e in events}
    events = sorted(unique.values(), key=lambda e: (e["start"], e["venue_id"], e["title"]))
    add_images(events)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "events.json").write_text(json.dumps(
        {"generated_at": now, "venues": VENUES, "events": events}, ensure_ascii=False, separators=(",", ":")))
    (OUT / "status.json").write_text(json.dumps({"generated_at": now, "venues": status}, ensure_ascii=False, indent=1))
    print(f"wrote {len(events)} events")
    return 0 if any(s["ok"] for s in status.values()) or not status else 1


if __name__ == "__main__":
    sys.exit(main(set(sys.argv[1:])))
