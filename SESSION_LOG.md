# Session Log

## 2026-10-21 — ABB blocked our IP: VPN proxy, server switching, back-off

**Done**
- Found every ABB domain timing out from the home connection while it loaded on a phone:
  ABB had blocked the home IP. Confirmed by loading ABB through a VPN HTTP proxy.
- `ABB_PROXY` (passed to the container as `HTTPS_PROXY`, which urllib already honours):
  ABB requests leave through a VPN. Empty means direct, as before.
- `fetch` now counts failures. After 3 in a row it asks the proxy VPN's Gluetun control API
  (`ABB_VPN_CONTROL`, `ABB_VPN_KEY`) for a new server (up to 3 switches, 30 s settle each);
  then, or straight away without VPN control, it leaves ABB alone for 30 minutes and answers
  empty. Any success resets the count. Control calls never go through the proxy.
- Deployed with a VPN container of its own (not the torrent one), random servers across
  several regions. README, `.env.example` and `docker-compose.yml` document the settings.

**Verification**
- 21 unit tests pass (5 new in `BlockTests`).
- Live: searches answered through the VPN; "Dark Age" returned only the Dramatized
  Adaptation and Harry Potter only the Full-Cast edition (full-cast rule confirmed). A server
  switch called from inside the container succeeded and the next search worked.

**Next steps**
- Watch logs for `switched VPN server` / `leaving it alone`: frequent switches mean ABB is
  blocking VPN ranges too.
- Minor ranking gap seen live: a Hindi edition appears for The Sandman. (The "Red Rising
  Series from AUDIBLE" bundle gap was fixed the same day: a series named up front with no
  book number now counts as a bundle.)

## 2026-10-20 — Initial build, public release, part/bundle fixes

**Done**
- Built the AudioBook Bay → Torznab bridge; deployed as a container; added to Prowlarr as a
  Generic Torznab indexer and to ReadMeABook at top priority (25 vs 10).
- Search: pooled query variants (full, title after series colon, shortened) ranked by
  title-word overlap; latest uploads for empty queries (connection test / RSS).
- `EDITION_PREFERENCE` (produced | narrated | any) and per-book choices via `POST /prefs`
  (token-protected), used by the request app's Edition toggle.
- Fixes from real use: part requests ("Dark Age (1 of 3)") no longer get another part;
  multi-book bundles, "Entire … Collection" and number-range titles are dropped unless asked
  for; ABB outages answer empty and aren't cached.
- Repo made public with deployment details moved to uncommitted `deploy.env` / `.env`.

**Verification**
- 16 unit tests pass (`python3 -m unittest discover -s tests`).
- Live: ReadMeABook picked ABB releases (scores 153–178) and imported them; part and bundle
  filters confirmed on real queries.

**Next steps**
- Watch for ABB layout changes (parse tests describe the expected HTML).
- Consider surfacing the edition actually chosen back to the requester.
