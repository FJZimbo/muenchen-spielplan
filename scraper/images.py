"""Fill in missing cover images from each event's detail page (its og:image).

Results are cached in image_cache.json (page URL -> image URL, "" = page has none),
so each production page is only fetched once.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from common import get

CACHE = Path(__file__).parent / "image_cache.json"
MAX_NEW_PER_RUN = 250
GENERIC = re.compile(r"social-image-default|logo", re.I)


def _page_key(url):
    return url.split("?")[0].split("#")[0]


def _og_image(url):
    page = BeautifulSoup(get(url, timeout=40).text, "html.parser")
    tag = page.find("meta", property="og:image") or page.find("meta", attrs={"name": "twitter:image"})
    src = tag.get("content") if tag else None
    if not src or GENERIC.search(src):
        return ""
    src = urljoin(url, src)
    return re.sub(r"([?&]w=)\d+", r"\g<1>800", src)  # Kammerspiele serves 2000px by default


def add_images(events):
    try:
        cache = json.loads(CACHE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    fetched = 0
    for e in events:
        if e["image"] or not e["url"] or "muenchenticket" in e["url"]:
            continue
        key = _page_key(e["url"])
        if key not in cache and fetched < MAX_NEW_PER_RUN:
            try:
                cache[key] = _og_image(key)
            except Exception as exc:  # leave uncached; retried next run
                print(f"  image: {key}: {exc}")
                continue
            fetched += 1
            time.sleep(0.3)
        e["image"] = cache.get(key) or None
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True))
    print(f"  images: {fetched} pages fetched, {sum(1 for e in events if e['image'])}/{len(events)} events have a cover")
