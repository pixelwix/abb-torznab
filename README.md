# abb-torznab

A small bridge that makes **AudioBook Bay** (ABB) look like a normal Torznab indexer, so
[Prowlarr](https://prowlarr.com) — and through it [ReadMeABook](https://github.com/kikootwo/readmeabook)
or any other Torznab client — can search it, rank it and download from it automatically.
Set it as your top-priority audiobook indexer and ABB becomes the first-choice source.

```
Audiobook request
        │
ReadMeABook ──search──▶ Prowlarr ──▶ every indexer, incl. "AudioBook Bay" (#23)
        │                                       │
        │                              abb-torznab (this) ──▶ audiobookbay.lu
        ▼
torrent client (use a VPN) ──▶ ReadMeABook import ──▶ Audiobookshelf
```

Single file (`app.py`), Python standard library only, no ABB account needed.

## Files

| | |
|---|---|
| `app.py` | the bridge (single file) |
| `docker-compose.yml`, `Dockerfile` | container, port **8791** |
| `.env.example` | optional settings (copy to `.env` on the docker host) |
| `deploy.sh`, `deploy.env.example` | one-command deploy over SSH (plain host or Proxmox LXC) |
| `tests/` | unit tests, no network needed |
| `data/details.json` | runtime cache of info hashes (safe to delete) |

Keep it on your LAN — it has no authentication. Don't publish it through a reverse proxy.

## How it works

* **Search** — ABB's own search page is fetched for a few variations of the query and the
  results are pooled. ABB's keyword matching is loose (a full title can return a sibling
  book), so the bridge ranks results by how many title words they share. Variations, most
  specific first (max 4):
  1. the whole query, cleaned (edition tags in brackets, punctuation and apostrophes removed)
  2. the part after the last colon/dash — series-prefixed Audible titles like
     *"Avatar, the Last Airbender: The Dawn of Yangchen"* are listed on ABB as *"The Dawn of Yangchen"*
  3. the first 4 words of that part
  4. the first 5 words of the whole query
* **Magnets** — each result's detail page is fetched once for its info hash and trackers
  (cached forever), so every item carries a ready magnet link.
* **Edition preference** — when ABB has both a produced edition (*dramatized*, *full-cast*,
  *GraphicAudio*, *audio drama*) and a single-narrator reading of the same book, the setting
  `EDITION_PREFERENCE` (in `.env`) decides which one ReadMeABook gets to see:

  | Value | Effect |
  |---|---|
  | `produced` *(default)* | Only the produced edition is returned — full cast always wins |
  | `narrated` | Only the single-narrator reading is returned |
  | `any` | Both are returned; ReadMeABook's normal ranking picks |

  It only applies when both versions exist; a book with just one version is always returned.
  Unrelated results are untouched. Change it with `docker compose up -d` after editing.
* **Empty query** (Prowlarr's connection test, RSS polling) returns ABB's latest uploads.
  ReadMeABook's RSS monitor uses this to match new uploads to waiting requests.
* **ABB down** — the bridge answers with an empty list (and doesn't cache it), so
  ReadMeABook simply falls back to the other indexers.
* ABB shows no seeder counts; items report a neutral 10/10 so clients don't discard them.

## Setup

### 1. Run it

```bash
docker compose up -d --build          # on the docker host, in this folder
curl -s http://localhost:8791/health  # {"ok":true}
```

Or from your machine: copy `deploy.env.example` to `deploy.env`, fill it in, then
`./deploy.sh` (runs the tests, copies the files, rebuilds and health-checks).

### 2. Prowlarr

Indexers → Add → **Generic Torznab**:

| Field | Value |
|---|---|
| Name | `AudioBook Bay` |
| URL | `http://<docker host>:8791` |
| API Path | `/api` |
| API Key | anything (`none`) — the bridge ignores it |
| Categories | Audio/Audiobook (3030) |
| Prefer Magnet URL | **on** |

The connection test needs ABB to be up (it fetches the latest uploads).

### 3. ReadMeABook

Settings → Indexers: enable **AudioBook Bay**, audiobook category **3030**,
**priority 25**, RSS **on**. Leave your other indexers at the default priority **10**.

ReadMeABook scores priority as a bonus (`priority / 25` of the indexer bonus) on top of each
release's quality score, so ABB wins whenever its copy passes the normal 50/100 quality bar.
A bad match from ABB still loses.

## Checking it

```bash
curl -s http://<docker host>:8791/health
curl -s "http://<docker host>:8791/api?t=search&q=threshing+day&cat=3030" | grep -o '<title>[^<]*'
docker logs --tail 50 abb-torznab
```

Tests: `python3 -m unittest discover -s tests` (no network needed).

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Every search returns no items | ABB is down — `curl -I https://audiobookbay.lu/` from the docker host. Logs show `search '…' failed`. Nothing to do; other indexers keep working. |
| ABB moved to a new domain | Set `ABB_BASE` in `.env`, then `docker compose up -d`. |
| Right book exists on ABB but isn't found | Try the query in the curl above. If ABB's own search can't find it with any of the 4 variations, add a custom search term on the request in ReadMeABook. |
| Results found but ReadMeABook picks nothing | Its 50/100 quality bar rejected them (shown as "No quality matches" on the request). Pick one by hand: ReadMeABook → request → Interactive search. |
| Page layout changed (results parse as empty while ABB is up) | Update `parse_search` / `parse_detail` in `app.py`; the tests show the HTML shape they expect. |
| Got the wrong edition (full cast vs. narrated) | Check `EDITION_PREFERENCE`; for a one-off, pick the other copy by hand in ReadMeABook → request → Interactive search. |
| Stale or wrong magnet | Delete `data/details.json` and restart the container. |

## Disclaimer

This project only reads ABB's public pages and builds magnet links from them; it hosts or
downloads nothing itself. You are responsible for what you download and for complying with
the laws where you live.
