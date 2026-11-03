"""One scraper per venue. Each returns a list of event dicts (see common.event)."""
import difflib
import html
import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup

from common import (MONTHS_DE, TZ, absolute, duration_from_range, event, find_time, get,
                    local_dt, parse_iso, session, soup, text, year_for_month)

MONTH_NAMES = ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
               "september", "oktober", "november", "dezember"]


def _status_from_text(s):
    s = (s or "").lower()
    if "entfällt" in s or "abgesagt" in s:
        return "cancelled"
    if "ausverkauft" in s:
        return "sold_out"
    if "restkarten" in s or "wenige" in s:
        return "few"
    return "unknown"


# ---------------------------------------------------------------- Residenztheater
def residenztheater():
    base = "https://www.residenztheater.de/spielplan"
    out, seen, queue = [], set(), [base]
    while queue and len(seen) < 8:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        page = soup(url)
        m = re.search(r"month=(\d{4})-(\d{2})", url)
        year = int(m.group(1)) if m else datetime.now(TZ).year
        for a in page.select(".pagination__item a[href*='month=']"):
            nxt = absolute(base, a["href"].split("#")[0])
            if nxt not in seen and nxt not in queue:
                queue.append(nxt)
        for act in page.select("article.schedule-act"):
            dm = re.search(r"(\d{1,2})\.?\s+([A-Za-zä]{3})", text(act.select_one(".schedule-act__date")))
            details = text(act.select_one(".schedule-act__details"))
            if not dm or "geschlossene" in details.lower():
                continue
            page_month = int(m.group(2)) if m else datetime.now(TZ).month
            month = MONTHS_DE.get(dm.group(2).lower()[:3], page_month)
            y = year + 1 if month < page_month else year
            hm = find_time(details)
            start = local_dt(y, month, int(dm.group(1)), *(hm or (0, 0)))
            link = act.select_one(".schedule-act__title a")
            cards = act.select_one(".schedule-act__cards-info")
            cards_txt = text(cards)
            cta = cards.select_one("a.schedule-act__cta") if cards else None
            cat = act.select_one(".schedule-act__category")
            price = text(cat).replace(text(cat.select_one(".schedule-act__price")), "").strip() if cat else ""
            price = re.sub(r"(\d+)\s*bis\s*(\d+)", r"\1–\2", price)
            img = act.select_one(".schedule-act__description-image img")
            out.append(event(
                "residenztheater",
                text(link).replace(text(link.select_one(".visuallyhidden")), "").strip(),
                start,
                time_tbd=hm is None,
                stage=details.split(",")[0].strip() if "," in details else None,
                subtitle=text(act.select_one(".schedule-act__author")),
                tags=[text(x) for x in act.select(".schedule-act__label")],
                status=_status_from_text(cards_txt),
                price="free" if "eintritt frei" in cards_txt.lower() else price,
                duration_min=duration_from_range(details),
                image=absolute(base, img.get("src")) if img else None,
                url=absolute(base, link.get("href")),
                ticket_url=cta.get("href") if cta and cta.get("href", "").startswith("http") else None,
            ))
    return out


# ---------------------------------------------------------------- Münchner Kammerspiele
MK_TAGS = {"Premiere": "Premiere", "UA": "Uraufführung", "Englische Übertitel": "English surtitles",
           "Wiederaufnahme": "Wiederaufnahme", "Zum letzten Mal": "Zum letzten Mal"}


