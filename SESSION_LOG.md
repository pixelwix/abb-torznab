# Session Log

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
