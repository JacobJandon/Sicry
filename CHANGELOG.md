# Changelog

All notable changes to SICRY™ are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org).

---

## [2.1.6] — 2026-03-16

### Fixed
- **BUG-1** `score_results()` now sets **both** `"score"` and `"confidence"` keys
  (`r_copy["confidence"] = r_copy["score"] = …`).  Pipeline re-score after scrape
  (step 6) now updates the value shown in the console and in all export formats.
- **BUG-2** `crawl()` `links_found` no longer filters to `.onion`-only hrefs.  The
  capture block now records all outbound links (clearnet and onion alike); the crawl
  queue still correctly follows only `.onion` URLs.  Shallow `.onion` pages that link
  exclusively to clearnet URLs now return a non-empty `links_found`.
- **UX-4** `_DB.engine_reliability()` returns `None` instead of `1.0` when no engine
  health history exists.  `engine_reliability_scores()` return type updated to
  `dict[str, float | None]`.  `--engine-stats` prints `(no data)` for unchecked
  engines and sorts them below engines with real history.

### Improved
- **UX-2** `--watch-check` prints the top-5 result titles and URLs inline for every
  job whose status changed to NEW, so the operator can see what triggered the alert
  at a glance.  `watch_check()` alert dicts now include `last_run`, `interval_hours`,
  and `mode` keys so the pipeline can compute the next scheduled time.
- **UX-3** `--interactive` number-based fetch now runs `analyze_nollm()` on the
  fetched page text and prints an **Entities / Keywords** block after the page
  content, giving actionable intel without a separate analysis step.
- **IMPROVE-1** Pipeline step-1 output now includes a **TorPool** line when
  `SICRY_POOL_SIZE > 0`, showing the number of circuits and the socks-port range so
  operators can confirm multi-circuit mode is active.
- **IMPROVE-7** `--watch-check --output-dir DIR` saves each triggered (NEW) alert as
  `DIR/<job_id>.json`, enabling automated downstream processing of watch results.

---

## [2.1.5] — 2026-03-16

### Fixed
- **BUG-1** `score_results()` `AttributeError` when `query` is a `list` — added
  `isinstance(query, list): query = " ".join(...)` guard before `.lower()`.
- **BUG-2** `crawl()` `links_found` always empty — now records ALL `.onion` hrefs
  discovered on each page, independently of crawl-queue filters (depth, domain,
  visited). Added `_seen_links` dedup set; queue-building is unchanged.
- **BUG-3** BM25 `conf=0.0000` on thin content — `score_results()` now accepts
  `texts: dict[str,str] | None` param; pipeline re-scores `best` results after
  step 6 (scrape) using actual page text for richer IDF weighting.
- **BUG-5** `sync_sicry` bundled `sicry.py` lag — added `--check-bundled` flag
  that compares bundled version to latest upstream SICRY™ tag; exits `2` when
  behind so release scripts can enforce synchronisation.
- **BUG-6** Cache warm ≥ cold time — `_DB._conn()` now enables WAL journal mode
  and `PRAGMA synchronous=NORMAL` on every new connection; added
  `_SEARCH_MEM_CACHE` in-process dict so warm search-cache hits skip SQLite
  JSON deserialisation entirely.

### Added
- **UX-3** `--watch-disable` now validates the job ID against `watch_list()`
  before calling `watch_disable()`; prints a clear error and exits `1` if not
  found instead of silently doing nothing.
- **UX-4** `--modes` flag prints each mode name, engine list, `max_results`, and
  `scrape` counts, then exits.
- **UX-5** `--watch-check` output now includes `last=<timestamp>` and
  `next=<timestamp>` per job so overdue or stuck watches are obvious.
- **UX-6** `--misp-threat-level {1,2,3,4}` and `--misp-distribution {0..5}` flags
  pass through to `to_misp()` instead of being hardcoded at `2`/`0`.
- **UX-7** Both interactive modes (`--interactive` standalone and follow-up REPL)
  now handle `help`/`?` (prints available commands) and `history` (lists prior
  queries); standalone mode accepts a bare number to fetch result N directly.
- **IMPROVE-2** `--engine-stats` prints per-engine reliability score, last latency,
  and last-seen timestamp from `engine_reliability_scores()` /
  `engine_health_history()`.
- **IMPROVE-3** `--watch-daemon` runs `watch_check()` as a foreground loop with
  configurable `--interval` (minutes); `SIGINT` / Ctrl+C exits cleanly.
- **IMPROVE-4** MISP usage example added to pipeline `--help` epilog.
- **IMPROVE-5** `--check-update` now also fetches the latest SICRY™ upstream tag
  and prints a `NOTICE` when the bundled `sicry.py` is behind.
