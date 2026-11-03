"""One scraper per venue. Each returns a list of event dicts (see common.event)."""
import difflib
import html
import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

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
        src = img.get("src") if img else None
        if img and (not src or src.startswith("data:")):  # lazy-loaded: real address in data-src / srcset
            src = img.get("data-src") or (img.get("data-srcset") or img.get("srcset") or "").split(" ")[0] or None
        tags = [text(li) for li in t.select('[data-component="tags"] li')]
        yield t["data-id"], event(
            "isarphilharmonie", text(h3), parse_iso(tm["datetime"].replace(" ", "T")),
            subtitle=sub_txt,
            genre=next((x for x in tags if x not in GASTEIG_SKIP_TAGS), None),
            status="cancelled" if t.get("data-canceled") else "unknown",
            image=src if src and src.startswith("http") else None,
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


# ---------------------------------------------------------------- der tu film (TUM student cinema)
TU_CAMPUS = {"MUC": "München", "GAR": "Garching"}
VERSION_TAGS = ("OV", "OmU", "OmdU", "OmeU", "DF")


def tu_film():
    base = "https://www.tu-film.de/"
    home = soup(base)
    semester = next((a["href"] for a in home.select("a[href^='/program/']")
                     if re.fullmatch(r"/program/[a-z]{2}\d{4}/", a["href"])), None)
    if not semester:
        raise RuntimeError("current semester not found")
    plan = soup(absolute(base, semester))
    today = datetime.now(TZ).date()
    out = []
    for row in plan.select(".plan tr"):
        link = row.select_one("td.title a")
        dm = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*'(\d\d)", text(row.select_one("td.date")))
        if not link or not dm:
            continue
        d, mo, y = int(dm.group(1)), int(dm.group(2)), 2000 + int(dm.group(3))
        if datetime(y, mo, d).date() < today:
            continue
        notes = re.findall(r"[^,()]+", text(row.select_one("td.title i")))
        notes = [n.strip() for n in notes if n.strip()]
        tags = [n for n in notes if n in VERSION_TAGS] + [n for n in notes if n not in VERSION_TAGS]
        url = absolute(base, link["href"])
        # the detail page has the start time, lecture hall, poster and running time
        detail = soup(url)
        when = detail.select_one("p.event")
        hm = find_time(text(when))
        room = text(when.select_one("a")) if when else ""
        poster = detail.select_one("td.poster img")
        mins = re.search(r"(\d+)\s*Minuten", text(detail.select_one(".programentry")))
        campus = TU_CAMPUS.get(text(row.select_one("td.place")), text(row.select_one("td.place")))
        out.append(event(
            "tu-film", text(link), local_dt(y, mo, d, *(hm or (20, 0))),
            time_tbd=hm is None,
            stage=f"{campus} · {room}" if room else campus,
            genre="Film",
            tags=tags,
            duration_min=int(mins.group(1)) if mins else None,
            image=absolute(url, poster.get("src")) if poster else None,
            url=url,
            ticket_url=None,
        ))
    return out


# ---------------------------------------------------------------- Staatstheater am Gärtnerplatz
GP_STATUS = {"tickets": "available", "restkarten": "few", "ausverkauft": "sold_out"}


def gaertnerplatz():
    base = "https://www.gaertnerplatztheater.de/de/spielplan/index.html"
    out = []
    for offset in range(18):  # one page per month, as the site's own "load more" does
        page = soup(base, params={"ajax": 1, "offset": offset, "letzterTermin": 0})
        rows = page.select("div.row.align-items-top")
        if not rows:
            break
        for row in rows:
            cols = row.find_all("div", class_="col", recursive=False)
            dm = re.search(r"(\d\d)\.(\d\d)\.(\d\d)", text(cols[0]) if cols else "")
            link = row.select_one("a[href*='ID_Vorstellung']")
            if not dm or not link:
                continue
            first_col = cols[0].find_all("div", recursive=False)
            when = text(first_col[1]) if len(first_col) > 1 else ""
            hm = find_time(when)
            label = text(cols[1].find("span", recursive=False)) if len(cols) > 1 else ""
            subtitle = label if label.startswith("»") else None
            tix = row.select_one("a.ticket")
            tix_txt = text(tix).lower() or text(row.select_one(".btn:not([href*='produktionen'])")).lower()
            href = re.sub(r"&m=\d+", "", link["href"])
            out.append(event(
                "gaertnerplatz", text(link),
                local_dt(2000 + int(dm.group(3)), int(dm.group(2)), int(dm.group(1)), *(hm or (0, 0))),
                time_tbd=hm is None,
                subtitle=subtitle,
                genre=None if subtitle else label or None,
                tags=[text(x) for x in row.select(".icons span") if text(x) and text(x) != text(link)],
                status=next((s for k, s in GP_STATUS.items() if k in tix_txt), "unknown"),
                duration_min=duration_from_range(when),
                url=absolute("https://www.gaertnerplatztheater.de/de/", href),
                ticket_url=tix.get("href") if tix and tix.get("href", "").startswith("http") else None,
            ))
    return out


# ---------------------------------------------------------------- Metropoltheater
def metropoltheater():
    base = "https://www.metropoltheater.com/spielplan/aktuell/"
    page = soup(base)
    out, year, month = [], None, None
    for el in page.find_all(lambda t: t.name in ("h1", "h2", "h3") or "termin" in (t.get("class") or [])):
        if el.name != "div":
            m = re.fullmatch(r"([A-Za-zä]+)\s+(\d{4})", text(el))
            if m and m.group(1).lower() in MONTH_NAMES:
                month, year = MONTH_NAMES.index(m.group(1).lower()) + 1, int(m.group(2))
            continue
        classes = el.get("class") or []
        link = el.select_one(".termin-column2 a")
        if not month or not link or "termin_spielfrei" in classes or "termin_gastspiel" in classes:
            continue
        hm = find_time(text(el.select_one(".termin-column1a")))
        # the "Karten" / "zum Stück" links follow the entry as siblings
        links = []
        for sib in el.find_next_siblings():
            if "termin" in (sib.get("class") or []):
                break
            links += sib.select("a") if sib.name != "a" else [sib]
        tix = next((a for a in links if text(a).lower().endswith("karten")), None)
        out.append(event(
            "metropoltheater", text(link),
            local_dt(year, month, int(text(el.select_one(".termin-datum"))), *(hm or (0, 0))),
            time_tbd=hm is None,
            stage=text(el.select_one(".termin-ort")),
            subtitle=text(el.select_one(".termin-zusatz")),
            url=absolute(base, link.get("href")),
            ticket_url=absolute(base, tix.get("href")) if tix else None,
        ))
    return out


# ---------------------------------------------------------------- Cinema München
CINEMA_VERSIONS = {"ov": "OV", "omu": "OmU", "omeu": "OmeU", "omdu": "OmdU", "orig.m.engl.u": "OmeU", "orig.m.dt.u": "OmdU"}


def cinema_muenchen():
    """The page embeds its programme as `pmkinoFrontVars = {...}`."""
    html_ = get("https://cinema-muenchen.com/de/programmuebersicht/").text
    m = re.search(r"pmkinoFrontVars\s*=\s*", html_)
    if not m:
        raise RuntimeError("programme data not found")
    data, _ = json.JSONDecoder().raw_decode(html_[m.end():])
    api = data["apiData"]
    movies = api["movies"]["items"]
    routes = data.get("routesData", {}).get("movies", {}).get("items", {})
    out = []
    for p in api["performances"]["items"].values():
        film = movies.get(p["moviePk"])
        if not film or not p.get("timeUtc"):
            continue
        start = datetime.fromtimestamp(p["timeUtc"] / 1000, TZ)
        versions = list(dict.fromkeys(CINEMA_VERSIONS[a["id"].lower()] for a in p.get("attributes", [])
                                      if a["id"].lower() in CINEMA_VERSIONS))
        full = p.get("occupationPercent") or 0
        out.append(event(
            "cinema-muenchen", film.get("titleDisplay") or film["title"], start,
            genre="Film",
            tags=versions,
            status="sold_out" if full >= 100 else "few" if full >= 85 else "unknown",
            duration_min=film.get("length"),
            image=((film.get("images") or {}).get("poster") or {}).get("url"),
            url=(routes.get(p["moviePk"], {}).get("uri_list") or {}).get("de") or "https://cinema-muenchen.com/de/programmuebersicht/",
        ))
    return out


# ---------------------------------------------------------------- BR Symphonieorchester
def br_symphonieorchester():
    today = datetime.now(TZ)
    r = session.post("https://www.brso.de/wp-json/v1/filter/concerts", timeout=60, data={
        "pagination": 1, "date_from_year": today.year, "date_from_month": f"{today.month:02d}",
        "date_from_day": f"{today.day:02d}", "presented_by": "", "director": "all", "location": 0, "abo": 0,
    })
    r.raise_for_status()
    out = []
    for c in r.json()["data"].get("concerts") or []:
        place = c.get("location") or ""
        if c.get("is_archive") or not c.get("start") or not place.startswith("München"):
            continue
        extra = c.get("info_additional") or ""
        tix = (c.get("ticket_link") or {}).get("url")
        out.append(event(
            "brso", html.unescape(c["title"]).replace(" : ", " · "), parse_iso(c["start"]),
            time_tbd=not c.get("date_known", True),
            stage=re.sub(r"^München,\s*", "", place),
            subtitle=html.unescape(c.get("subtitle") or "") or None,
            genre="Klassik",
            status=_status_from_text(extra),
            image=c.get("thumbnail_url"),
            url=c.get("url"),
            ticket_url=tix or None,
        ))
    return out


# ---------------------------------------------------------------- Muffatwerk (Muffathalle, Ampere, …)
MUFFAT_GENRE = {"Konzert": "Konzert", "Wort": "Lesung", "Tanz / Theater": "Tanz", "Party": "Party"}


def muffatwerk():
    base = "https://www.muffatwerk.de/de/events"
    page = soup(base)
    today = datetime.now(TZ).date()
    out, seen = [], set()
    for box in page.select(".entry-content"):
        info = box.select_one(".hover-in .center")
        link = box.select_one("a[href*='/de/events/view/']")
        date_txt = text(box.select_one(".hover-out .date"))
        # "Fr 07.11 26" (year on its own line); "ab 02.11.26" marks ongoing notices, skipped
        dm = re.fullmatch(r"\w\w\s+(\d\d)\.(\d\d)\.?\s*(\d\d)", date_txt)
        cat = text(box.select_one(".circle span"))
        if not info or not link or not dm or cat == "Andere" or link["href"] in seen:
            continue
        seen.add(link["href"])
        day = local_dt(2000 + int(dm.group(3)), int(dm.group(2)), int(dm.group(1)))
        if day.date() < today:
            continue
        title_el = info.find("span")
        title = text(title_el)
        # rest reads like "ausverkauft Glanz Null Tour support: Kay Konzert Ort: Muffathalle — 06.11.26"
        rest = text(info).replace(title, "", 1).strip()
        place = re.search(r"Ort:\s*(.+?)(?:\s+—|$)", rest)
        state = re.match(r"(abgesagt|entfällt|ausverkauft|wenige karten)\b", rest, re.I)
        subtitle = rest.split("Ort:")[0]
        subtitle = re.sub(r"^(abgesagt|entfällt|ausverkauft|wenige karten)\s*", "", subtitle, flags=re.I)
        subtitle = re.sub(r"\s*(Konzert|Party|Wort|Tanz / Theater|Andere)?\s*[–-]?\s*$", "", subtitle).strip() or None
        url = absolute(base, link["href"])
        # start time, price and picture are only on the event's own page
        detail = soup(url)
        body = text(detail.find("body"))
        hm = find_time((re.search(r"Beginn:\s*([\d:.]+(?:\s*Uhr)?)", body) or [None, ""])[1].replace(" Uhr", ":00"))
        price = re.search(r"VVK\s*€\s*([\d,.]+)", body)
        og = detail.find("meta", property="og:image")
        out.append(event(
            "muffatwerk", title, day.replace(hour=hm[0], minute=hm[1]) if hm else day,
            time_tbd=hm is None,
            stage=place.group(1).strip() if place else None,
            subtitle=subtitle,
            genre=MUFFAT_GENRE.get(cat, cat or None),
            status=_status_from_text(state.group(1)) if state else "unknown",
            price=f"VVK {price.group(1)} €" if price else None,
            image=og.get("content") if og else None,
            url=url,
            ticket_url=None,
        ))
        time.sleep(0.2)
    return out


# ---------------------------------------------------------------- iCal feeds (The Events Calendar on WordPress)
def _ics(url, start=None):
    """Minimal iCalendar reader: yields one dict per VEVENT (property name -> (params, value))."""
    params = {"post_type": "tribe_events", "ical": 1, "eventDisplay": "list"}
    if start:
        params["tribe-bar-date"] = start
    raw = get(url, params=params).text
    lines = []
    for line in raw.splitlines():
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    ev = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            ev = {}
        elif line == "END:VEVENT" and ev is not None:
            yield ev
            ev = None
        elif ev is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            value = value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")
            ev[name] = (params, value)


def _ics_start(prop):
    params, value = prop
    if "VALUE=DATE" in params or "T" not in value:
        return local_dt(int(value[:4]), int(value[4:6]), int(value[6:8])), True
    dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ), False
    return dt.replace(tzinfo=TZ), False


