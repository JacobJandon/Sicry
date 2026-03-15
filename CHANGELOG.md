# Changelog

All notable changes to SICRY™ are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org).

---

## [1.2.1] — 2026-03-15

### Fixed
- **Tests**: Updated `TestPipelineFixes.test_out_exits_1_on_oserror` to match
  the broadened `except Exception` handler introduced in v1.2.1 of OnionClaw;
  added `test_out_handler_not_bare_oserror` guard. 190 tests pass.
- **Tests**: Added `TestSetupChmod.test_chmod_runs_before_early_return` and
  `TestSetupPyAuthAndMCP` AUTH-1 assertions for `_fix_cookie_auth()`,
  `CookieAuthFileGroupReadable`, and systemd drop-in constants.

---

## [1.2.0] — 2026-03-15

### Added
- **SAFETY-1 gap fix**: `_TOKEN_PAIR_BLACKLIST` token-pair matching in
  `_is_content_safe()` — blocks evasive titles like “KIDS – CHILD – RAPE”
  that bypassed single-phrase matching. Also added standalone dangerous terms
  (rape video, torture porn, kids sex, child rape, etc.)
- **Persistent fetch cache**: `_CACHE_FILE` (`/tmp/onionclaw_cache.json`) —
  cache now survives between process restarts via `_save_disk_cache()` /
  `_load_disk_cache()`. Override path with `SICRY_CACHE_FILE` env var.
- **`clear_cache()` function**: wipes memory + disk cache; returns evicted count
- **`clear-cache` CLI command**: `python sicry.py clear-cache`
- **`--version` flag**: all CLI entry-points now respond to `--version`

### Security
- **Redirect de-anonymization blocked**: `fetch()` now detects when a `.onion`
  request is silently redirected to a clearnet URL and returns an error dict
  with `"de-anonymization"` in the message instead of leaking the request.
- **User-Agent rotation confirmed** (already in v1.1.0, now explicitly tested)

### Changed
- `__version__` bumped to `1.2.0`
- `_is_content_safe()` now also applies `_TOKEN_PAIR_BLACKLIST` after phrase match

---

## [1.1.0] — 2026-03-15

### Added
- `fetch()` 10-minute TTL result cache (`_FETCH_CACHE`) controlled via
  `SICRY_CACHE_TTL` env var (default 600 s; 0 = disabled)
- `SICRY_CACHE_TTL` added to `.env.example`

### Changed
- `SEARCH_ENGINES` reduced from 18 to 12 — removed permanently-dead engines:
  Torgle, Kaizer, Anima, Tornado, TorNet, FindTor (all offline as of 2026-Q1)
- Docstring / comment counts updated: "18 engines" → "12 engines"

### Fixed
- `fetch()`: HTTPS → HTTP automatic fallback for `.onion` addresses
  (most hidden services are HTTP-only; HTTPS fetch now retries as HTTP before
  returning an error)
- `fetch()`: SOCKS-level retry — rebuilds Tor session and retries once on
  `SOCKS5`, `timed out`, or `ConnectionError` exceptions, then falls through
  to the HTTP fallback variant if both attempts fail

---

## [1.0.0] — 2026-03-14

### Added
- 18 dark web search engines (14 .onion engines + 4 clearnet Tor-routed fallbacks)
- 6 agent tools: `search`, `fetch`, `check_tor`, `renew_identity`, `ask`, `dispatch`
- Native tool schemas for Anthropic, OpenAI, and Gemini
- FastMCP server (`python3 sicry.py serve`)
- 4 LLM analysis modes: `summary`, `entity`, `threat`, `ioc`
- Full Robin OSINT pipeline baked in — no separate Robin install needed
- Tor authentication: cookie, password, hash, and unauthenticated fallback
- `__version__ = "1.0.0"`
- GitHub Actions CI (Python 3.9–3.12)
- `CONTRIBUTING.md`, `SECURITY.md`, issue templates

### Fixed
- URL extraction now includes clearnet fallback when no `.onion` links found (fixes DuckDuckGo-Tor / Ahmia-clearnet returning 0 results)
- Ahmia `/redirect/?redirect_url=` wrapper decoded correctly
- CSS selector result containers targeted before falling back to all `<a>` tags
- `ANTHROPIC_MODEL` corrected to `claude-opus-4-5`
- Unclosed file handle in `renew_identity()` replaced with `with open()` block

---

<!-- next release goes here
## [Unreleased]
### Added
### Changed
### Fixed
### Removed
-->

[1.0.0]: https://github.com/JacobJandon/Sicry/releases/tag/v1.0.0