- **IMPROVE-6** `search_and_crawl()` deduplicates seed URLs by `.onion` domain
  before crawling — prevents the same hidden service being crawled multiple times
  when several search results share a domain.
- **IMPROVE-7** `crawl_export(job_id, format="json")` now accepts `"stix"`,
  `"misp"`, and `"csv"` format arguments, returning the same output as the
  corresponding `to_stix()` / `to_misp()` / `to_csv()` functions.
- **IMPROVE-8** `--output-dir DIR` flag auto-names output files as
  `DIR/<job_id>.<ext>` for batch / watch workflows (overrides `--out`).
- MISP epilog example, `sync_sicry --check-bundled` release guard.

### Changed
- `__version__` bumped to `2.1.5`.
- `sync_sicry --version` → `2.1.5`.

---

## [2.1.4] — 2026-03-16

### Fixed
- **CRITICAL-1** `check_engines.py` syntax error: `sys.exit(1)    if not args.json:` merged onto one line; split and verified `SYNTAX OK`.
- **CRITICAL-2** Added `"csam"` to `_CONTENT_BLACKLIST`.
- **CRITICAL-3** Added `("child","minor")` and `("kids","child")` to `_TOKEN_PAIR_BLACKLIST`.
- **BUG-1** `CrawlResult.links_found` changed from `int` to `list[str]`; crawl now appends URLs.
- **BUG-2** `crawl_export()` now SELECTs `text` and parses `entities` JSON string back to `dict`.
- **BUG-3** pipeline `new_count` → `result_count` in `--watch-check` output.

### Added
- `--format misp` in `pipeline.py`; calls `sicry.to_misp()`.
- `--watch-list` and `--watch-disable JOB_ID` in `pipeline.py`.
- Mode override `NOTE` printed when `--engines` overrides mode routing.

### Changed
- `__version__` → `2.1.4`.

---

## [2.1.3] — 2026-03-16

### Fixed
- `engine-history` / `engines` CLI sub-commands: `KeyError` on `j["id"]` when
  watch entries lacked the key; normalised via `.get("id","")`.
- `TorPool` constructor `TypeError` on `pool start` command.
- Tor pre-check guard added to `fetch.py`, `search.py`, `check_engines.py`.
- `watch_check()` `new_count` → `result_count` key normalisation.
- `crawl()` `on_page` callback signature enforced to 3-arg lambda.
- `_is_content_safe()` rake bypass gap closed.

### Changed
- `__version__` → `2.1.3`.

---

## [2.1.2] — 2026-03-16

### Fixed
- `check_engines.py` CLI: `KeyError` on `engines`/`engine-history`.
- Pool `start` sub-command `TypeError` (`size` kwarg).
- Tor pre-check added to `scrape.py` and `crawl.py` scripts.

### Changed
- `__version__` → `2.1.2`.

---

## [2.1.1] — 2026-03-16

### Fixed
- `check_tor()` false-positive: now probes SOCKS port before making a remote
  request, eliminating "Tor active" reports when the service is actually down.

### Changed
- `__version__` → `2.1.1`.

---

## [2.1.0] — 2026-03-16

### Added
- 15 `ResourceWarning` bare `open().read()` calls replaced with `_read_src()` / `_read_oc_src()` helpers.
- Full test suite at 419 tests, 0 failures (including live Tor tests).

---

## [2.0.0] — 2026-03-16

### Added
- Complete ground-up rewrite as SICRY™ v2  
- `TorPool`: multi-circuit Tor pool with round-robin session assignment.
- Persistent SQLite cache for fetch, search, engine health, watch jobs, crawl data.
- `crawl()` depth-first `.onion` spider with entity extraction, `CrawlResult` dataclass.
- `search_and_crawl()` combined search + concurrent crawl.
- `watch_add()` / `watch_check()` / `watch_disable()` / `watch_daemon()` alert system.
- `to_stix()`, `to_misp()`, `to_csv()` export formats.
- `engine_health_history()`, `engine_reliability_scores()` per-engine rolling stats.
- `analyze_nollm()` fully offline entity / keyword report (no LLM required).
- `deduplicate_results()` content-fingerprint dedup.
- 4 OSINT modes: `threat_intel`, `ransomware`, `personal_identity`, `corporate`.
- FastMCP server, full tool schemas for Anthropic / OpenAI / Gemini.
- OnionClaw `pipeline.py` OSINT pipeline with resume checkpoints, confidence scores, watch loop.

### Changed
- `__version__` → `2.0.0`.

---

## [1.2.2] — 2026-03-15

### Fixed
- **Tests**: Updated `TestVersion` to v1.2.2; added `TestCheckTorRenewFlags`,
  `TestSyncSicryDocs` classes; rewrote `TestCheckUpdate` mocks for Tags API.
  211 tests pass.

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
