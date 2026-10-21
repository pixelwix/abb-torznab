"""AudioBook Bay -> Torznab bridge.

Lets Prowlarr (and through it ReadMeABook) search AudioBook Bay like any other
torrent indexer. Results come from ABB's search page; each result's detail
page is fetched once for its info hash so every item carries a ready magnet
link. Standard library only.

Endpoints
  GET /api?t=caps                         Torznab capabilities
  GET /api?t=search|book&q=...            search (q, or title + author)
  GET /api?t=search  (no q)               latest uploads (Prowlarr test / RSS)
  POST /prefs  {title, preference}        per-book edition choice (X-Token header)
  GET /health                             liveness

See README.md for setup and the search rules.
"""
import html
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --- configuration ---------------------------------------------------------

BASE = os.environ.get("ABB_BASE", "https://audiobookbay.lu").rstrip("/")
PORT = int(os.environ.get("PORT", "8791"))
CACHE_FILE = os.environ.get("CACHE_FILE", "/data/details.json")
PREFS_FILE = os.environ.get("PREFS_FILE", os.path.join(os.path.dirname(CACHE_FILE) or ".", "prefs.json"))
PREFS_TOKEN = os.environ.get("PREFS_TOKEN", "")  # required to write per-book preferences; unset = writes disabled
PREFS_TTL = 60 * 86400                            # a per-book choice is forgotten after 60 days
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "10"))
SEARCH_TTL = 600     # seconds a search result list is reused
LATEST_TTL = 1800    # seconds the front-page list is reused
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126 Safari/537.36")
CATEGORY = 3030      # Newznab Audio/Audiobook

STOP_WORDS = {"the", "a", "an", "of", "and"}
# Which edition wins when ABB has both a produced (dramatized / full-cast / GraphicAudio)
# and a single-narrator version of the same book:
#   produced  - keep only the produced edition (default, house rule)
#   narrated  - keep only the single-narrator reading
#   any       - keep both and let ReadMeABook's ranking decide
EDITION_PREFERENCE = os.environ.get("EDITION_PREFERENCE", "produced").strip().lower()
PRODUCED = re.compile(r"dramati[sz]ed|full[- ]?cast|graphic ?audio|audio drama", re.I)
SAME_BOOK = 0.5      # title-word overlap at which two results count as the same book