def _ics_venue(venue_id, site, genre_from_description=False):
    today = datetime.now(TZ).date()
    feed, seen, page_start = [], set(), None
    for _ in range(12):  # the feed returns ~30 events; continue from the last one's date
        batch = [e for e in _ics(site, page_start) if "DTSTART" in e and "SUMMARY" in e]
        new = [e for e in batch if e.get("UID", ([], id(e)))[1] not in seen]
        if not new:
            break
        seen.update(e.get("UID", ([], id(e)))[1] for e in new)
        feed += new
        last = max(_ics_start(e["DTSTART"])[0] for e in new).date()
        page_start = last.isoformat()
    out = []
    for ev in feed:
        start, all_day = _ics_start(ev["DTSTART"])
        if start.date() < today:
            continue
        desc = ev.get("DESCRIPTION", ([], ""))[1]
        genre = None
        if genre_from_description:  # schwere reiter: "DI 03.11. | 20:00 | musik"
            m = re.match(r"\s*\w\w \d\d\.\d\d\.\s*\|\s*[\d:]+\s*\|\s*([^\n|]+)", desc)
            genre = m.group(1).strip().capitalize() if m else None
        out.append(event(
            venue_id, html.unescape(ev["SUMMARY"][1]), start,
            time_tbd=all_day,
            genre=genre,
            image=ev.get("ATTACH", ([], None))[1],
            url=ev.get("URL", ([], None))[1],
        ))
    return out


def schwere_reiter():
    return _ics_venue("schwere-reiter", "https://schwerereiter.de/", genre_from_description=True)


def hochx():
    return _ics_venue("hochx", "https://theater-hochx.de/")


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
    "tu-film": tu_film,
    "gaertnerplatz": gaertnerplatz,
    "metropoltheater": metropoltheater,
    "cinema-muenchen": cinema_muenchen,
    "brso": br_symphonieorchester,
    "muffatwerk": muffatwerk,
    "schwere-reiter": schwere_reiter,
    "hochx": hochx,
}