def kammerspiele():
    base = "https://www.muenchner-kammerspiele.de/de/programm"
    page = soup(base)
    out = []
    for group in page.select(".events-group[data-date]"):
        y, mo, d = map(int, group["data-date"].split("-"))
        for li in group.select("li.preview-event"):
            link = li.select_one(".preview-event__title")
            paras = [text(p) for p in li.select(".preview-event__text p")]
            when = next((p for p in reversed(paras) if find_time(p)), "")
            hm = find_time(when)
            stage = re.sub(r"^[\d:\s–-]+", "", when).strip() or None
            btn = li.select_one(".event-button--ticket")
            btn_txt = text(btn)
            status = _status_from_text(btn_txt + " " + " ".join(paras))
            if status == "unknown" and "wenige" in btn_txt.lower():
                status = "few"
            labels = [text(x) for x in li.select(".event-label")]
            out.append(event(
                "kammerspiele", text(link), local_dt(y, mo, d, *(hm or (0, 0))),
                time_tbd=hm is None,
                stage=stage,
                subtitle=paras[0] if len(paras) > 1 else None,
                tags=[MK_TAGS[x] for x in labels if x in MK_TAGS],
                status=status,
                price="free" if "kostenfrei" in btn_txt.lower() else None,
                duration_min=duration_from_range(when),
                url=absolute(base, link.get("href")),
                ticket_url=btn.get("href") if btn and btn.get("href", "").startswith("http") else None,
            ))
    return out


# ---------------------------------------------------------------- Münchner Volkstheater
def volkstheater():
    base = "https://www.muenchner-volkstheater.de/programm/spielplan"
    page = soup(base)
    out = []
    for mw in page.select(".schedule--month-wrapper"):
        month = MONTH_NAMES.index(text(mw.select_one(".schedule--month-title")).lower()) + 1
        year = year_for_month(month)
        for day in mw.select(".schedule--day-wrapper"):
            d = int(text(day.select_one(".schedule--day")))
            for row in day.select(".schedule--day-content"):
                link = row.select_one(".schedule--title a")
                if not link:
                    continue
                hm = find_time(text(row.select_one(".field-event-time")))
                col = row.select_one("[class*='event-type--']")
                kinds = [c.split("--")[1] for c in (col.get("class") if col else []) if c.startswith("event-type--")]
                genre = next((k for k in kinds if k not in ("repertoire", "extra")), None)
                dot = row.select_one(".availability-dot")
                dot_cls = " ".join(dot.get("class", [])) if dot else ""
                tix = row.select_one("a.schedule--tickets-link")
                special = text(row.select_one(".schedule__special-information"))
                if "cancelled" in dot_cls or "entfällt" in special.lower():
                    status = "cancelled"
                elif tix and "sold-out" in tix.get("class", []):
                    status = "sold_out"
                elif "yellow" in dot_cls or "red" in dot_cls:
                    status = "few"
                elif "green" in dot_cls:
                    status = "available"
                else:
                    status = "unknown"
                notes = text(row.select_one(".field-event-notes"))
                out.append(event(
                    "volkstheater", text(link), local_dt(year, month, d, *(hm or (0, 0))),
                    time_tbd=hm is None,
                    stage=text(row.select_one(".field-event-location")),
                    subtitle=special or text(row.select_one(".field-subtitle")),
                    genre=genre.capitalize() if genre else None,
                    tags=[notes] if notes else [],
                    status=status,
                    url=absolute(base, link.get("href")),
                    ticket_url=tix.get("href") if tix else None,
                ))
    return out


# ---------------------------------------------------------------- Deutsches Theater (via its ticket shop)
def _norm_title(s):
    s = html.unescape(s).lower().replace("´", "'").replace("’", "'")
    s = re.sub(r"\b(disney|20\d\d)\b", " ", s)
    return re.sub(r"[^a-z0-9äöüß]+", " ", s).strip()


def _dt_show_pages():
    """Title -> production page, from the website's show lists."""
    pages = {}
    for kind in ("mshows", "ashows"):
        for n in range(1, 10):
            r = session.get(f"https://www.deutsches-theater.de/wp-json/wp/v2/{kind}", timeout=60,
                            params={"per_page": 100, "page": n, "_fields": "link,title"})
            if r.status_code != 200 or not r.json():
                break
            for x in r.json():
                pages.setdefault(_norm_title(x["title"]["rendered"]), x["link"])
            if n >= int(r.headers.get("X-WP-TotalPages", 1)):
                break
    return pages