# --- ABB access --------------------------------------------------------------


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def size_bytes(text):
    m = re.search(r"([\d.,]+)\s*(KB|MB|GB|TB)s?", text or "", re.I)
    if not m:
        return 0
    return int(float(m.group(1).replace(",", "")) * {"KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}[m.group(2).upper()])


def parse_search(page):
    """Results on ABB's search and front pages: one `<div class="post">` each, with a
    title link and a details line ("Posted: … Format: M4B / Bitrate: … File Size: 481.44 MBs")."""
    out = []
    for block in page.split('<div class="post">')[1:]:
        block = block.split('<div class="navigation"')[0]
        m = re.search(r'<div class="postTitle">.*?<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        href = m.group(1) if m.group(1).startswith("http") else BASE + m.group(1)
        text = html.unescape(re.sub(r"<[^>]+>", " ", block))
        out.append({
            "href": href,
            "title": html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip(),
            "format": _first(r"Format:\s*([A-Za-z0-9]+)", text),
            "size": size_bytes(_first(r"File Size:\s*([\d.,]+\s*[KMGT]B)", text, re.I)),
            "posted": _first(r"Posted:\s*(\d{1,2} \w{3} \d{4})", text),
        })
    return out


def parse_detail(page):
    """Info hash, trackers and size from a result's own page."""
    m = (re.search(r"Info Hash:?\s*</td>\s*<td[^>]*>\s*([0-9a-fA-F]{40})", page)
         or re.search(r"\b([0-9a-fA-F]{40})\b", page))
    if not m:
        return None
    return {
        "hash": m.group(1).lower(),
        "trackers": sorted(set(re.findall(r"(?:udp|http)://[a-z0-9.-]+:\d+/announce", page)))[:12],
        "size": size_bytes(_first(r"Combined File Size:?\s*(?:</td>\s*<td[^>]*>)?\s*([\d.,]+\s*[KMGT]B)", page, re.I)),
    }


def _first(pattern, text, flags=0):
    m = re.search(pattern, text or "", flags)
    return m.group(1) if m else ""


# --- caches --------------------------------------------------------------------

_lock = threading.Lock()
_searches = {}  # cleaned query -> (time, items)


def _load_details():
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


_details = _load_details()  # detail-page href -> parse_detail() result; never changes, kept forever


def detail(href):
    with _lock:
        if href in _details:
            return _details[href]
    d = parse_detail(fetch(href))
    if d:
        with _lock:
            _details[href] = d
            try:
                tmp = CACHE_FILE + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(_details, f)
                os.replace(tmp, CACHE_FILE)
            except OSError:
                pass
    return d


def with_magnets(results):
    """Attach a magnet link to each result (fetching detail pages in parallel); drop any without a hash."""
    def safe(href):
        try:
            return detail(href)
        except Exception as e:
            log("detail failed for %s: %s" % (href, e))
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        details = list(ex.map(lambda r: safe(r["href"]), results))
    items = []
    for r, d in zip(results, details):
        if not d:
            continue
        trackers = "".join("&tr=" + urllib.parse.quote(t, safe="") for t in d["trackers"])
        items.append({**r, "hash": d["hash"], "size": r["size"] or d["size"],
                      "magnet": f"magnet:?xt=urn:btih:{d['hash']}&dn={urllib.parse.quote(r['title'])}{trackers}"})
    return items


# --- search strategy -----------------------------------------------------------


def clean_query(q):
    """ABB search is plain keywords: drop edition tags in brackets, punctuation and apostrophes."""
    q = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", q or "")
    q = re.sub(r"[^\w\s']", " ", q).replace("'", "")
    return re.sub(r"\s+", " ", q).strip().lower()


def title_part(query):
    """The part after the last colon/dash — series-prefixed Audible titles
    ("Avatar, the Last Airbender: The Dawn of Yangchen") are usually listed on ABB under it."""
    parts = re.split(r"[:–—]| - ", query or "")
    return clean_query(parts[-1]) if len(parts) > 1 else ""


def query_variants(query):
    """Up to four searches, most specific first: full query, title part, its first 4 words,
    first 5 words of the full query. ABB's matching is loose, so all are run and pooled."""
    q, t = clean_query(query), title_part(query)
    variants = [q, t, " ".join(t.split()[:4]), " ".join(q.split()[:5])]
    return [v for v in dict.fromkeys(variants) if len(v) >= 3][:4]


PART = re.compile(r"\(?\b(?:part\s*)?(\d+)\s*of\s*(\d+)\b\)?", re.I)


def part_of(text):
    """(n, total) from "(Part 2 of 3)" / "(2 of 3)", else None."""
    m = PART.search(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def overlap(key_words, title):
    return len(key_words & set(clean_query(title).split())) / max(len(key_words), 1)


# --- per-book edition choices ------------------------------------------------------
# A requester can pick the edition for one book (e.g. "standard reading" where the house
# default is full cast). The requesting app POSTs {title, preference} before handing the
# request to ReadMeABook; searches whose query contains that title then use it.

VALID_PREFERENCES = ("produced", "narrated", "any")


def _load_prefs():
    try:
        with open(PREFS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


_prefs = _load_prefs()  # cleaned title -> {"preference", "at"}


def set_preference(title, preference):
    key = title_part(title) or clean_query(title)
    if not key or preference not in VALID_PREFERENCES:
        raise ValueError("title and a preference of produced|narrated|any are required")
    with _lock:
        now = time.time()
        for k in [k for k, v in _prefs.items() if now - v["at"] > PREFS_TTL]:
            del _prefs[k]
        _prefs[key] = {"preference": preference, "at": now}
        _searches.clear()  # cached answers may now be filtered differently
        tmp = PREFS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_prefs, f)
        os.replace(tmp, PREFS_FILE)
    return key


def preference_for(query):
    """The per-book choice whose title words all appear in the query, else the default."""
    words = set(clean_query(query).split())
    now = time.time()
    with _lock:
        matches = [(len(k.split()), v["preference"]) for k, v in _prefs.items()
                   if now - v["at"] <= PREFS_TTL and set(k.split()) <= words]
    return max(matches)[1] if matches else EDITION_PREFERENCE


def rank(results, query, preference=None):
    """Closest title first, then apply the edition preference to versions of the requested book."""
    preference = preference or preference_for(query)
    key = set((title_part(query) or clean_query(query)).split()) - STOP_WORDS
    ranked = sorted(results, key=lambda r: overlap(key, r["title"]), reverse=True)
    # A request for one part of a split edition ("Dark Age (1 of 3)") must never get another
    # part: drop releases labelled with a different part number of the same book.
    # Multi-book bundles ("Red Rising Book 1 - 5", "Complete Series") only when a bundle was asked for.
    bundle = re.compile(r"\bbooks?\s*\d+\s*[-\u2013]\s*\d+\b|\bcomplete (series|collection)\b|\bbox(ed)? ?set\b|\bentire\b.*\bcollection\b|\bcollection\s*-\s*various\b|\b\d+\s*[-\u2013]\s*\d+\b(?=.*\b(books?|series)\b)", re.I)
    # A bare number range in a title ("Dark Age 1-3", "#0.5-7") also marks a bundle.
    num_range = re.compile(r"#?\b\d+(?:\.\d+)?\s*[-\u2013]\s*\d+\b")
    if not bundle.search(query or "") and not num_range.search(query or ""):
        ranked = [r for r in ranked if not bundle.search(r["title"]) and not num_range.search(r["title"])]
    wanted = part_of(query)
    if wanted:
        ranked = [r for r in ranked if not (part_of(r["title"]) and part_of(r["title"]) != wanted)]
    same_book = lambda r: overlap(key, r["title"]) >= SAME_BOOK
    produced = [r for r in ranked if same_book(r) and PRODUCED.search(r["title"])]
    narrated = [r for r in ranked if same_book(r) and not PRODUCED.search(r["title"])]
    if produced and narrated and preference in ("produced", "narrated"):
        drop = narrated if preference == "produced" else produced
        ranked = [r for r in ranked if r not in drop]
    return ranked


def search(query):
    q = clean_query(query)
    if not q:
        return latest()
    cache_key = q + "|" + preference_for(query)
    cached = _cached(cache_key, SEARCH_TTL)
    if cached is not None:
        return cached
    pooled, seen, errors = [], set(), 0
    for variant in query_variants(query):
        try:
            found = parse_search(fetch(f"{BASE}/?s={urllib.parse.quote_plus(variant)}"))
        except Exception as e:
            errors += 1
            log("search '%s' failed: %s" % (variant, e))
            continue
        for r in found:
            if r["href"] not in seen:
                seen.add(r["href"])
                pooled.append(r)
    items = with_magnets(rank(pooled, query)[:MAX_RESULTS])
    if items or not errors:  # don't cache an empty answer caused by ABB being down
        _store(cache_key, items)
    return items


def latest():
    cached = _cached("", LATEST_TTL)
    if cached is not None:
        return cached
    items = with_magnets(parse_search(fetch(BASE + "/"))[:MAX_RESULTS])
    _store("", items)
    return items


def _cached(key, ttl):
    with _lock:
        hit = _searches.get(key)
    return hit[1] if hit and time.time() - hit[0] < ttl else None


def _store(key, items):
    with _lock:
        _searches[key] = (time.time(), items)


# --- Torznab output -------------------------------------------------------------

CAPS = ('<?xml version="1.0" encoding="UTF-8"?><caps>'
        '<server title="AudioBook Bay bridge"/><limits max="50" default="25"/>'
        '<searching><search available="yes" supportedParams="q"/>'
        '<book-search available="yes" supportedParams="q,title,author"/>'
        '<tv-search available="no"/><movie-search available="no"/><music-search available="no"/></searching>'
        f'<categories><category id="3000" name="Audio"><subcat id="{CATEGORY}" name="Audio/Audiobook"/></category></categories>'
        '</caps>')


def rss(items):
    esc = lambda s: html.escape(str(s), quote=True)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>',
           f"<title>AudioBook Bay</title><link>{esc(BASE)}</link>"]
    for it in items:
        title = it["title"] + (f" [{it['format']}]" if it.get("format") else "")
        try:
            pub = formatdate(time.mktime(time.strptime(it["posted"], "%d %b %Y")), usegmt=True)
        except (ValueError, TypeError):
            pub = formatdate(usegmt=True)
        attrs = {"category": CATEGORY, "size": it["size"], "magneturl": it["magnet"], "infohash": it["hash"],
                 # ABB shows no swarm counts; a neutral value keeps clients from discarding results.
                 "seeders": 10, "peers": 10, "downloadvolumefactor": 0, "uploadvolumefactor": 1}
        out.append(
            "<item>"
            f"<title>{esc(title)}</title><guid>{esc(it['href'])}</guid><comments>{esc(it['href'])}</comments>"
            f"<link>{esc(it['magnet'])}</link><pubDate>{pub}</pubDate><size>{it['size']}</size>"
            f'<enclosure url="{esc(it["magnet"])}" length="{it["size"]}" type="application/x-bittorrent"/>'
            + "".join(f'<torznab:attr name="{k}" value="{esc(v)}"/>' for k, v in attrs.items())
            + "</item>")
    out.append("</channel></rss>")
    return "".join(out)


# --- HTTP server ------------------------------------------------------------------


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/xml; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/health":
            return self._send(200, '{"ok":true}', "application/json")
        if url.path.rstrip("/") not in ("", "/api"):
            return self._send(404, "not found", "text/plain")
        if params.get("t") == "caps":
            return self._send(200, CAPS)
        cats = params.get("cat", "")
        if cats and not any(c.strip().startswith("3") for c in cats.split(",")):
            return self._send(200, rss([]))  # only audio lives here
        query = params.get("q") or " ".join(filter(None, [params.get("title"), params.get("author")]))
        try:
            items = search(query)
        except Exception as e:  # ABB down or changed: answer empty so the client falls back to other indexers
            log("request failed: %s" % e)
            items = []
        self._send(200, rss(items))

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/prefs":
            return self._send(404, "not found", "text/plain")
        if not PREFS_TOKEN or self.headers.get("X-Token") != PREFS_TOKEN:
            return self._send(403, '{"error":"forbidden"}', "application/json")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            key = set_preference(body.get("title", ""), body.get("preference", ""))
        except (ValueError, json.JSONDecodeError) as e:
            return self._send(400, json.dumps({"error": str(e)}), "application/json")
        log(f"edition preference for '{key}': {body['preference']}")
        self._send(200, json.dumps({"ok": True, "title": key}), "application/json")

    def log_message(self, fmt, *args):
        log("%s %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    os.makedirs(os.path.dirname(CACHE_FILE) or ".", exist_ok=True)
    log(f"listening on :{PORT}, source {BASE}, edition preference {EDITION_PREFERENCE}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
