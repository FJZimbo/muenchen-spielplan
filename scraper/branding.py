"""One-off: fetch each venue's app icon and turn its mark into a white cut-out
(site/logos/<id>.png) that sits on the venue's brand colour in the UI.

Colours come from each venue's branding (icon or stylesheet, Nov 2026), adjusted so that
no two venues share a colour: several brands are red, so Volkstheater is orange,
Deutsches Theater wine, Museum Lichtspiele magenta; Gasteig uses its yellow, the
Philharmoniker their light blue, City Kinos the green from its stylesheet, BRSO a teal
(BR's own blue is too close to TU Film's), Muffatwerk an olive (no brand colour).
Sources are URLs or files in branding_src/ (SVG logos rendered once on a Mac with
`qlmanage -t -s 600 -o . logo.svg`).
Run again only when a venue changes its branding:  python scraper/branding.py
"""
import io
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from common import get  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "logos"
VENUES = Path(__file__).parent / "venues.json"

BRANDING = {
    "residenztheater": ("https://www.residenztheater.de/_assets/0fc4c476ba417208cc581328d051a35d/Favicons/apple-touch-icon.png", "#d60027"),
    "kammerspiele": ("https://www.muenchner-kammerspiele.de/apple-touch-icon.png", "#000000"),
    "volkstheater": ("https://www.muenchner-volkstheater.de/themes/mvtneubau/images/touch-icons/Icon-60-3x.png", "#ff8c00"),
    "metropoltheater": ("https://www.metropoltheater.com/assets/img/logo.jpg", "#1d2b4f"),
    "schwere-reiter": ("https://schwerereiter.de/wp-content/uploads/2024/04/schwerereiter_sw_gleichberechtigt_300dpi.jpg", "#d4e600"),
    "hochx": ("https://theater-hochx.de/wp-content/uploads/2022/04/cropped-favicon_hochx_512x512-192x192.png", "#00bbff"),
    "deutsches-theater": ("https://www.deutsches-theater.de/apple-touch-icon.png", "#7a1230"),
    "isarphilharmonie": ("https://www.gasteig.de/build/assets/images/favicons/frontend/apple-icon-180x180.png", "#ffdd20"),
    "muenchner-philharmoniker": ("https://www.mphil.de/typo3conf/ext/puck/Resources/Public/Icons/Favicons/packages/default/apple-touch-icon-180x180.png", "#78c4e9"),
    "brso": ("branding_src/brso.png", "#0a6963"),  # brso.de/wp-content/uploads/sites/2/brso-logo-2.svg
    "muffatwerk": ("https://www.muffatwerk.de/favicon_mh.ico", "#8a8f2a"),
    # round red-orange logo with white lettering: used as it is
    "gaertnerplatz": ("branding_src/gaertnerplatz.png", "#e53517", "as-is"),  # gaertnerplatztheater.de/assets/images/logo.svg
    "museum-lichtspiele": ("https://www.museum-lichtspiele.de/clients/356/img/favicons/apple-touch-icon.png", "#e6007e"),
    "city-kino-atelier": ("https://www.city-kinos.de/favicon/apple-touch-icon.png", "#2e8540"),
    # white "C" on a navy-to-red gradient: used as it is, the colour is the gradient's navy
    "cinema-muenchen": ("https://cinema-muenchen.com/wp-content/uploads/sites/5/2022/09/cropped-favicon_cinema_neu-1-180x180.png", "#162a47", "as-is"),
    # white "der tu film" wordmark on TUM blue, stacked as "der tu" / "film"
    "tu-film": ("https://www.tu-film.de/logo_white.png", "#0065bd", [[0, 1], [2]]),
    # staatsoper.de blocks automated requests: no icon, keeps its colour and text label
}
SIZE = 96


def luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def cutout(png_bytes, brand):
    """Pixels that differ from the icon's background become the mark, drawn in a colour
    that contrasts with the brand colour; everything else is transparent."""
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA").resize((180, 180))
    ink = (17, 17, 17) if luminance(brand) > 0.5 else (255, 255, 255)
    alpha = im.getchannel("A")
    px = im.load()
    opaque = [px[x, y][:3] for x in range(180) for y in range(180) if px[x, y][3] > 200]
    colours = Counter((r // 16, g // 16, b // 16) for r, g, b in opaque)
    single_colour = colours.most_common(1)[0][1] > 0.9 * len(opaque)
    if sum(alpha.histogram()[:128]) > 0.2 * 180 * 180 and single_colour:
        # a one-colour mark on a transparent background: its shape is the mark
        mask = alpha.point(lambda a: 255 if a > 128 else 0)
        return _square(mask.crop(mask.getbbox()), ink)
    bg = colours.most_common(1)[0][0]
    mask = Image.new("L", im.size, 0)
    m = mask.load()
    for x in range(180):
        for y in range(180):
            r, g, b, a = px[x, y]
            if a > 128 and (r // 16, g // 16, b // 16) != bg:
                m[x, y] = 255
    return _square(mask.crop(mask.getbbox()), ink)


def stacked_wordmark(png_bytes, brand, lines):
    """A wide light-on-transparent wordmark, split into words and stacked so it fits a circle.
    lines: word indices per line, e.g. [[0, 1], [2]] for "der tu" / "film"."""
    alpha = Image.open(io.BytesIO(png_bytes)).convert("RGBA").getchannel("A")
    alpha = alpha.crop(alpha.getbbox())
    cols = [any(alpha.getpixel((x, y)) > 128 for y in range(alpha.height)) for x in range(alpha.width)]
    words, start = [], None
    gap = alpha.height // 6  # letter gaps are narrower than word gaps
    for x, on in enumerate(cols + [False] * (gap + 1)):
        if on and start is None:
            start, last = x, x
        elif on:
            last = x
        elif start is not None and x - last > gap:
            words.append(alpha.crop((start, 0, last + 1, alpha.height)))
            start = None
    space = alpha.height // 3
    rows = []
    for idx in lines:
        parts = [words[i] for i in idx]
        row = Image.new("L", (sum(p.width for p in parts) + space * (len(parts) - 1), alpha.height), 0)
        x = 0
        for p in parts:
            row.paste(p, (x, 0))
            x += p.width + space
        rows.append(row)
    mask = Image.new("L", (max(r.width for r in rows), sum(r.height for r in rows)), 0)
    y = 0
    for r in rows:
        mask.paste(r, ((mask.width - r.width) // 2, y))
        y += r.height
    ink = (17, 17, 17) if luminance(brand) > 0.5 else (255, 255, 255)
    return _square(mask, ink, padding=1.3)


def _square(mask, ink, padding=1.35):
    """Centre the mark in a transparent square, padded so it sits inside the round bubble."""
    w, h = mask.size
    side = int(max(w, h) * padding)
    logo = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    logo.paste(Image.new("RGBA", mask.size, ink + (255,)), ((side - w) // 2, (side - h) // 2), mask)
    return logo.resize((SIZE, SIZE), Image.LANCZOS)


def as_is(png_bytes):
    """A logo that already works as a round badge: scaled and clipped to a circle."""
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA").resize((SIZE * 4, SIZE * 4), Image.LANCZOS)
    circle = Image.new("L", im.size, 0)
    ImageDraw.Draw(circle).ellipse((0, 0, im.width - 1, im.height - 1), fill=255)
    im.putalpha(ImageChops.multiply(im.getchannel("A"), circle))
    return im.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    venues = json.loads(VENUES.read_text())
    for v in venues:
        if v["id"] not in BRANDING:
            continue
        source, color, *mode = BRANDING[v["id"]]
        png = get(source).content if source.startswith("http") else (Path(__file__).parent / source).read_bytes()
        if mode and mode[0] == "as-is":
            logo = as_is(png)
        elif mode:
            logo = stacked_wordmark(png, color, mode[0])
        else:
            logo = cutout(png, color)
        logo.save(OUT / f"{v['id']}.png", optimize=True)
        v["color"], v["logo"] = color, f"logos/{v['id']}.png"
        print(f"  {v['id']:26} {color}")
    VENUES.write_text(json.dumps(venues, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