def _dt_match(title, pages):
    key = _norm_title(title)
    if key in pages:
        return pages[key]
    best = difflib.get_close_matches(key, pages.keys(), n=1, cutoff=0.8)
    if best:
        return pages[best[0]]
    # shop titles often add a subtitle: "Günther Grauer - Musikalische Erinnerungen: …"
    prefix = [k for k in pages if len(k) >= 8 and (key.startswith(k) or k.startswith(key))]
    return pages[max(prefix, key=len)] if prefix else None


DT_SUFFIX = re.compile(r"\s+-\s+(Preview|Premiere)$", re.I)


def deutsches_theater():
    shop = "https://tickets.muenchenticket.de/shop/214"
    page = soup(shop, timeout=120)
    try:
        show_pages = _dt_show_pages()
    except Exception as exc:  # covers and info links are optional
        print(f"  deutsches-theater: show pages unavailable: {exc}")
        show_pages = {}
    out = []
    for box in page.select(".event-container"):
        ld = box.find("script", type="application/ld+json")
        if not ld:
            continue
        data = json.loads(ld.string)
        name = html.unescape(data.get("name", ""))
        if not data.get("startDate") or re.search(r"gutschein|showcard", name, re.I):
            continue
        suffix = DT_SUFFIX.search(name)
        title = DT_SUFFIX.sub("", name)
        place = data.get("location", {}).get("name", "")
        out.append(event(
            "deutsches-theater", title, parse_iso(data["startDate"]),
            stage=place.split(" - ", 1)[1] if " - " in place else None,
            subtitle=html.unescape(text(box.select_one(".details-text"))),
            tags=[suffix.group(1).capitalize()] if suffix else [],
            status=_status_from_text(text(box.select_one(".event-state"))),
            url=_dt_match(title, show_pages) or data.get("url"),
            ticket_url=data.get("url"),
        ))
    return out


# ---------------------------------------------------------------- Isarphilharmonie (Gasteig)
GASTEIG_SKIP_TAGS = {"Highlight", "Gasteig HP8", "Isarphilharmonie", "Musik", "Bühne", "Literatur"}


def _gasteig_teasers(html):
    for t in BeautifulSoup(html, "html.parser").select('[data-component="teaser"][data-id]'):
        tm = t.find("time")
        h3 = t.find("h3")
        if not tm or not h3:
            continue
        sub = h3.find("span")
        sub_txt = text(sub)
        if sub:
            sub.extract()
        a = t.find("a")
        img = t.find("img")
        tags = [text(li) for li in t.select('[data-component="tags"] li')]
        yield t["data-id"], event(
            "isarphilharmonie", text(h3), parse_iso(tm["datetime"].replace(" ", "T")),
            subtitle=sub_txt,
            genre=next((x for x in tags if x not in GASTEIG_SKIP_TAGS), None),
            status="cancelled" if t.get("data-canceled") else "unknown",
            image=img.get("src") if img else None,
            url=a.get("href") if a else None,
        )


def isarphilharmonie():
    url = "https://www.gasteig.de/veranstaltungen/?room=isarphilharmonie"
    html = get(url, timeout=120).text
    out, ids = {}, []
    for tid, ev in _gasteig_teasers(html):
        out[ev["id"]] = ev
        ids.append(int(tid))
    cfg = re.search(r'data-component="loadMore"[^>]*>\s*<div[^>]*>\s*<script type="application/json">(.*?)</script>', html, re.S)
    if not cfg:
        return list(out.values())
    params = json.loads(cfg.group(1))
    for _ in range(15):
        form = {k: json.dumps(v) if isinstance(v, (dict, list, bool)) else str(v) for k, v in params.items()}
        form["ignore"] = json.dumps(ids)
        r = session.post("https://www.gasteig.de/backend/admin-ajax.php", data=form, timeout=120,
                         headers={"X-Requested-With": "XMLHttpRequest"})
        r.raise_for_status()
        new = list(_gasteig_teasers(r.text))
        if not new:
            break
        for tid, ev in new:
            out[ev["id"]] = ev
            ids.append(int(tid))
        if max(parse_iso(e["start"]) for _, e in new) > datetime.now(TZ) + timedelta(days=200):
            break
    return list(out.values())


