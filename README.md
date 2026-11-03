# München Spielplan

Theatre, opera, concert and cinema programme for Munich, refreshed every day.

- `site/` – the website (one static page). It loads `site/data/events.json`.
- `scraper/` – Python scrapers, one function per venue in `venues.py`; `run.py` merges them.
- `.github/workflows/update.yml` – runs the scrapers daily on GitHub and publishes `site/` to GitHub Pages.

If a venue's website fails or changes layout, its previous events are kept and the
footer of the site marks that source in red. `site/data/status.json` has the error.

## Run locally

```bash
pip install -r scraper/requirements.txt
python scraper/run.py                 # all venues
python scraper/run.py volkstheater    # just one
python -m http.server -d site 8000    # then open http://localhost:8000
```
