"""One-off: fetch each venue's app icon and turn its mark into a white cut-out
(site/logos/<id>.png) that sits on the venue's brand colour in the UI.

Colours come from each venue's branding (icon or stylesheet, Nov 2026), adjusted so that
no two venues share a colour: several brands are red, so Volkstheater is orange-red,
Deutsches Theater wine, Museum Lichtspiele magenta; Gasteig uses its yellow, the
Philharmoniker their light blue, City Kinos the green from its stylesheet.
Run again only when a venue changes its branding:  python scraper/branding.py
"""
import io
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from common import get  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "logos"
VENUES = Path(__file__).parent / "venues.json"

BRANDING = {
    "residenztheater": ("https://www.residenztheater.de/_assets/0fc4c476ba417208cc581328d051a35d/Favicons/apple-touch-icon.png", "#d60027"),
    "kammerspiele": ("https://www.muenchner-kammerspiele.de/apple-touch-icon.png", "#000000"),
    "volkstheater": ("https://www.muenchner-volkstheater.de/themes/mvtneubau/images/touch-icons/Icon-60-3x.png", "#ff5a1f"),
    "deutsches-theater": ("https://www.deutsches-theater.de/apple-touch-icon.png", "#7a1230"),
    "isarphilharmonie": ("https://www.gasteig.de/build/assets/images/favicons/frontend/apple-icon-180x180.png", "#ffdd20"),
    "muenchner-philharmoniker": ("https://www.mphil.de/typo3conf/ext/puck/Resources/Public/Icons/Favicons/packages/default/apple-touch-icon-180x180.png", "#78c4e9"),
    "museum-lichtspiele": ("https://www.museum-lichtspiele.de/clients/356/img/favicons/apple-touch-icon.png", "#e6007e"),
    "city-kino-atelier": ("https://www.city-kinos.de/favicon/apple-touch-icon.png", "#2e8540"),
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
    px = im.load()
    opaque = [px[x, y][:3] for x in range(180) for y in range(180) if px[x, y][3] > 200]
    bg = Counter((r // 16, g // 16, b // 16) for r, g, b in opaque).most_common(1)[0][0]
    ink = (17, 17, 17) if luminance(brand) > 0.5 else (255, 255, 255)
    mask = Image.new("L", im.size, 0)
    m = mask.load()
    for x in range(180):
        for y in range(180):
            r, g, b, a = px[x, y]
            if a > 128 and (r // 16, g // 16, b // 16) != bg:
                m[x, y] = 255
    box = mask.getbbox()
    mask = mask.crop(box)
    w, h = mask.size
    side = int(max(w, h) * 1.35)  # padding so the mark sits inside the round bubble
    logo = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    logo.paste(Image.new("RGBA", mask.size, ink + (255,)), ((side - w) // 2, (side - h) // 2), mask)
    return logo.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    venues = json.loads(VENUES.read_text())
    for v in venues:
        if v["id"] not in BRANDING:
            continue
        url, color = BRANDING[v["id"]]
        cutout(get(url).content, color).save(OUT / f"{v['id']}.png", optimize=True)
        v["color"], v["logo"] = color, f"logos/{v['id']}.png"
        print(f"  {v['id']:26} {color}")
    VENUES.write_text(json.dumps(venues, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