# ---------------------------------------------------------------- Münchner Philharmoniker
MPHIL_PARAM = "tx_mphilconcerts_konzertkalender26"
# tour venues are listed as "Gastkonzerte"; a few out-of-town ones are not
MPHIL_NOT_MUNICH = re.compile(r"ottobeuren|aix-en|wien|hamburg|new york|paris|frankfurt|baden-baden", re.I)


def _surname(name):
    return name.split()[-1] if name else ""


def muenchner_philharmoniker():
    base = "https://www.mphil.de/kalender"
    out = []
    for offset in range(0, 600, 15):  # the calendar's own "Mehr laden" pages
        page = soup(base, params={
            f"{MPHIL_PARAM}[action]": "concertCalendarLoadConcerts", f"{MPHIL_PARAM}[controller]": "Opas",
            f"{MPHIL_PARAM}[cUid]": "4852", "type": "1726500002", f"{MPHIL_PARAM}[offset]": offset,
        })
        items = page.select(".m-mphil-concertlist__item")
        if not items:
            break
        for it in items:
            tm = it.select_one("time[datetime]")
            stage = text(it.select_one(".m-mphil-concertlist__venue"))
            cats = list(dict.fromkeys(text(x) for x in it.select(".m-mphil-concertlist__cat")))
            if not tm or "Gastkonzerte" in cats or MPHIL_NOT_MUNICH.search(stage):
                continue
            headline = text(it.select_one(".m-mphil-concertlist__headline"))
            composers = list(dict.fromkeys(_surname(text(x)) for x in it.select(".m-mphil-concertlist__work-composer")))
            people = [
                f"{text(p.select_one('.m-mphil-concertlist__person-link-title')) or text(p.select_one('a'))}"
                + (f" ({text(p.select_one('.m-mphil-concertlist__instrument'))})" if p.select_one(".m-mphil-concertlist__instrument") else "")
                for p in it.select(".m-mphil-concertlist__person")
            ]
            title = headline or " / ".join(c for c in composers if c) or "Münchner Philharmoniker"
            subtitle = text(it.select_one(".m-mphil-concertlist__subheadline")) or " · ".join(x for x in people if x.strip())
            detail = it.select_one("a.m-mphil-concertlist__detail-link")
            buttons = it.select(".m-mphil-concertlist__buttons a[href^='http']")
            tix = next((b for b in buttons if "gruppe" not in text(b).lower()), None)
            src = it.select_one("figure source[srcset]:not([type])") or it.select_one("figure img")
            img = (src.get("srcset") or src.get("src") or "").split(",")[0].split()[0] if src else None
            out.append(event(
                "muenchner-philharmoniker", title, parse_iso(tm["datetime"].replace(" ", "T")),
                stage=stage,
                subtitle=subtitle,
                genre=cats[0] if cats else "Konzert",
                status=_status_from_text(text(tix)),
                image=img,
                url=absolute(base, detail.get("href")) if detail else base,
                ticket_url=tix.get("href") if tix else None,
            ))
    return out


# ---------------------------------------------------------------- Bayerische Staatsoper
def staatsoper():
    base = "https://www.staatsoper.de/spielplan"
    page = soup(base)
    out = []
    for a in page.select("a.activity-list__content"):
        tm = a.select_one("time[datetime]")
        if not tm:
            continue
        y, mo, d = map(int, tm["datetime"][:10].split("-"))
        spans = a.select(".activity-list__text > span")
        info = text(spans[0]) if spans else ""
        hm = find_time(info)
        title = a.select_one(".h3")
        row = a.find_parent(class_=re.compile("activity-list__row")) or a.parent.parent
        tix = row.select_one("a[href*='webshop']") if row else None
        out.append(event(
            "bayerische-staatsoper", text(title), local_dt(y, mo, d, *(hm or (0, 0))),
            time_tbd=hm is None,
            stage=info.split("|", 1)[1].split("(")[0].strip() if "|" in info else None,
            genre=text(a.select_one(".activity-list__channel")),
            status=_status_from_text(text(row) if row else ""),
            url=absolute(base, a.get("href")),
            ticket_url=tix.get("href") if tix else None,
        ))
    return out


