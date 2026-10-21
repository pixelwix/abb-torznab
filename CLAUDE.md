# AGENTS.md — abb-torznab

Instructions for AI coding agents (Claude Code, Codex, Gemini) working in this repo.
Human-facing setup and usage live in `README.md`; read it first.

## What this is

A single-file Python (standard library only) bridge that exposes AudioBook Bay as a
Torznab indexer for Prowlarr / ReadMeABook. Entry point: `app.py`.

Layout of `app.py`, top to bottom: configuration → ABB access (`fetch`, `parse_search`,
`parse_detail`) → caches → search strategy (`clean_query`, `title_part`, `query_variants`,
`rank`, `search`, `latest`) → per-book edition choices (`set_preference`,
`preference_for`) → Torznab output (`CAPS`, `rss`) → HTTP server (`Handler`).

## Rules

- **Public repo.** Never commit hostnames, internal IPs, container IDs, tokens or any
  detail of a specific deployment. Deployment settings belong in the uncommitted
  `deploy.env` / `.env` files (templates: `deploy.env.example`, `.env.example`).
- **Standard library only.** No third-party dependencies.
- **Tests first.** Every change to parsing or ranking gets a test in `tests/test_app.py`
  built from the real HTML shape or a real failing query. Run:
  `python3 -m unittest discover -s tests`. `deploy.sh` refuses to deploy on failure.
- **Fail soft.** If ABB is down or changes, answer an empty result list (never an error,
  never cache the empty answer) so clients fall back to other indexers.
- **Be gentle with ABB.** Every ABB request goes through `fetch`, which counts failures,
  switches VPN server through Gluetun's control API (`ABB_VPN_CONTROL`) and then pauses ABB
  requests for 30 minutes. Don't add ABB requests that bypass it, and don't add request volume
  (more variants, more parallel detail fetches, shorter caches) without a reason: ABB has
  blocked a deployment's IP before.
- **Ranking rules are behaviour, not style.** Keep these unless the user changes them:
  - pooled multi-variant search, ranked by title-word overlap;
  - edition preference (`produced` default: dramatized / full cast / GraphicAudio wins);
  - a request for part N of M never gets a different part;
  - multi-book bundles (book ranges, complete series, box sets, number ranges) are
    dropped unless the query asks for a bundle.
- Keep `README.md` in sync with behaviour and settings, and add a `SESSION_LOG.md`
  entry at the end of each working session.

## Deploy

`./deploy.sh` (needs a local `deploy.env`): tests → copy files → `docker compose up -d
--build` → health check. Commit and push after a verified deploy.