# ---------------------------------------------------------------- Museum Lichtspiele
def _as_list(x):
    return x if isinstance(x, list) else [x]


def museum_lichtspiele():
    """The page embeds its whole programme as `programm = {...}` for its own JavaScript."""
    base = "https://www.museum-lichtspiele.de"
    page = get(f"{base}/programm?filter=all").text
    m = re.search(r"\bprogramm\s*=\s*", page)
    if not m:
        raise RuntimeError("programme data not found")
    data, _ = json.JSONDecoder().raw_decode(page[m.end():])
    out = []
    for film in data.get("filme", {}).values():
        facts = film["filmfakten"]
        title = facts.get("titel") or ""
        poster = (facts.get("plakat_ids") or {}).get("id")
        runtime = facts.get("laufzeit")
        tags = [x for x in str(facts.get("Versionsmarker") or "").split("|") if x and x != "2D"]
        for group in _as_list(film.get("vorstellungen") or []):
            for shows in (group.get("termine") or {}).values():
                for s in _as_list(shows):
                    y, mo, d = map(int, s["datum"].split("-"))
                    h, mi = map(int, s["zeit"].split(":"))
                    link = s.get("link_mobile")
                    out.append(event(
                        "museum-lichtspiele", title, local_dt(y, mo, d, h, mi),
                        stage=s.get("saal_bezeichnung") or None,
                        genre="Film",
                        tags=tags,
                        duration_min=int(runtime) if str(runtime).isdigit() else None,
                        image=f"{base}/images/Breite_400px_RGB/{poster}" if poster else None,
                        url=f"{base}/detail/{facts['idf']}/{quote(title.replace(' ', '_'))}",
                        ticket_url=unquote(link) if isinstance(link, str) else None,
                    ))
    return out


# ---------------------------------------------------------------- City Kinos & Atelier
def city_kinos():
    base = "https://www.city-kinos.de/filme"
    page = soup(base)
    props = json.loads(page.find("script", id="__NEXT_DATA__").string)["props"]["pageProps"]
    out = []
    for item in props.get("films", []) + props.get("specials", []):
        f = item["fields"]
        img = (((f.get("heroImage") or {}).get("fields") or {}).get("image") or {}).get("fields", {}).get("file", {}).get("url")
        for s in f.get("sessions", []):
            sf = s["fields"]
            cinema = ((sf.get("cinema") or {}).get("fields") or {}).get("name", "")
            if not re.search(r"city|atelier", cinema, re.I):
                continue
            out.append(event(
                "city-kino-atelier", f.get("title") or f.get("name", ""), parse_iso(sf["startTime"]),
                stage=cinema,
                genre="Film",
                tags=sf.get("formats") or [],
                duration_min=f.get("runtime"),
                # Contentful crops the wide still to poster format around faces
                image=f"https:{img}?w=300&h=450&fit=fill&f=faces&fm=jpg&q=80" if img else None,
                url=f"https://www.city-kinos.de/filme/{f['slug']}" if f.get("slug") else base,
            ))
    return out


SCRAPERS = {
    "residenztheater": residenztheater,
    "kammerspiele": kammerspiele,
    "volkstheater": volkstheater,
    "deutsches-theater": deutsches_theater,
    "isarphilharmonie": isarphilharmonie,
    "muenchner-philharmoniker": muenchner_philharmoniker,
    "bayerische-staatsoper": staatsoper,
    "museum-lichtspiele": museum_lichtspiele,
    "city-kino-atelier": city_kinos,
}
