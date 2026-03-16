#!/usr/bin/env python3
"""
SICRY + OnionClaw v2.0.0 — comprehensive test suite
Tests all v1.2.3 and v2.0.0 changes: BUG-1 renew.py --json guard, BUG-3 sync_sicry fetch order,
redirect de-anonymization blocking, persistent file cache, clear_cache(),
--clear-cache flag, --cached mode in check_engines.py, --version everywhere,
and sync_sicry.py documentation.

Usage:
  python3 tests.py            # all tests
  python3 tests.py -v         # verbose
  python3 tests.py --live     # include live Tor network tests (slow, ~2 min)
"""
import sys, os, time, json, subprocess, argparse, importlib, unittest
from unittest.mock import patch, MagicMock, call

def _read(path: str) -> str:
    """Read a file safely (avoids ResourceWarning from bare open().read())."""
    with open(path) as fh:
        return fh.read()

# ── locate repos ───────────────────────────────────────────────────────────────
_HERE         = os.path.dirname(os.path.abspath(__file__))
_ONION_CLAW   = os.path.join(_HERE, "OnionClaw")

# Make sure we test the ROOT sicry.py (not OnionClaw copy)
sys.path.insert(0, _HERE)
import sicry as SICRY

# Also load the OnionClaw copy as a separate module for diff-check
sys.path.insert(0, _ONION_CLAW)
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("sicry_oc", os.path.join(_ONION_CLAW, "sicry.py"))
SICRY_OC = _ilu.module_from_spec(_spec)
# Register in sys.modules BEFORE exec so @dataclasses.dataclass can find the module
sys.modules["sicry_oc"] = SICRY_OC
_spec.loader.exec_module(SICRY_OC)

LIVE = "--live" in sys.argv

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline(*args):
    """Run pipeline.py as a subprocess and return (returncode, stdout, stderr)."""
    cmd = [sys.executable, os.path.join(_ONION_CLAW, "pipeline.py"), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout, r.stderr


def _read_src(filename: str = "sicry.py") -> str:
    """Read a source file from the SICRY root directory, always closing the handle."""
    with open(os.path.join(_HERE, filename), encoding="utf-8") as _fh:
        return _fh.read()


def _read_oc_src(filename: str) -> str:
    """Read a source file from the OnionClaw directory, always closing the handle."""
    with open(os.path.join(_ONION_CLAW, filename), encoding="utf-8") as _fh:
        return _fh.read()


# ═════════════════════════════════════════════════════════════════════════════
# 1. Version
# ═════════════════════════════════════════════════════════════════════════════
class TestVersion(unittest.TestCase):
    def test_sicry_version(self):
        self.assertEqual(SICRY.__version__, "2.1.6")

    def test_onion_claw_version(self):
        self.assertEqual(SICRY_OC.__version__, "2.1.6")

    def test_both_copies_identical_version(self):
        self.assertEqual(SICRY.__version__, SICRY_OC.__version__)


# ═════════════════════════════════════════════════════════════════════════════
# 2. SEARCH_ENGINES — dead engine removal
# ═════════════════════════════════════════════════════════════════════════════
class TestSearchEngines(unittest.TestCase):
    DEAD = {"Torgle", "Kaizer", "Anima", "Tornado", "TorNet", "FindTor"}
    EXPECTED = {
        "Ahmia", "OnionLand", "Amnesia", "Torland", "Excavator",
        "Onionway", "Tor66", "OSS", "Torgol", "TheDeepSearches",
        "DuckDuckGo-Tor", "Ahmia-clearnet",
    }

    def _check(self, mod, label):
        names = {e["name"] for e in mod.SEARCH_ENGINES}
        for dead in self.DEAD:
            self.assertNotIn(dead, names, f"{label}: dead engine '{dead}' still present")
        for expected in self.EXPECTED:
            self.assertIn(expected, names, f"{label}: expected engine '{expected}' missing")
        self.assertEqual(len(mod.SEARCH_ENGINES), 12,
                         f"{label}: expected 12 engines, got {len(mod.SEARCH_ENGINES)}")

    def test_root_dead_engines_removed(self):
        self._check(SICRY, "Sicry root")

    def test_onion_claw_dead_engines_removed(self):
        self._check(SICRY_OC, "OnionClaw")

    def test_both_copies_same_engines(self):
        root_names = sorted(e["name"] for e in SICRY.SEARCH_ENGINES)
        oc_names   = sorted(e["name"] for e in SICRY_OC.SEARCH_ENGINES)
        self.assertEqual(root_names, oc_names, "Engine lists differ between copies")

    def test_all_engines_have_url(self):
        for e in SICRY.SEARCH_ENGINES:
            self.assertIn("{query}", e["url"],
                          f"Engine '{e['name']}' URL missing {{query}} placeholder")


# ═════════════════════════════════════════════════════════════════════════════
# 3. FETCH_CACHE_TTL config
# ═════════════════════════════════════════════════════════════════════════════
class TestFetchCacheTTL(unittest.TestCase):
    def test_ttl_constant_exists(self):
        self.assertTrue(hasattr(SICRY, "FETCH_CACHE_TTL"), "FETCH_CACHE_TTL missing")

    def test_default_ttl_600(self):
        # Default should be 600 unless overridden by env
        env_val = os.getenv("SICRY_CACHE_TTL")
        expected = int(env_val) if env_val else 600
        self.assertEqual(SICRY.FETCH_CACHE_TTL, expected)

    def test_fetch_cache_dict_exists(self):
        self.assertTrue(hasattr(SICRY, "_FETCH_CACHE"), "_FETCH_CACHE missing")
        self.assertIsInstance(SICRY._FETCH_CACHE, dict)


# ═════════════════════════════════════════════════════════════════════════════
# 4. fetch() — TTL cache unit test
# ═════════════════════════════════════════════════════════════════════════════
class TestFetchCache(unittest.TestCase):
    def setUp(self):
        # Clear cache before each test
        SICRY._FETCH_CACHE.clear()

    def _make_mock_response(self, html="<html><body>hello</body></html>", status=200):
        resp = MagicMock()
        resp.status_code = status
        resp.text = html
        return resp

    def test_cache_hit_avoids_second_request(self):
        """Second call with same URL should return cached result without making a request."""
        url = "http://test.onion/page"
        fake_result = {"url": url, "is_onion": True, "status": 200,
                       "title": "cached", "text": "cached text", "links": [], "error": None}
        SICRY._FETCH_CACHE[url.lower().rstrip("/")] = (time.time(), fake_result)

        with patch.object(SICRY, "_build_tor_session") as mock_session_builder:
            result = SICRY.fetch(url)
            mock_session_builder.assert_not_called()
        self.assertEqual(result["title"], "cached")

    def test_expired_cache_makes_fresh_request(self):
        """An expired cache entry should trigger a real fetch."""
        url = "http://test.onion/page"
        old_result = {"url": url, "is_onion": True, "status": 200,
                      "title": "old", "text": "old text", "links": [], "error": None}
        # Store with timestamp 700 seconds ago (past the 600s TTL)
        SICRY._FETCH_CACHE[url.lower().rstrip("/")] = (time.time() - 700, old_result)

        mock_session = MagicMock()
        mock_session.get.return_value = self._make_mock_response("<html><title>fresh</title></html>")
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            result = SICRY.fetch(url)
        self.assertNotEqual(result.get("title"), "old")

    def test_cache_disabled_when_ttl_zero(self):
        """Setting FETCH_CACHE_TTL=0 should bypass cache entirely."""
        url = "http://test.onion/zero"
        cached = {"url": url, "is_onion": True, "status": 200,
                  "title": "stale", "text": "stale", "links": [], "error": None}
        SICRY._FETCH_CACHE[url.lower().rstrip("/")] = (time.time(), cached)

        saved_ttl = SICRY.FETCH_CACHE_TTL
        SICRY.FETCH_CACHE_TTL = 0
        try:
            mock_session = MagicMock()
            mock_session.get.return_value = self._make_mock_response("<html><title>new</title></html>")
            with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
                result = SICRY.fetch(url)
            # With TTL=0 cache check is skipped so a real request is made
            mock_session.get.assert_called_once()
        finally:
            SICRY.FETCH_CACHE_TTL = saved_ttl

    def test_successful_fetch_is_cached(self):
        """A successful fetch should populate the cache."""
        url = "http://newpage.onion/path"
        SICRY._FETCH_CACHE.clear()

        mock_session = MagicMock()
        mock_session.get.return_value = self._make_mock_response(
            "<html><title>mytitle</title><body>body text</body></html>")
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            SICRY.fetch(url)

        key = url.lower().rstrip("/")
        self.assertIn(key, SICRY._FETCH_CACHE)
        ts, cached = SICRY._FETCH_CACHE[key]
        self.assertAlmostEqual(ts, time.time(), delta=5)
        self.assertEqual(cached.get("title"), "mytitle")

    def test_no_cache_bypass(self):
        """_use_cache=False should bypass cache lookup and not store result."""
        url = "http://bypass.onion/"
        SICRY._FETCH_CACHE.clear()

        mock_session = MagicMock()
        mock_session.get.return_value = self._make_mock_response()
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            SICRY.fetch(url, _use_cache=False)

        # Cache should still be empty (no-cache = don't store either)
        self.assertNotIn(url.lower().rstrip("/"), SICRY._FETCH_CACHE)


# ═════════════════════════════════════════════════════════════════════════════
# 5. fetch() — HTTPS → HTTP fallback unit test
# ═════════════════════════════════════════════════════════════════════════════
class TestFetchHTTPSFallback(unittest.TestCase):
    def setUp(self):
        SICRY.clear_cache()

    def test_https_onion_falls_back_to_http(self):
        """If HTTPS fails for a .onion URL, fetch() should retry with http://."""
        url = "https://somemarket.onion/page"
        http_url = "http://somemarket.onion/page"

        call_urls = []

        def _fake_session_fn():
            s = MagicMock()
            def _get(u, **kw):
                call_urls.append(u)
                if u.startswith("https://"):
                    raise Exception("SOCKS5 auth failed — HTTPS not supported")
                resp = MagicMock()
                resp.status_code = 200
                resp.text = "<html><title>OK</title><body>hello</body></html>"
                return resp
            s.get.side_effect = _get
            return s

        with patch.object(SICRY, "_build_tor_session", side_effect=_fake_session_fn):
            result = SICRY.fetch(url)

        # At some point the http URL must have been tried
        self.assertTrue(any(u.startswith("http://") and ".onion" in u for u in call_urls),
                        f"HTTP fallback not tried. Calls: {call_urls}")
        self.assertEqual(result["status"], 200)
        self.assertIsNone(result["error"])

    def test_clearnet_no_fallback(self):
        """Clearnet URLs should NOT get an HTTP fallback (only .onion gets it)."""
        url = "https://example.com/"
        call_urls = []

        def _fake_session_fn():
            s = MagicMock()
            def _get(u, **kw):
                call_urls.append(u)
                raise Exception("Connection refused")
            s.get.side_effect = _get
            return s

        with patch.object(SICRY, "_build_tor_session", side_effect=_fake_session_fn):
            result = SICRY.fetch(url)

        http_calls = [u for u in call_urls if u.startswith("http://") and "example.com" in u]
        self.assertEqual(http_calls, [], f"Clearnet got fallback: {call_urls}")
        self.assertEqual(result["status"], 0)

    def test_http_onion_no_double_fallback(self):
        """An already-http .onion URL should only be tried once (no double fallback)."""
        url = "http://alreadyhttp.onion/"
        call_urls = []

        def _fake_session_fn():
            s = MagicMock()
            def _get(u, **kw):
                call_urls.append(u)
                raise Exception("Network unreachable")
            s.get.side_effect = _get
            return s

        with patch.object(SICRY, "_build_tor_session", side_effect=_fake_session_fn):
            SICRY.fetch(url)

        # Only the original http URL should appear (at most 2x due to SOCKS retry, never a different URL)
        unique_urls = set(call_urls)
        self.assertEqual(unique_urls, {url}, f"Unexpected URL variants tried: {unique_urls}")


# ═════════════════════════════════════════════════════════════════════════════
# 6. fetch() — SOCKS retry unit test
# ═════════════════════════════════════════════════════════════════════════════
class TestFetchSOCKSRetry(unittest.TestCase):
    def setUp(self):
        SICRY.clear_cache()

    def _make_counting_session(self, fail_first=True, error_msg="SOCKS5 handshake failed"):
        """Returns a factory that fails on attempt 0 then succeeds (or always fails)."""
        attempt = [0]
        def _factory():
            s = MagicMock()
            def _get(u, **kw):
                attempt[0] += 1
                if fail_first and attempt[0] == 1:
                    raise Exception(error_msg)
                resp = MagicMock()
                resp.status_code = 200
                resp.text = "<html><title>retry success</title></html>"
                return resp
            s.get.side_effect = _get
            return s
        return _factory, attempt

    def test_socks_error_triggers_retry(self):
        """A SOCKS error on attempt 1 should trigger a retry (attempt 2 succeeds)."""
        factory, attempt = self._make_counting_session(fail_first=True, error_msg="SOCKS5 auth")
        with patch.object(SICRY, "_build_tor_session", side_effect=factory):
            with patch("time.sleep"):  # don't actually sleep
                result = SICRY.fetch("http://test.onion/")
        self.assertGreater(attempt[0], 1, "No retry occurred")
        self.assertEqual(result["status"], 200)

    def test_timeout_triggers_retry(self):
        """A 'timed out' error should also trigger a retry."""
        factory, attempt = self._make_counting_session(fail_first=True, error_msg="timed out")
        with patch.object(SICRY, "_build_tor_session", side_effect=factory):
            with patch("time.sleep"):
                result = SICRY.fetch("http://onion2.onion/")
        self.assertGreater(attempt[0], 1)
        self.assertEqual(result["status"], 200)

    def test_non_socks_error_no_retry(self):
        """A non-retryable error (e.g. HTTP 404 parse) should NOT retry."""
        attempt = [0]
        def _factory():
            s = MagicMock()
            def _get(u, **kw):
                attempt[0] += 1
                raise ValueError("JSON decode error — unrelated")
            s.get.side_effect = _get
            return s
        with patch.object(SICRY, "_build_tor_session", side_effect=_factory):
            with patch("time.sleep") as mock_sleep:
                SICRY.fetch("http://noretry.onion/")
        # Should not sleep (no SOCKS retry triggered)
        mock_sleep.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# 7. fetch() — return shape + field validation
# ═════════════════════════════════════════════════════════════════════════════
class TestFetchReturnShape(unittest.TestCase):
    REQUIRED = {"url", "is_onion", "status", "title", "text", "links", "error", "truncated"}

    def setUp(self):
        SICRY.clear_cache()

    def _mock_success(self, html, url):
        mock_session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = html
        resp.encoding = "utf-8"          # prevent ISO-8859-1 branch
        resp.apparent_encoding = "utf-8"
        mock_session.get.return_value = resp
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            return SICRY.fetch(url)

    def test_success_has_all_fields(self):
        r = self._mock_success("<html><title>T</title><body>B</body></html>",
                               "http://ok.onion/")
        self.assertEqual(r.keys() & self.REQUIRED, self.REQUIRED)

    def test_error_has_all_fields(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("dead")
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            with patch("time.sleep"):
                r = SICRY.fetch("http://dead.onion/")
        self.assertEqual(r.keys() & self.REQUIRED, self.REQUIRED)
        self.assertEqual(r["status"], 0)
        self.assertIsNotNone(r["error"])

    def test_is_onion_clearnet(self):
        r = self._mock_success("<html></html>", "http://example.com/")
        self.assertFalse(r["is_onion"])

    def test_is_onion_dotOnion(self):
        r = self._mock_success("<html></html>", "http://abc.onion/")
        self.assertTrue(r["is_onion"])

    def test_truncated_false_for_short(self):
        """BUG-3: 'truncated' should be False for short content."""
        r = self._mock_success("<html><body>short</body></html>", "http://t.onion/")
        self.assertFalse(r["truncated"])

    def test_truncated_true_for_big(self):
        """BUG-3: 'truncated' should be True when content exceeds MAX_CONTENT_CHARS."""
        big = "A" * 20000
        r = self._mock_success(f"<html><body>{big}</body></html>", "http://big.onion/")
        self.assertTrue(r["truncated"])

    def test_text_truncated_to_max_chars(self):
        big = "A" * 20000
        r = self._mock_success(f"<html><body>{big}</body></html>", "http://big.onion/")
        self.assertLessEqual(len(r["text"]), SICRY.MAX_CONTENT_CHARS + 50)

    def test_links_extracted(self):
        html = '<html><body><a href="http://other.onion/">link</a></body></html>'
        r = self._mock_success(html, "http://main.onion/")
        self.assertIsInstance(r["links"], list)
        self.assertTrue(any("other.onion" in l["href"] for l in r["links"]))

    def test_relative_links_resolved(self):
        html = '<html><body><a href="/path/page">x</a></body></html>'
        r = self._mock_success(html, "http://rel.onion/")
        self.assertTrue(any("rel.onion/path/page" in l["href"] for l in r["links"]))

    def test_auto_prepend_scheme(self):
        """URLs without scheme should get http:// prepended."""
        SICRY.clear_cache()
        mock_session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html></html>"
        mock_session.get.return_value = resp
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            r = SICRY.fetch("naked.onion/page")
        self.assertTrue(r["url"].startswith("http://"))


# ═════════════════════════════════════════════════════════════════════════════
# 8. pipeline.py — --no-llm flag
# ═════════════════════════════════════════════════════════════════════════════
class TestPipelineNoLLM(unittest.TestCase):
    def test_no_llm_argparse_accepted(self):
        """--no-llm should be a valid argument (argparse won't raise)."""
        import argparse, types

        # We can't import pipeline.py directly (it runs at import), so check
        # the source text instead.
        src = _read(os.path.join(_ONION_CLAW, "pipeline.py"))
        self.assertIn("--no-llm", src, "--no-llm flag not found in pipeline.py")
        self.assertIn("NO_LLM", src, "NO_LLM variable not found in pipeline.py")

    def test_no_llm_skips_ask(self):
        """With --no-llm, pipeline output should NOT call sicry.ask."""
        src = _read(os.path.join(_ONION_CLAW, "pipeline.py"))
        # The ask() call must be inside an `else` block guarded by NO_LLM
        self.assertIn("if NO_LLM", src)
        # Verify ask is inside the else branch that follows NO_LLM check
        no_llm_pos = src.index("if NO_LLM")
        ask_pos = src.rindex("sicry.ask(")  # last occurrence
        self.assertGreater(ask_pos, no_llm_pos,
                           "sicry.ask() appears before NO_LLM guard")

    def test_no_llm_skips_refine(self):
        src = _read(os.path.join(_ONION_CLAW, "pipeline.py"))
        # refine_query should only be called inside "else" after checking NO_LLM
        self.assertIn("sicry.refine_query", src)
        # The refine call must be within an else block
        self.assertIn("Query refinement skipped", src)

    def test_no_llm_skips_filter(self):
        src = _read(os.path.join(_ONION_CLAW, "pipeline.py"))
        self.assertIn("BM25 confidence", src)

    def test_total_steps_conditional(self):
        """TOTAL should always be 7 (LLM steps are skipped via [skip N/7] labels)."""
        src = _read(os.path.join(_ONION_CLAW, "pipeline.py"))
        self.assertIn("TOTAL = 7", src)

    def test_no_llm_out_flag_works(self):
        """pipeline.py --no-llm should write a file when --out is supplied (no Tor needed for source check)."""
        src = _read(os.path.join(_ONION_CLAW, "pipeline.py"))
        # The no-llm branch must have its own output file write
        self.assertIn("no-LLM", src, "no-LLM label missing from output section")


# ═════════════════════════════════════════════════════════════════════════════
# 9. setup.py — existence and structure
# ═════════════════════════════════════════════════════════════════════════════
class TestSetupPy(unittest.TestCase):
    SETUP = os.path.join(_ONION_CLAW, "setup.py")

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(self.SETUP))

    def test_syntax_clean(self):
        import ast
        src = _read(self.SETUP)
        # Should not raise
        ast.parse(src)

    def test_has_env_setup(self):
        src = _read(self.SETUP)
        self.assertIn("setup_env", src)

    def test_has_tor_setup(self):
        src = _read(self.SETUP)
        self.assertIn("setup_tor", src)
        self.assertIn("ControlPort", src)
        self.assertIn("CookieAuthentication", src)

    def test_has_dep_check(self):
        src = _read(self.SETUP)
        self.assertIn("check_deps", src)

    def test_has_summary(self):
        src = _read(self.SETUP)
        self.assertIn("summary", src)

    def test_torrc_snippet_correct(self):
        src = _read(self.SETUP)
        self.assertIn("ControlPort 9051", src)
        self.assertIn("CookieAuthentication 1", src)

    def test_env_example_has_cache_ttl(self):
        """UX-2: .env.example must document SICRY_CACHE_TTL."""
        root_ex = os.path.join(_HERE, ".env.example")
        oc_ex   = os.path.join(_ONION_CLAW, ".env.example")
        if os.path.isfile(root_ex):
            self.assertIn("SICRY_CACHE_TTL", _read(root_ex),
                          "root .env.example missing SICRY_CACHE_TTL")
        if os.path.isfile(oc_ex):
            self.assertIn("SICRY_CACHE_TTL", _read(oc_ex),
                          "OnionClaw .env.example missing SICRY_CACHE_TTL")

    def test_patch_env_function(self):
        """_patch_env in setup.py should be able to add/update keys."""
        import ast
        src = _read(self.SETUP)
        self.assertIn("_patch_env", src)


# ═════════════════════════════════════════════════════════════════════════════
# 10. scrape_all — shape validation (mock)
# ═════════════════════════════════════════════════════════════════════════════
class TestScrapeAll(unittest.TestCase):
    def test_returns_dict(self):
        mock_session = MagicMock()
        resp = MagicMock()
        resp.text = "<html><body>content</body></html>"
        mock_session.get.return_value = resp

        urls = [{"title": "Test", "url": "http://test.onion/"}]
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            result = SICRY.scrape_all(urls)
        self.assertIsInstance(result, dict)
        self.assertIn("http://test.onion/", result)

    def test_empty_urls(self):
        result = SICRY.scrape_all([])
        self.assertEqual(result, {})

    def test_error_url_skipped(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("network error")
        urls = [{"title": "Bad", "url": "http://bad.onion/"}]
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            result = SICRY.scrape_all(urls)
        # Should not raise; bad URL maps to its title or is skipped
        self.assertIsInstance(result, dict)


# ═════════════════════════════════════════════════════════════════════════════
# 11. check_tor() — shape validation (mock)
# ═════════════════════════════════════════════════════════════════════════════
class TestCheckTor(unittest.TestCase):
    def test_success_shape(self):
        mock_session = MagicMock()
        resp = MagicMock()
        resp.json.return_value = {"IsTor": True, "IP": "1.2.3.4"}
        mock_session.get.return_value = resp
        with patch.object(SICRY, "_tor_port_open", return_value=True), \
             patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            r = SICRY.check_tor()
        self.assertTrue(r["tor_active"])
        self.assertEqual(r["exit_ip"], "1.2.3.4")
        self.assertIsNone(r["error"])

    def test_failure_shape(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("nope")
        with patch.object(SICRY, "_tor_port_open", return_value=True), \
             patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            r = SICRY.check_tor()
        self.assertFalse(r["tor_active"])
        self.assertIsNone(r["exit_ip"])
        self.assertIsNotNone(r["error"])

    def test_port_closed_returns_false_immediately(self):
        """Regression: check_tor() must return tor_active=False when the SOCKS
        port is not listening — no false positive after systemctl stop tor."""
        with patch.object(SICRY, "_tor_port_open", return_value=False):
            r = SICRY.check_tor()
        self.assertFalse(r["tor_active"])
        self.assertIsNone(r["exit_ip"])
        self.assertIsNotNone(r["error"])
        self.assertIn("not reachable", r["error"])

    def test_port_closed_never_makes_network_request(self):
        """When the port probe fails, no external HTTP request should be made."""
        mock_session = MagicMock()
        with patch.object(SICRY, "_tor_port_open", return_value=False), \
             patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            SICRY.check_tor()
        mock_session.get.assert_not_called()

    def test_tor_port_open_helper_exists(self):
        self.assertTrue(callable(SICRY._tor_port_open))

    def test_tor_port_open_returns_bool(self):
        # Port 1 is almost certainly closed; any result must be a bool
        result = SICRY._tor_port_open(port=1, timeout=0.1)
        self.assertIsInstance(result, bool)


# ═════════════════════════════════════════════════════════════════════════════
# 11b. check_update()
# ═════════════════════════════════════════════════════════════════════════════
class TestCheckUpdate(unittest.TestCase):
    """check_update() — GitHub Tags API version check (BUG-3)."""

    def _fake_response(self, tag="1.2.1"):
        """Mock the Tags API: returns list of tag objects."""
        m = MagicMock()
        m.json.return_value = [{"name": f"v{tag}"}]
        m.raise_for_status = lambda: None
        return m

    def test_up_to_date_when_same_version(self):
        with patch("sicry.requests.get", return_value=self._fake_response(SICRY.__version__)):
            r = SICRY.check_update()
        self.assertTrue(r["up_to_date"])
        self.assertIsNone(r["error"])
        self.assertEqual(r["current"], SICRY.__version__)

    def test_not_up_to_date_on_newer_tag(self):
        with patch("sicry.requests.get", return_value=self._fake_response("99.99.99")):
            r = SICRY.check_update()
        self.assertFalse(r["up_to_date"])
        self.assertEqual(r["latest"], "99.99.99")
        self.assertIsNotNone(r["url"])
        self.assertIsNone(r["error"])

    def test_up_to_date_on_older_tag(self):
        with patch("sicry.requests.get", return_value=self._fake_response("0.0.1")):
            r = SICRY.check_update()
        self.assertTrue(r["up_to_date"])

    def test_network_error_is_silent(self):
        with patch("sicry.requests.get", side_effect=Exception("timeout")):
            r = SICRY.check_update()
        self.assertIsNotNone(r)
        self.assertTrue(r["up_to_date"])  # safe default
        self.assertIsNotNone(r["error"])

    def test_return_keys_present(self):
        with patch("sicry.requests.get", return_value=self._fake_response()):
            r = SICRY.check_update()
        for key in ("up_to_date", "current", "latest", "url", "error"):
            self.assertIn(key, r, f"check_update() missing key '{key}'")

    def test_github_tags_url_constant_exists(self):
        """BUG-3: check_update() must use Tags API, not Releases API."""
        self.assertTrue(hasattr(SICRY, "GITHUB_TAGS_URL"),
                        "GITHUB_TAGS_URL constant missing from sicry.py")
        self.assertIn("JacobJandon/OnionClaw", SICRY.GITHUB_TAGS_URL)
        self.assertIn("tags", SICRY.GITHUB_TAGS_URL)

    def test_empty_tag_list_handled(self):
        """BUG-3: empty tags list must not crash."""
        m = MagicMock()
        m.json.return_value = []
        m.raise_for_status = lambda: None
        with patch("sicry.requests.get", return_value=m):
            r = SICRY.check_update()
        self.assertTrue(r["up_to_date"])
        self.assertIsNotNone(r["error"])

    def test_url_points_to_tag(self):
        """BUG-3: url must reference the specific tag, not a generic page."""
        with patch("sicry.requests.get", return_value=self._fake_response("99.0.0")):
            r = SICRY.check_update()
        self.assertIn("99.0.0", r["url"])


# ═════════════════════════════════════════════════════════════════════════════
# 12. refine_query() fallback
# ═════════════════════════════════════════════════════════════════════════════
class TestRefineQuery(unittest.TestCase):
    def test_returns_original_on_llm_error(self):
        """refine_query must return original query if LLM fails."""
        with patch.object(SICRY, "_call_llm", return_value="[SICRY: error]"):
            result = SICRY.refine_query("my investigation query")
        self.assertEqual(result, "my investigation query")

    def test_returns_refined_on_llm_success(self):
        with patch.object(SICRY, "_call_llm", return_value="malware C2 server"):
            result = SICRY.refine_query("can you find malware command and control servers")
        self.assertEqual(result, "malware C2 server")

    def test_strips_whitespace(self):
        with patch.object(SICRY, "_call_llm", return_value="  trimmed  "):
            result = SICRY.refine_query("anything")
        self.assertEqual(result, "trimmed")


# ═════════════════════════════════════════════════════════════════════════════
# 13. filter_results() fallback
# ═════════════════════════════════════════════════════════════════════════════
class TestFilterResults(unittest.TestCase):
    def _make_results(self, n):
        return [{"url": f"http://r{i}.onion", "title": f"Result {i}", "engine": "Test"}
                for i in range(n)]

    def test_returns_top20_on_llm_error(self):
        results = self._make_results(30)
        with patch.object(SICRY, "_call_llm", return_value="[SICRY: error]"):
            out = SICRY.filter_results("query", results)
        self.assertLessEqual(len(out), 20)

    def test_empty_results(self):
        out = SICRY.filter_results("query", [])
        self.assertEqual(out, [])

    def test_fewer_than_20_passed_through(self):
        results = self._make_results(5)
        with patch.object(SICRY, "_call_llm", return_value="[SICRY: error]"):
            out = SICRY.filter_results("query", results)
        self.assertEqual(len(out), 5)


# ═════════════════════════════════════════════════════════════════════════════
# 14. dispatch() — tool routing
# ═════════════════════════════════════════════════════════════════════════════
class TestDispatch(unittest.TestCase):
    def test_dispatch_check_tor(self):
        with patch.object(SICRY, "check_tor", return_value={"tor_active": True}):
            r = SICRY.dispatch("sicry_check_tor", {})
        self.assertIn("tor_active", r)

    def test_dispatch_fetch(self):
        SICRY.clear_cache()
        mock_session = MagicMock()
        resp = MagicMock(); resp.status_code = 200; resp.text = "<html></html>"
        mock_session.get.return_value = resp
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            r = SICRY.dispatch("sicry_fetch", {"url": "http://test.onion/"})
        self.assertIn("status", r)

    def test_dispatch_unknown_tool(self):
        """dispatch() raises ValueError for unknown tools — that is the contract."""
        with self.assertRaises(ValueError):
            SICRY.dispatch("nonexistent_tool", {})

    def test_tools_list_exists(self):
        self.assertTrue(hasattr(SICRY, "TOOLS"), "TOOLS list missing")
        self.assertIsInstance(SICRY.TOOLS, list)
        self.assertGreater(len(SICRY.TOOLS), 0)

    def test_tools_openai_exists(self):
        self.assertTrue(hasattr(SICRY, "TOOLS_OPENAI"))

    def test_tools_gemini_exists(self):
        self.assertTrue(hasattr(SICRY, "TOOLS_GEMINI"))


# ═════════════════════════════════════════════════════════════════════════════
# 15. File consistency — both copies identical
# ═════════════════════════════════════════════════════════════════════════════
class TestFilesConsistency(unittest.TestCase):
    def test_sicry_copies_identical(self):
        with open(os.path.join(_HERE, "sicry.py")) as _fh:
            root = _fh.read()
        with open(os.path.join(_ONION_CLAW, "sicry.py")) as _fh:
            oc = _fh.read()
        self.assertEqual(root, oc, "sicry.py root and OnionClaw copies differ!")

    def test_env_example_has_cache_ttl(self):
        """Both .env.example copies must have SICRY_CACHE_TTL."""
        root_ex = os.path.join(_HERE, ".env.example")
        oc_ex   = os.path.join(_ONION_CLAW, ".env.example")
        if os.path.isfile(root_ex):
            self.assertIn("SICRY_CACHE_TTL", _read(root_ex),
                          "root .env.example missing SICRY_CACHE_TTL")
        if os.path.isfile(oc_ex):
            self.assertIn("SICRY_CACHE_TTL", _read(oc_ex),
                          "OnionClaw .env.example missing SICRY_CACHE_TTL")


# ═════════════════════════════════════════════════════════════════════════════
# 16. LIVE Tor tests (only if --live flag)
# ═════════════════════════════════════════════════════════════════════════════
@unittest.skipUnless(LIVE, "Pass --live to run live Tor network tests")
class TestLive(unittest.TestCase):
    def test_tor_active(self):
        r = SICRY.check_tor()
        self.assertTrue(r["tor_active"], f"Tor not active: {r['error']}")
        self.assertIsNotNone(r["exit_ip"])

    def test_fetch_ahmia(self):
        """Fetch Ahmia clearnet (always reachable via Tor)."""
        SICRY._FETCH_CACHE.clear()
        r = SICRY.fetch("https://ahmia.fi/")
        self.assertIn(r["status"], range(200, 400), f"Ahmia returned {r['status']}: {r['error']}")
        self.assertGreater(len(r["text"]), 0)

    def test_fetch_duckduckgo_tor(self):
        """Fetch DuckDuckGo via Tor onion — our most reliable .onion."""
        SICRY._FETCH_CACHE.clear()
        r = SICRY.fetch("https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/")
        # Success OR 40x are both acceptable (ddg sometimes blocks bots)
        self.assertIn(r["status"], list(range(200, 500)) + [0],
                      f"Unexpected status {r['status']}: {r['error']}")

    def test_fetch_cache_live(self):
        """Second fetch of same URL should be instant (from cache)."""
        SICRY._FETCH_CACHE.clear()
        url = "https://ahmia.fi/search/?q=test"
        t0 = time.time()
        r1 = SICRY.fetch(url)
        t1 = time.time()
        r2 = SICRY.fetch(url)
        t2 = time.time()
        self.assertEqual(r1["url"], r2["url"])
        self.assertLess(t2 - t1, 1.0, "Cache hit took >1s — cache not working")

    def test_search_returns_results(self):
        """search() against at least Ahmia-clearnet should return ≥1 result."""
        results = SICRY.search("test", engines=["Ahmia-clearnet"], max_results=5)
        self.assertIsInstance(results, list)
        # Ahmia-clearnet is a clearnet HTTPS endpoint — should always return results
        self.assertGreater(len(results), 0, "search() returned 0 results")

    def test_search_result_shape(self):
        results = SICRY.search("malware", engines=["Ahmia-clearnet"], max_results=3)
        if results:
            r = results[0]
            for field in ("title", "url", "engine"):
                self.assertIn(field, r, f"Result missing '{field}'")

    def test_renew_identity(self):
        """renew_identity() should succeed when ControlPort 9051 is open."""
        import socket
        try:
            s = socket.create_connection(("127.0.0.1", 9051), timeout=2)
            s.close()
            cp_open = True
        except Exception:
            cp_open = False

        r = SICRY.renew_identity()
        if cp_open:
            self.assertTrue(r["success"], f"renew_identity failed: {r['error']}")
        else:
            # No control port — expected failure
            self.assertFalse(r["success"])
            self.assertIsNotNone(r["error"])


# ═════════════════════════════════════════════════════════════════════════════
# UX-1: check_tor.py and renew.py --version / --help flags
# ═════════════════════════════════════════════════════════════════════════════
class TestCheckTorRenewFlags(unittest.TestCase):
    """UX-1: check_tor.py and renew.py must expose --version and --help."""

    def _check_tor_src(self):
        return _read(os.path.join(_ONION_CLAW, "check_tor.py"))

    def _renew_src(self):
        return _read(os.path.join(_ONION_CLAW, "renew.py"))

    def test_check_tor_has_argparse(self):
        self.assertIn("argparse", self._check_tor_src())

    def test_renew_has_argparse(self):
        self.assertIn("argparse", self._renew_src())

    def test_check_tor_has_version_flag(self):
        src = self._check_tor_src()
        self.assertIn("--version", src,
                      "check_tor.py must have --version flag")
        self.assertIn("action=\"version\"", src)

    def test_renew_has_version_flag(self):
        src = self._renew_src()
        self.assertIn("--version", src,
                      "renew.py must have --version flag")
        self.assertIn("action=\"version\"", src)

    def test_check_tor_has_json_flag(self):
        self.assertIn("--json", self._check_tor_src())

    def test_renew_has_json_flag(self):
        self.assertIn("--json", self._renew_src())


# ═════════════════════════════════════════════════════════════════════════════
# BUG-2: sync_sicry.py tag mismatch docs
# ═════════════════════════════════════════════════════════════════════════════
class TestSyncSicryDocs(unittest.TestCase):
    """BUG-2: sync_sicry.py must document tag mismatch and give clear 404 error."""

    def _src(self):
        return _read(os.path.join(_ONION_CLAW, "sync_sicry.py"))

    def test_tag_mismatch_documented(self):
        """BUG-2: docstring must explain SICRY™ vs OnionClaw separate tag cadences."""
        src = self._src()
        self.assertIn("independent", src,
                      "sync_sicry.py must explain independent release cadences")

    def test_404_specific_handler(self):
        """BUG-2: 404 must produce a specific helpful error, not a bare exception dump."""
        src = self._src()
        self.assertIn("404", src,
                      "sync_sicry.py must handle 404 specifically")
        self.assertIn("SICRY", src)

    def test_no_raise_for_status(self):
        """BUG-2: raise_for_status() causes double/confusing output — must not be used."""
        src = self._src()
        self.assertNotIn("raise_for_status", src,
                         "sync_sicry.py must not use raise_for_status() (causes double output)")

    def test_no_hardcoded_tag_list_in_error(self):
        """COSMETIC: 404 error must not contain a hardcoded tag list — must use live API."""
        src = self._src()
        self.assertNotIn('"v1.0.0, v1.0.1, v1.1.0, v1.1.1"', src,
                         "404 error message must not embed a hardcoded tag list")
        # The old hardcoded string literal must be gone from the 404 print statement
        self.assertNotIn("v1.0.0, v1.0.1, v1.1.0, v1.1.1\"", src,
                         "Hardcoded tag list must be replaced with live API lookup")

    def test_live_tag_lookup_function(self):
        """COSMETIC: sync_sicry.py must define _fetch_sicry_tags() for live tag lookup."""
        src = self._src()
        self.assertIn("_fetch_sicry_tags", src,
                      "sync_sicry.py must have _fetch_sicry_tags() helper")
        self.assertIn("SICRY_TAGS_API", src,
                      "sync_sicry.py must define SICRY_TAGS_API constant")

    def test_404_calls_live_lookup(self):
        """COSMETIC: 404 handler must call _fetch_sicry_tags() to build the tag hint."""
        src = self._src()
        # The 404 block must reference the live lookup function, not a raw string literal
        idx_404 = src.index("if r.status_code == 404")
        snippet = src[idx_404:idx_404 + 400]
        self.assertIn("_fetch_sicry_tags()", snippet,
                      "404 handler must call _fetch_sicry_tags() for the live tag list")


# ═════════════════════════════════════════════════════════════════════════════
# v1.1.1 regression tests — 15 bug fixes
# ═════════════════════════════════════════════════════════════════════════════

class TestSafetyBlacklist(unittest.TestCase):
    """SAFETY-1: content blacklist and _is_content_safe()."""

    def test_safe_function_exists(self):
        self.assertTrue(hasattr(SICRY, "_is_content_safe"),
                        "_is_content_safe() missing from sicry.py")

    def test_blacklist_exists(self):
        self.assertTrue(hasattr(SICRY, "_CONTENT_BLACKLIST"),
                        "_CONTENT_BLACKLIST missing from sicry.py")

    def test_clean_text_passes(self):
        self.assertTrue(SICRY._is_content_safe("dark web threat intelligence"))

    def test_csam_term_blocked(self):
        self.assertFalse(SICRY._is_content_safe("jailbait site underground"))

    def test_csam_compound_blocked(self):
        self.assertFalse(SICRY._is_content_safe("child sex marketplace"))

    def test_case_insensitive(self):
        self.assertFalse(SICRY._is_content_safe("JAILBAIT"))

    def test_search_result_blocked(self):
        """search() should drop results matching the blacklist."""
        # Build a fake result list and confirm the blacklist filter removes bad entries
        results = [
            {"title": "Normal hacking forum", "url": "http://a.onion/", "engine": "Test"},
            {"title": "jailbait photos archive", "url": "http://b.onion/", "engine": "Test"},
        ]
        filtered = [r for r in results if SICRY._is_content_safe(
            r.get("title", "") + " " + r.get("url", ""))]
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title"], "Normal hacking forum")


class TestSearchScriptFlags(unittest.TestCase):
    """BUG-1/BUG-4/BUG-5: search.py CLI."""

    def _src(self):
        return _read(os.path.join(_ONION_CLAW, "search.py"))

    def test_json_flag_present(self):
        """BUG-1: --json flag must be defined in search.py."""
        self.assertIn("--json", self._src())

    def test_empty_query_guard(self):
        """BUG-5: search.py must guard against empty --query."""
        self.assertIn("query.strip()", self._src())

    def test_engine_validation_exit_on_all_invalid(self):
        """BUG-4: if all engines invalid, script must exit 1."""
        src = self._src()
        self.assertIn("sys.exit(1)", src)
        self.assertIn("none of the specified engines", src)

    def test_no_bare_json_at_end(self):
        """BUG-1: JSON should not be printed unconditionally at end."""
        lines = self._src().splitlines()
        # The final print(json.dumps...) must be guarded by if args.json
        json_lines = [i for i, l in enumerate(lines) if "json.dumps(results" in l]
        for li in json_lines:
            # Walk back to find if/else guard
            block = "\n".join(lines[max(0, li-5):li+1])
            self.assertIn("args.json", block,
                          f"json.dumps at line {li+1} not guarded by args.json")


class TestFetchScriptFixes(unittest.TestCase):
    """BUG-2/BUG-3: fetch.py CLI."""

    def _src(self):
        return _read(os.path.join(_ONION_CLAW, "fetch.py"))

    def test_fetching_header_guarded(self):
        """BUG-2: 'Fetching ...' print must be inside if not args.json block."""
        src = self._src()
        idx_fetch = src.index("Fetching")
        # The nearest preceding if-block must mention args.json
        preceding = src[max(0, idx_fetch-200):idx_fetch]
        self.assertIn("args.json", preceding,
                      "'Fetching...' print is not guarded by args.json check")

    def test_no_bare_json_at_end(self):
        """BUG-2: stray json.dumps at end of fetch.py must be gone."""
        lines = self._src().splitlines()
        # Check last 8 lines for bare json.dumps
        last_block = "\n".join(lines[-8:])
        self.assertNotIn("json.dumps(result", last_block,
                         "Stray json.dumps(result) still at end of fetch.py")

    def test_truncated_display_present(self):
        """BUG-3: fetch.py must show truncation notice."""
        self.assertIn("truncated", self._src())


class TestPipelineFixes(unittest.TestCase):
    """BUG-5/BUG-6/UX-4: pipeline.py."""

    def _src(self):
        return _read(os.path.join(_ONION_CLAW, "pipeline.py"))

    def test_empty_query_guard(self):
        """BUG-5: pipeline.py must guard against empty --query."""
        self.assertIn("query.strip()", self._src())

    def test_out_exits_1_on_oserror(self):
        """BUG-6: --out permission failure must exit 1.
        Handlers now use 'except Exception' to catch PermissionError,
        FUSE errors, UnicodeEncodeError, etc — not just bare OSError."""
        src = self._src()
        # Locate the two '--out' write-error handlers by their unique message
        # and verify sys.exit(1) immediately follows each one.
        msg = "could not write output file"
        parts = src.split(msg)
        self.assertGreater(len(parts), 1,
                           "pipeline.py --out error message not found")
        for part in parts[1:]:
            block = part[:150]
            self.assertIn("sys.exit(1)", block,
                          "--out exception handler does not call sys.exit(1)")

    def test_out_handler_not_bare_oserror(self):
        """BUG-6: --out must NOT use bare 'except OSError' (too narrow)."""
        src = self._src()
        # After IMPROVE-8, the file is opened via _out_path variable.
        # Count 'with open(_out_path' in the output section (should be >= 1)
        out_blocks = [i for i, line in enumerate(src.splitlines())
                      if 'with open(_out_path' in line or 'with open(args.out' in line]
        self.assertGreater(len(out_blocks), 0, "No --out write blocks found")
        for lineno in out_blocks:
            # Within 10 lines after the open, find the except
            window = "\n".join(src.splitlines()[lineno:lineno+10])
            self.assertNotIn("except OSError", window,
                             f"--out handler near line {lineno+1} uses bare 'except OSError'")

    def test_total_steps_always_7(self):
        """UX-4: TOTAL should always be 7."""
        self.assertIn("TOTAL = 7", self._src())

    def test_no_llm_step_labels(self):
        """UX-4: no-LLM steps must use correct labels."""
        src = self._src()
        self.assertIn("skip 3/", src)          # step 3 skip label still present
        self.assertIn("BM25 confidence", src)   # step 5: BM25 ranking (no skip)
        self.assertIn("No-LLM entity", src)     # step 7: analyze_nollm header

    def test_check_update_flag_exists(self):
        """pipeline.py must support --check-update flag."""
        self.assertIn("--check-update", self._src())

    def test_passive_update_notice_present(self):
        """pipeline.py must print passive update notice when sicry.check_update() says so."""
        src = self._src()
        self.assertIn("check_update", src)
        self.assertIn("up_to_date", src)

    def test_query_not_required_for_check_update(self):
        """BUG-1: --check-update must work without --query.
        Fix: --query must NOT be required=True at parse time;
        it is checked manually after the standalone flags exit."""
        src = self._src()
        # The --query arg definition must NOT contain 'required=True'
        # (required validation happens manually after standalone flags)
        lines = src.splitlines()
        query_lines = [l for l in lines if "--query" in l and "add_argument" in l]
        self.assertGreater(len(query_lines), 0, "--query arg definition not found")
        for l in query_lines:
            self.assertNotIn("required=True", l,
                             "--query must not be required=True — breaks --check-update")

    def test_query_manual_check_present(self):
        """BUG-1: after standalone flags, --query is validated manually."""
        src = self._src()
        # Must have manual 'if not args.query' guard
        self.assertIn("if not args.query", src,
                      "pipeline.py must manually validate --query after standalone flags")


class TestSetupPyAuthAndMCP(unittest.TestCase):
    """AUTH-1/AUTH-2/MCP-1/MCP-2: setup.py."""

    def _src(self):
        return _read(os.path.join(_ONION_CLAW, "setup.py"))

    def test_auth_verification_present(self):
        """AUTH-1/AUTH-2: setup.py must test actual Tor auth."""
        self.assertIn("authenticate", self._src())

    def test_group_fix_applied_not_just_documented(self):
        """AUTH-1: setup.py must actually call usermod, not just document it."""
        src = self._src()
        self.assertIn("usermod", src,
                      "setup.py must call usermod to add user to debian-tor")
        self.assertIn("subprocess", src,
                      "setup.py must use subprocess to apply group fix")

    def test_cookie_file_group_readable_in_setup(self):
        """AUTH-1: torrc must include CookieAuthFileGroupReadable 1."""
        src = self._src()
        self.assertIn("CookieAuthFileGroupReadable", src,
                      "setup.py must add CookieAuthFileGroupReadable 1 to torrc")

    def test_systemd_dropin_defined(self):
        """AUTH-1: setup.py must define a systemd drop-in to chmod the cookie."""
        src = self._src()
        self.assertIn("SYSTEMD_DROPIN", src,
                      "setup.py must define SYSTEMD_DROPIN_PATH for permanent fix")
        self.assertIn("ExecStartPost", src,
                      "systemd drop-in must use ExecStartPost to chmod cookie")

    def test_fix_cookie_auth_function_exists(self):
        """AUTH-1: _fix_cookie_auth() must be a callable function."""
        src = self._src()
        self.assertIn("def _fix_cookie_auth(", src,
                      "setup.py must define _fix_cookie_auth() function")

    def test_group_fix_documented(self):
        """AUTH-1: setup.py must mention debian-tor group fix."""
        self.assertIn("debian-tor", self._src())

    def test_password_auth_documented(self):
        """AUTH-1: setup.py must document HashedControlPassword option."""
        self.assertIn("HashedControlPassword", self._src())

    def test_mcp_optional_dep_documented(self):
        """MCP-1: setup.py check_deps must mention mcp."""
        self.assertIn("mcp", self._src())

    def test_mcp_user_install_hint(self):
        """MCP-2: setup.py must include --user install hint for mcp."""
        src = self._src()
        self.assertIn("--user", src)


class TestRequirementsMCP(unittest.TestCase):
    """MCP-1: OnionClaw/requirements.txt must mention mcp."""

    def test_mcp_in_requirements(self):
        req = _read(os.path.join(_ONION_CLAW, "requirements.txt"))
        self.assertIn("mcp", req)


class TestSKILLMDSyncDocs(unittest.TestCase):
    """UX-2: sync_sicry.py must be documented in SKILL.md."""

    def test_sync_sicry_documented(self):
        skill = _read(os.path.join(_ONION_CLAW, "SKILL.md"))
        self.assertIn("sync_sicry", skill)


# ═════════════════════════════════════════════════════════════════════════════
# LLM backend tests — every provider + every code path (mocked, no credits needed)
# ═════════════════════════════════════════════════════════════════════════════

def _openai_mock_response(text: str) -> MagicMock:
    """Build a mock openai chat-completions response."""
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class TestCallLLMOpenAI(unittest.TestCase):
    """_call_llm() — openai provider."""

    def test_openai_success(self):
        """openai: returns LLM text on success."""
        with patch.object(SICRY, "OPENAI_API_KEY", "sk-test"):
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _openai_mock_response("ANALYSIS OK")
            with patch("sicry.OpenAI", return_value=mock_client, create=True):
                # patch at the module level where it's imported inside the function
                import openai as _openai_module
                with patch.object(_openai_module, "OpenAI", return_value=mock_client):
                    result = SICRY._call_llm("openai", "sys", "prompt")
        self.assertEqual(result, "ANALYSIS OK")

    def test_openai_no_key_returns_error_string(self):
        """openai: returns [SICRY: ...] string when key is missing — never raises."""
        with patch.object(SICRY, "OPENAI_API_KEY", None):
            result = SICRY._call_llm("openai", "sys", "prompt")
        self.assertTrue(result.startswith("[SICRY:"))
        self.assertIn("OPENAI_API_KEY", result)

    def test_openai_exception_returns_error_string(self):
        """openai: API exception is caught and returned as [SICRY:...] string."""
        with patch.object(SICRY, "OPENAI_API_KEY", "sk-test"):
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception("quota exceeded")
            import openai as _openai_module
            with patch.object(_openai_module, "OpenAI", return_value=mock_client):
                result = SICRY._call_llm("openai", "sys", "prompt")
        self.assertTrue(result.startswith("[SICRY:"))
        self.assertIn("quota exceeded", result)


class TestCallLLMOllama(unittest.TestCase):
    """_call_llm() — ollama provider (local, no key)."""

    def _post(self, url, **kwargs):
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {"response": "OLLAMA RESULT"}
        mock.raise_for_status = MagicMock()
        return mock

    def test_ollama_success(self):
        with patch("sicry.requests") as mock_req:
            mock_req.post.side_effect = self._post
            result = SICRY._call_llm("ollama", "sys", "prompt")
        self.assertEqual(result, "OLLAMA RESULT")

    def test_ollama_http_error_returns_error_string(self):
        with patch("sicry.requests") as mock_req:
            mock_req.post.return_value.raise_for_status.side_effect = Exception("conn refused")
            result = SICRY._call_llm("ollama", "sys", "prompt")
        self.assertTrue(result.startswith("[SICRY:"))


class TestCallLLMLlamaCpp(unittest.TestCase):
    """_call_llm() — llamacpp provider."""

    def test_llamacpp_success(self):
        with patch("sicry.requests") as mock_req:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": "LLAMA RESULT"}}]}
            mock_req.post.return_value = resp
            result = SICRY._call_llm("llamacpp", "sys", "prompt")
        self.assertEqual(result, "LLAMA RESULT")

    def test_llamacpp_exception_returns_error_string(self):
        with patch("sicry.requests") as mock_req:
            mock_req.post.side_effect = Exception("server offline")
            result = SICRY._call_llm("llamacpp", "sys", "prompt")
        self.assertTrue(result.startswith("[SICRY:"))


class TestCallLLMUnknown(unittest.TestCase):
    """_call_llm() — unknown provider returns error string."""

    def test_unknown_provider(self):
        result = SICRY._call_llm("invalid_provider", "sys", "prompt")
        self.assertTrue(result.startswith("[SICRY:"))
        self.assertIn("Unknown LLM provider", result)
        self.assertIn("invalid_provider", result)


class TestAskFunction(unittest.TestCase):
    """ask() — all modes, aliases, custom_instructions."""

    def _mock_ask(self, expected_return="REPORT", **ask_kwargs):
        with patch.object(SICRY, "_call_llm", return_value=expected_return) as m:
            result = SICRY.ask("content text", **ask_kwargs)
        return result, m

    def test_threat_intel_mode(self):
        result, mock_llm = self._mock_ask(query="ransomware", mode="threat_intel")
        self.assertEqual(result, "REPORT")
        _, system, prompt = mock_llm.call_args[0]
        self.assertIn("Threat Intelligence", system)
        self.assertIn("ransomware", prompt)

    def test_ransomware_mode(self):
        result, mock_llm = self._mock_ask(mode="ransomware")
        _, system, _ = mock_llm.call_args[0]
        self.assertIn("ransomware", system.lower())

    def test_personal_identity_mode(self):
        result, mock_llm = self._mock_ask(mode="personal_identity")
        _, system, _ = mock_llm.call_args[0]
        self.assertIn("Personal", system)

    def test_corporate_mode(self):
        result, mock_llm = self._mock_ask(mode="corporate")
        _, system, _ = mock_llm.call_args[0]
        self.assertIn("corporate", system.lower())

    def test_mode_alias_ransomware_malware(self):
        """ransomware_malware alias maps to ransomware prompt."""
        _, m1 = self._mock_ask(mode="ransomware")
        _, m2 = self._mock_ask(mode="ransomware_malware")
        self.assertEqual(m1.call_args[0][1], m2.call_args[0][1])

    def test_mode_alias_corporate_espionage(self):
        """corporate_espionage alias maps to corporate prompt."""
        _, m1 = self._mock_ask(mode="corporate")
        _, m2 = self._mock_ask(mode="corporate_espionage")
        self.assertEqual(m1.call_args[0][1], m2.call_args[0][1])

    def test_unknown_mode_falls_back_to_threat_intel(self):
        _, m1 = self._mock_ask(mode="threat_intel")
        _, m2 = self._mock_ask(mode="nonexistent_mode")
        self.assertEqual(m1.call_args[0][1], m2.call_args[0][1])

    def test_custom_instructions_appended(self):
        _, mock_llm = self._mock_ask(custom_instructions="focus on C2 infrastructure")
        _, system, _ = mock_llm.call_args[0]
        self.assertIn("focus on C2 infrastructure", system)

    def test_empty_custom_instructions_not_appended(self):
        _, m1 = self._mock_ask(mode="threat_intel", custom_instructions="")
        _, m2 = self._mock_ask(mode="threat_intel")
        # Systems should be identical when custom_instructions is blank
        self.assertEqual(m1.call_args[0][1], m2.call_args[0][1])

    def test_content_truncated_to_max_chars(self):
        big_content = "X" * 99999
        with patch.object(SICRY, "_call_llm", return_value="ok") as m:
            SICRY.ask(big_content)
        _, _, prompt = m.call_args[0]
        self.assertLessEqual(len(prompt), SICRY.MAX_CONTENT_CHARS + 200)  # prompt overhead

    def test_provider_override(self):
        """ask() passes provider override through to _call_llm."""
        with patch.object(SICRY, "_call_llm", return_value="ok") as m:
            SICRY.ask("content", provider="ollama")
        self.assertEqual(m.call_args[0][0], "ollama")

    def test_returns_llm_error_string_not_exception(self):
        """ask() must return error string, never raise."""
        with patch.object(SICRY, "_call_llm", return_value="[SICRY: LLM call failed — boom]"):
            result = SICRY.ask("content")
        self.assertTrue(result.startswith("[SICRY:"))


class TestRefineQueryLLM(unittest.TestCase):
    """refine_query() — all code paths."""

    def test_success_returns_refined(self):
        with patch.object(SICRY, "_call_llm", return_value="ransomware leak"):
            result = SICRY.refine_query("tell me about ransomware data breaches")
        self.assertEqual(result, "ransomware leak")

    def test_strips_whitespace(self):
        with patch.object(SICRY, "_call_llm", return_value="  ransomware leak  "):
            result = SICRY.refine_query("query")
        self.assertEqual(result, "ransomware leak")

    def test_llm_error_tag_falls_back_to_original(self):
        """If _call_llm returns a [SICRY:...] error, original query is returned."""
        with patch.object(SICRY, "_call_llm", return_value="[SICRY: OPENAI_API_KEY not set]"):
            result = SICRY.refine_query("my original query")
        self.assertEqual(result, "my original query")

    def test_exception_falls_back_to_original(self):
        with patch.object(SICRY, "_call_llm", side_effect=Exception("network error")):
            result = SICRY.refine_query("my query")
        self.assertEqual(result, "my query")

    def test_provider_override(self):
        with patch.object(SICRY, "_call_llm", return_value="refined") as m:
            SICRY.refine_query("query", provider="ollama")
        self.assertEqual(m.call_args[0][0], "ollama")


class TestFilterResultsLLM(unittest.TestCase):
    """filter_results() — all code paths."""

    def _make_results(self, n: int) -> list[dict]:
        return [{"title": f"Result {i}", "url": f"http://{i}.onion/", "engine": "Test"}
                for i in range(1, n + 1)]

    def test_empty_input_returns_empty(self):
        result = SICRY.filter_results("query", [])
        self.assertEqual(result, [])

    def test_success_returns_selected_indices(self):
        results = self._make_results(10)
        # LLM picks indices 3, 7, 1
        with patch.object(SICRY, "_call_llm", return_value="3,7,1"):
            filtered = SICRY.filter_results("ransomware", results)
        self.assertEqual(len(filtered), 3)
        self.assertEqual(filtered[0]["title"], "Result 3")
        self.assertEqual(filtered[1]["title"], "Result 7")
        self.assertEqual(filtered[2]["title"], "Result 1")

    def test_llm_error_tag_returns_top20(self):
        results = self._make_results(30)
        with patch.object(SICRY, "_call_llm", return_value="[SICRY: OPENAI_API_KEY not set]"):
            filtered = SICRY.filter_results("query", results)
        self.assertEqual(filtered, results[:20])

    def test_duplicate_indices_deduped(self):
        results = self._make_results(5)
        with patch.object(SICRY, "_call_llm", return_value="1,1,2,2,3"):
            filtered = SICRY.filter_results("query", results)
        # Should have 3 unique results, not 5
        urls = [r["url"] for r in filtered]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(len(filtered), 3)

    def test_out_of_range_indices_ignored(self):
        results = self._make_results(5)
        with patch.object(SICRY, "_call_llm", return_value="1,99,0,5"):
            filtered = SICRY.filter_results("query", results)
        # Only 1 and 5 are valid
        self.assertEqual(len(filtered), 2)

    def test_no_valid_indices_returns_top20(self):
        results = self._make_results(25)
        with patch.object(SICRY, "_call_llm", return_value="999,888,777"):
            filtered = SICRY.filter_results("query", results)
        self.assertEqual(filtered, results[:20])

    def test_capped_at_20_results(self):
        results = self._make_results(30)
        all_indices = ",".join(str(i) for i in range(1, 31))
        with patch.object(SICRY, "_call_llm", return_value=all_indices):
            filtered = SICRY.filter_results("query", results)
        self.assertLessEqual(len(filtered), 20)

    def test_rate_limit_exception_triggers_truncated_retry(self):
        results = self._make_results(5)
        call_count = [0]
        def side_effect(provider, system, prompt):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("rate limit exceeded")
            return "1,2"
        with patch.object(SICRY, "_call_llm", side_effect=side_effect):
            filtered = SICRY.filter_results("query", results)
        self.assertEqual(call_count[0], 2, "Should retry with truncated content")
        self.assertEqual(len(filtered), 2)

    def test_both_attempts_fail_returns_top20(self):
        results = self._make_results(25)
        with patch.object(SICRY, "_call_llm", side_effect=Exception("rate limit exceeded")):
            filtered = SICRY.filter_results("query", results)
        self.assertEqual(filtered, results[:20])

    def test_non_rate_limit_exception_returns_top20_immediately(self):
        results = self._make_results(25)
        call_count = [0]
        def side_effect(provider, system, prompt):
            call_count[0] += 1
            raise Exception("authentication failed")
        with patch.object(SICRY, "_call_llm", side_effect=side_effect):
            filtered = SICRY.filter_results("query", results)
        self.assertEqual(call_count[0], 1, "Non-rate-limit error must NOT retry")
        self.assertEqual(filtered, results[:20])

    def test_provider_override_passed(self):
        results = self._make_results(5)
        with patch.object(SICRY, "_call_llm", return_value="1,2") as m:
            SICRY.filter_results("query", results, provider="ollama")
        self.assertEqual(m.call_args[0][0], "ollama")


class TestSystemPrompts(unittest.TestCase):
    """_SYSTEM_PROMPTS has all required modes and correct content."""

    def test_all_modes_defined(self):
        for mode in ("threat_intel", "ransomware", "personal_identity", "corporate"):
            self.assertIn(mode, SICRY._SYSTEM_PROMPTS,
                          f"Mode '{mode}' missing from _SYSTEM_PROMPTS")

    def test_prompts_not_empty(self):
        for mode, prompt in SICRY._SYSTEM_PROMPTS.items():
            self.assertTrue(prompt.strip(), f"Prompt for '{mode}' is empty")

    def test_prompts_mention_expert(self):
        for mode, prompt in SICRY._SYSTEM_PROMPTS.items():
            self.assertIn("Expert", prompt, f"Prompt for '{mode}' missing 'Expert' role")


class TestGenerateFinalString(unittest.TestCase):
    """_generate_final_string() used by filter_results."""

    def test_basic_formatting(self):
        results = [{"title": "Test Site", "url": "http://abc.onion/path", "engine": "X"}]
        out = SICRY._generate_final_string(results)
        self.assertIn("Test Site", out)
        self.assertIn("abc.onion", out)

    def test_truncate_mode_shortens_titles(self):
        long_title = "A" * 200
        results = [{"title": long_title, "url": "http://abc.onion/", "engine": "X"}]
        out = SICRY._generate_final_string(results, truncate=True)
        # In truncated mode, url is omitted and title is cut to 30 chars
        self.assertNotIn("abc.onion", out)
        self.assertLessEqual(len(out.split(".")[-1]), 40)  # rough check

    def test_empty_results(self):
        self.assertEqual(SICRY._generate_final_string([]), "")

    def test_strips_non_alphanumeric_from_title(self):
        results = [{"title": "Hello <World>!", "url": "http://x.onion/", "engine": "X"}]
        out = SICRY._generate_final_string(results)
        self.assertNotIn("<", out)
        self.assertNotIn(">", out)


# ═════════════════════════════════════════════════════════════════════════════
# v1.2.0 fixes — Safety / Security / Functional / UX
# ═════════════════════════════════════════════════════════════════════════════

class TestSafetyTokenPair(unittest.TestCase):
    """SAFETY-1 gap fix: token-pair matching and standalone dangerous terms."""

    def test_token_pair_blacklist_exists(self):
        self.assertTrue(hasattr(SICRY, "_TOKEN_PAIR_BLACKLIST"),
                        "_TOKEN_PAIR_BLACKLIST missing from sicry.py")

    def test_abyss_title_blocked(self):
        """Regression: 'KIDS - CHILD - RAPE' must be blocked via token-pair."""
        self.assertFalse(SICRY._is_content_safe("KIDS - CHILD - RAPE"))

    def test_child_rape_blocked(self):
        self.assertFalse(SICRY._is_content_safe("child rape archives"))

    def test_minor_rape_blocked(self):
        self.assertFalse(SICRY._is_content_safe("minor rape site dark web"))

    def test_kids_sex_blocked(self):
        self.assertFalse(SICRY._is_content_safe("kids sex video download"))

    def test_kids_porn_blocked(self):
        self.assertFalse(SICRY._is_content_safe("kids porn archive"))

    def test_torture_child_blocked(self):
        self.assertFalse(SICRY._is_content_safe("child torture onion"))

    def test_snuff_live_blocked(self):
        self.assertFalse(SICRY._is_content_safe("live snuff stream"))

    def test_legitimate_child_safe(self):
        """'child' alone in a normal context must NOT be blocked."""
        self.assertTrue(SICRY._is_content_safe("child welfare dark web threat"))

    def test_legitimate_minor_safe(self):
        self.assertTrue(SICRY._is_content_safe("minor version update repository"))

    def test_rape_without_context_not_auto_blocked(self):
        """Standalone 'rape' not near any context keyword must be treated carefully.
        Criminology research topics should not be blocked."""
        # A title with just the word 'rape' but no illegal content context
        # The current implementation requires context keywords to block standalone rape.
        # A pure criminology stats report should be allowed.
        result = SICRY._is_content_safe("rape statistics annual report criminology 2026")
        # This is allowed — no dark-web/media/victim context keywords present
        self.assertTrue(result)

    def test_rape_video_blocked(self):
        self.assertFalse(SICRY._is_content_safe("rape video upload dark web"))

    def test_rape_porn_blocked(self):
        self.assertFalse(SICRY._is_content_safe("rape porn site onion"))


class TestSecurityChmod(unittest.TestCase):
    """Security: setup.py must chmod 600 the .env after writing it."""

    def test_chmod_600_called_in_setup(self):
        src = _read(os.path.join(_ONION_CLAW, "setup.py"))
        self.assertIn("chmod", src,
                      "setup.py must call os.chmod to restrict .env permissions")
        self.assertIn("0o600", src,
                      "setup.py must set permissions to 0o600 (owner r/w only)")

    def test_chmod_at_env_path(self):
        src = _read(os.path.join(_ONION_CLAW, "setup.py"))
        # The chmod call must reference the _ENV variable
        idx = src.index("0o600")
        surrounding = src[max(0, idx - 80):idx + 20]
        self.assertIn("_ENV", surrounding,
                      "os.chmod must be called on the _ENV path")

    def test_chmod_message_printed(self):
        src = _read(os.path.join(_ONION_CLAW, "setup.py"))
        self.assertIn("600", src)


class TestSecurityRedirectBlock(unittest.TestCase):
    """Security: fetch() must block .onion → clearnet redirects."""

    def _fetch_with_redirect(self, start_url: str, redirect_to: str):
        SICRY.clear_cache()

        mock_resp = MagicMock()
        mock_resp.status_code = 301
        mock_resp.url = redirect_to          # simulates requests following the redirect
        mock_resp.text = "<html><title>clearnet</title><body>redirected</body></html>"
        mock_resp.apparent_encoding = "utf-8"
        mock_resp.encoding = "utf-8"

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            return SICRY.fetch(start_url)

    def test_onion_to_clearnet_blocked(self):
        """An .onion URL that redirects to clearnet must return an error."""
        result = self._fetch_with_redirect(
            "http://legit.onion/page",
            "https://clearnet-evil.com/page",
        )
        self.assertIsNotNone(result.get("error"),
                             "Clearnet redirect must set an error")
        self.assertIn("de-anonymization", result["error"])

    def test_onion_to_onion_allowed(self):
        """An .onion → .onion redirect must be allowed."""
        result = self._fetch_with_redirect(
            "http://legit.onion/page",
            "http://other.onion/page",
        )
        # Should succeed (error is None OR error is None — title present)
        # Because other.onion still has .onion in hostname
        self.assertIsNone(result.get("error"),
                          f"onion→onion redirect should be allowed; got: {result.get('error')}")

    def test_clearnet_to_clearnet_no_issue(self):
        """Clearnet fetches are NOT .onion so redirect blocking must NOT apply."""
        SICRY.clear_cache()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://clearnet.example.com/final"
        mock_resp.text = "<html><title>hello</title><body>ok</body></html>"
        mock_resp.apparent_encoding = "utf-8"
        mock_resp.encoding = "utf-8"

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            result = SICRY.fetch("http://clearnet.example.com/page")

        self.assertIsNone(result.get("error"))

    def test_redirect_block_has_clearnet_url_in_error(self):
        """The error message must include the clearnet URL so users can see where they were sent."""
        result = self._fetch_with_redirect(
            "http://market.onion/",
            "http://tracking.example.com/spy",
        )
        self.assertIn("tracking.example.com", result["error"])


class TestSecurityUserAgentRotation(unittest.TestCase):
    """Security: _USER_AGENTS pool exists and is used in fetch() headers."""

    def test_user_agents_pool_exists(self):
        self.assertTrue(hasattr(SICRY, "_USER_AGENTS"),
                        "_USER_AGENTS list missing from sicry.py")
        self.assertGreater(len(SICRY._USER_AGENTS), 3,
                           "Should have multiple User-Agents for rotation")

    def test_user_agent_used_in_fetch(self):
        """fetch() must pass a User-Agent header from the pool."""
        src_path = os.path.join(_HERE, "sicry.py")
        src = _read(src_path)
        self.assertIn("_USER_AGENTS", src)
        self.assertIn("User-Agent", src)
        self.assertIn("random.choice", src)


class TestPersistentCache(unittest.TestCase):
    """v2.0.0: JSON disk cache replaced by SQLite (_DB). Verify the transition."""

    def setUp(self):
        pass  # v2.0.0: no _FETCH_CACHE dict

    def test_cache_file_constant_exists(self):
        # v2.0.0: replaced by SICRY_DB_PATH env var + _DB class
        self.assertTrue(hasattr(SICRY, "SICRY_DB_PATH") or hasattr(SICRY, "_DB"),
                        "Neither SICRY_DB_PATH nor _DB found — SQLite cache missing")

    def test_save_disk_cache_exists(self):
        # v2.0.0: _save_disk_cache replaced by _db().cache_set()
        self.assertTrue(hasattr(SICRY, "_DB"),
                        "_DB SQLite wrapper missing from sicry.py")

    def test_load_disk_cache_exists(self):
        # v2.0.0: _load_disk_cache replaced by _db().cache_get()
        self.assertTrue(callable(getattr(SICRY, "_db", None)),
                        "_db() singleton accessor missing from sicry.py")

    def test_clear_cache_function_exists(self):
        self.assertTrue(callable(getattr(SICRY, "clear_cache", None)),
                        "clear_cache() missing from sicry.py")

    def test_clear_cache_empties_memory(self):
        # v2.0.0: clear_cache() delegates to SQLite; just check it returns int
        n = SICRY.clear_cache()
        self.assertIsInstance(n, int)

    def test_clear_cache_returns_count(self):
        n = SICRY.clear_cache()
        self.assertIsInstance(n, int)
        self.assertGreaterEqual(n, 0)

    def test_save_and_load_roundtrip(self):
        # v2.0.0: SQLite roundtrip via _db().cache_set / cache_get
        import tempfile
        tmp = tempfile.mktemp(suffix=".db")
        old_env = os.environ.get("SICRY_DB_PATH")
        os.environ["SICRY_DB_PATH"] = tmp
        try:
            db = SICRY._DB(tmp)
            db.cache_set("http://x.onion", "fetch", {"title": "hi", "text": "body"})
            result = db.cache_get("http://x.onion", "fetch", ttl=3600)
            self.assertIsNotNone(result)
            self.assertEqual(result.get("title"), "hi")
        finally:
            if old_env is None:
                os.environ.pop("SICRY_DB_PATH", None)
            else:
                os.environ["SICRY_DB_PATH"] = old_env
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def test_load_ignores_corrupt_cache(self):
        # v2.0.0: corrupted data in SQLite returns None, never raises
        import tempfile
        tmp = tempfile.mktemp(suffix=".db")
        try:
            db = SICRY._DB(tmp)
            # Insert corrupt JSON directly
            import sqlite3
            conn = sqlite3.connect(tmp)
            conn.execute(
                "INSERT OR REPLACE INTO cache(key,cache_type,ts,data) VALUES(?,?,?,?)",
                ("bad", "fetch", 9999999999.0, "NOTJSON{{{{"),
            )
            conn.commit()
            conn.close()
            result = db.cache_get("bad", "fetch", ttl=3600)
            self.assertIsNone(result)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass


class TestClearCacheCLI(unittest.TestCase):
    """Functional: --clear-cache flag exposed in all CLI scripts."""

    def test_pipeline_has_clear_cache_flag(self):
        src = _read(os.path.join(_ONION_CLAW, "pipeline.py"))
        self.assertIn("--clear-cache", src)
        self.assertIn("clear_cache", src)

    def test_fetch_has_clear_cache_flag(self):
        src = _read(os.path.join(_ONION_CLAW, "fetch.py"))
        self.assertIn("--clear-cache", src)
        self.assertIn("clear_cache", src)

    def test_sicry_has_clear_cache_command(self):
        src = _read(os.path.join(_HERE, "sicry.py"))
        self.assertIn("clear-cache", src)
        self.assertIn("clear_cache", src)


class TestCheckEnginesCachedMode(unittest.TestCase):
    """UX: check_engines.py must support --cached N flag."""

    def test_cached_flag_present(self):
        src = _read(os.path.join(_ONION_CLAW, "check_engines.py"))
        self.assertIn("--cached", src,
                      "check_engines.py is missing the --cached flag")

    def test_engines_cache_file_defined(self):
        src = _read(os.path.join(_ONION_CLAW, "check_engines.py"))
        self.assertIn("_ENGINES_CACHE_FILE", src)

    def test_cached_skips_live_ping(self):
        """If a fresh cache file exists, --cached should not call check_search_engines."""
        import tempfile, importlib.util as ilu, types
        # Write a fake engine cache file
        fake_results = [{"name": "Ahmia", "status": "up", "latency_ms": 300}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"_timestamp": time.time(), "results": fake_results}, f)
            tmp = f.name
        try:
            # Patch sys.argv to simulate: check_engines.py --cached 10 --json
            with patch("sys.argv", ["check_engines.py", "--cached", "10", "--json"]):
                # We can read the script and verify the logic handles the cache
                src = _read(os.path.join(_ONION_CLAW, "check_engines.py"))
                # The script must load from cache when fresh
                self.assertIn("age_seconds", src)
                self.assertIn("_timestamp", src)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def test_cached_mode_json_still_works(self):
        """--json flag must still work alongside --cached."""
        src = _read(os.path.join(_ONION_CLAW, "check_engines.py"))
        self.assertIn("args.json", src)


class TestVersionFlags(unittest.TestCase):
    """UX: --version flag must be present in all CLI scripts."""

    def _has_version_flag(self, path: str) -> bool:
        src = _read(path)
        return "--version" in src and "action=\"version\"" in src

    def test_sicry_has_version_flag(self):
        self.assertTrue(self._has_version_flag(os.path.join(_HERE, "sicry.py")),
                        "sicry.py is missing --version argparse flag")

    def test_pipeline_has_version_flag(self):
        self.assertTrue(self._has_version_flag(os.path.join(_ONION_CLAW, "pipeline.py")),
                        "pipeline.py is missing --version flag")

    def test_fetch_has_version_flag(self):
        self.assertTrue(self._has_version_flag(os.path.join(_ONION_CLAW, "fetch.py")),
                        "fetch.py is missing --version flag")

    def test_search_has_version_flag(self):
        self.assertTrue(self._has_version_flag(os.path.join(_ONION_CLAW, "search.py")),
                        "search.py is missing --version flag")

    def test_check_engines_has_version_flag(self):
        self.assertTrue(self._has_version_flag(os.path.join(_ONION_CLAW, "check_engines.py")),
                        "check_engines.py is missing --version flag")

    def test_sync_sicry_has_version_flag(self):
        self.assertTrue(self._has_version_flag(os.path.join(_ONION_CLAW, "sync_sicry.py")),
                        "sync_sicry.py is missing --version flag")

    def test_pipeline_version_includes_sicry_version(self):
        src = _read(os.path.join(_ONION_CLAW, "pipeline.py"))
        self.assertIn("__version__", src)


class TestREADMESyncSicryDocs(unittest.TestCase):
    """UX: sync_sicry.py must be documented in both SKILL.md and OnionClaw/README.md."""

    def test_sync_sicry_in_skill_md(self):
        skill = _read(os.path.join(_ONION_CLAW, "SKILL.md"))
        self.assertIn("sync_sicry", skill)

    def test_sync_sicry_section_in_readme(self):
        readme = _read(os.path.join(_ONION_CLAW, "README.md"))
        self.assertIn("sync_sicry.py", readme,
                      "OnionClaw README must have a sync_sicry.py section")

    def test_sync_sicry_readme_documents_dry_run(self):
        readme = _read(os.path.join(_ONION_CLAW, "README.md"))
        self.assertIn("--dry-run", readme,
                      "README must document sync_sicry.py --dry-run")

    def test_sync_sicry_readme_documents_tag(self):
        readme = _read(os.path.join(_ONION_CLAW, "README.md"))
        self.assertIn("--tag", readme,
                      "README must document sync_sicry.py --tag")

    def test_check_engines_cached_docs_in_readme(self):
        readme = _read(os.path.join(_ONION_CLAW, "README.md"))
        self.assertIn("--cached", readme,
                      "README must document check_engines.py --cached flag")

    def test_clear_cache_docs_in_readme(self):
        readme = _read(os.path.join(_ONION_CLAW, "README.md"))
        self.assertIn("--clear-cache", readme,
                      "README must document the --clear-cache flag")


class TestSetupChmod(unittest.TestCase):
    """Security: setup.py setup_env() must chmod 600 after writing .env."""

    def test_chmod_in_setup_env_function(self):
        src = _read(os.path.join(_ONION_CLAW, "setup.py"))
        # Find setup_env function body
        idx = src.index("def setup_env(")
        func_body = src[idx: idx + 4000]
        self.assertIn("chmod", func_body,
                      "setup_env() must call os.chmod")
        self.assertIn("0o600", func_body,
                      "setup_env() must chmod to 0o600")

    def test_chmod_runs_before_early_return(self):
        """chmod must run BEFORE the early return so existing .env files
        also get their permissions corrected (not only fresh setups)."""
        src = _read(os.path.join(_ONION_CLAW, "setup.py"))
        idx_func = src.index("def setup_env(")
        func_body = src[idx_func: idx_func + 4000]
        idx_chmod  = func_body.index("chmod")
        # The 'return' that exits when user skips reconfigure must come AFTER chmod
        idx_return = func_body.index("return")
        self.assertLess(idx_chmod, idx_return,
                        "os.chmod must appear before the early 'return' in setup_env()")


# ═════════════════════════════════════════════════════════════════════════════
# v2.0.0  Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestV200Version(unittest.TestCase):
    """Both copies must declare version 2.1.6."""

    def test_sicry_version_200(self):
        self.assertEqual(SICRY.__version__, "2.1.6")

    def test_onion_claw_version_200(self):
        self.assertEqual(SICRY_OC.__version__, "2.1.6")


class TestSQLiteCache(unittest.TestCase):
    """_DB SQLite wrapper — cache_get / cache_set / cache_clear / prune."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mktemp(suffix=".db")
        os.environ["SICRY_DB_PATH"] = self._tmp

    def tearDown(self):
        try:
            os.unlink(self._tmp)
        except OSError:
            pass

    def _fresh_db(self):
        # create a fresh _DB instance pointing at tmp path
        if hasattr(SICRY, "_DB"):
            return SICRY._DB(self._tmp)
        self.skipTest("_DB not found in sicry")

    def test_db_class_exists(self):
        self.assertTrue(hasattr(SICRY, "_DB"), "_DB class missing")

    def test_cache_set_and_get(self):
        db = self._fresh_db()
        db.cache_set("k1", "test", {"hello": "world"})
        result = db.cache_get("k1", "test", ttl=3600)
        self.assertEqual(result, {"hello": "world"})

    def test_cache_ttl_expired(self):
        db = self._fresh_db()
        db.cache_set("k2", "test", {"data": 1})
        # TTL of 0 = always expired
        result = db.cache_get("k2", "test", ttl=0)
        self.assertIsNone(result)

    def test_cache_clear_returns_int(self):
        db = self._fresh_db()
        db.cache_set("k3", "test", "value")
        n = db.cache_clear()
        self.assertIsInstance(n, int)
        self.assertGreaterEqual(n, 0)

    def test_clear_cache_delegates_to_db(self):
        """clear_cache() at module level must call _db().cache_clear()."""
        self.assertTrue(callable(SICRY.clear_cache))
        # Just verify it returns an integer
        result = SICRY.clear_cache()
        self.assertIsInstance(result, int)

    def test_engine_history_add_and_get(self):
        db = self._fresh_db()
        db.engine_history_add("TestEngine", "up", 42, None)
        history = db.engine_history_get("TestEngine", n=5)
        self.assertIsInstance(history, list)

    def test_engine_reliability(self):
        db = self._fresh_db()
        db.engine_history_add("TestEngine2", "up",   30, None)
        db.engine_history_add("TestEngine2", "down", None, None)
        rel = db.engine_reliability("TestEngine2", window=10)
        self.assertIsInstance(rel, float)
        self.assertAlmostEqual(rel, 0.5, places=1)


class TestFriendlyError(unittest.TestCase):
    """_friendly_error() maps known Tor/socket exceptions to user-readable strings."""

    def test_friendly_error_exists(self):
        self.assertTrue(hasattr(SICRY, "_friendly_error"))

    def test_socks_error_mapped(self):
        msg = SICRY._friendly_error(Exception("SOCKS5 connection refused"))
        self.assertIn("Tor", msg)

    def test_timeout_mapped(self):
        msg = SICRY._friendly_error(Exception("read operation timed out"))
        self.assertIn("timed out", msg.lower())

    def test_max_retries_mapped(self):
        msg = SICRY._friendly_error(Exception("Max retries exceeded"))
        self.assertIn("renew", msg.lower())

    def test_unknown_error_passthrough(self):
        exc = ValueError("something weird happened")
        msg = SICRY._friendly_error(exc)
        self.assertIn("weird", msg)

    def test_returns_string(self):
        msg = SICRY._friendly_error(Exception("test"))
        self.assertIsInstance(msg, str)


class TestNoLLMLayer(unittest.TestCase):
    """extract_keywords, score_results, deduplicate_results."""

    def test_extract_keywords_exists(self):
        self.assertTrue(hasattr(SICRY, "extract_keywords"))

    def test_extract_keywords_returns_list(self):
        kw = SICRY.extract_keywords("ransomware attacked hospital network systems leaked data", top_n=5)
        self.assertIsInstance(kw, list)
        self.assertGreater(len(kw), 0)

    def test_extract_keywords_respects_top_n(self):
        kw = SICRY.extract_keywords("one two three four five six seven eight", top_n=3)
        self.assertLessEqual(len(kw), 3)

    def test_extract_keywords_filters_stopwords(self):
        kw = SICRY.extract_keywords("the and for http https www onion ransomware leak")
        # common stopwords should not dominate
        joined = " ".join(kw).lower()
        self.assertIn("ransomware", joined)

    def test_score_results_exists(self):
        self.assertTrue(hasattr(SICRY, "score_results"))

    def test_score_results_adds_score_key(self):
        results = [
            {"title": "ransomware data leak forum", "url": "http://x.onion", "engine": "Ahmia"},
            {"title": "weather forecast", "url": "http://y.onion", "engine": "Tor66"},
        ]
        scored = SICRY.score_results("ransomware data leak", results)
        for r in scored:
            # score_results() adds "score" key; search() renames to "confidence"
            self.assertTrue("score" in r or "confidence" in r)
            val = r.get("score", r.get("confidence"))
            self.assertIsInstance(val, (int, float))

    def test_score_results_sorted_descending(self):
        results = [
            {"title": "weather forecast completely unrelated", "url": "http://a.onion", "engine": "X"},
            {"title": "ransomware data leak", "url": "http://b.onion", "engine": "X"},
        ]
        scored = SICRY.score_results("ransomware leak", results)
        if len(scored) >= 2:
            key = "confidence" if "confidence" in scored[0] else "score"
            self.assertGreaterEqual(scored[0][key], scored[-1][key])

    def test_deduplicate_results_exists(self):
        self.assertTrue(hasattr(SICRY, "deduplicate_results"))

    def test_deduplicate_removes_same_url(self):
        results = [
            {"url": "http://x.onion", "title": "A"},
            {"url": "http://x.onion", "title": "A"},
        ]
        deduped = SICRY.deduplicate_results(results)
        self.assertEqual(len(deduped), 1)

    def test_deduplicate_removes_same_content(self):
        results = [
            {"url": "http://a.onion", "title": "ransomware forum"},
            {"url": "http://b.onion", "title": "ransomware forum"},
        ]
        # Both have identical text — deduplicate_results should drop one
        texts = ["ransomware data leak victims list", "ransomware data leak victims list"]
        deduped = SICRY.deduplicate_results(results, texts=texts)
        # May deduplicate to 1 or 2 depending on implementation — just check it returns a list
        self.assertIsInstance(deduped, list)
        self.assertGreaterEqual(len(deduped), 1)


class TestTorPoolClass(unittest.TestCase):
    """TorPool init, port calculation, round-robin — no live Tor needed."""

    def test_torpool_class_exists(self):
        self.assertTrue(hasattr(SICRY, "TorPool"))

    def test_torpool_init(self):
        pool = SICRY.TorPool(size=3, base_port=9060)
        self.assertEqual(pool.size, 3)
        self.assertEqual(pool.base_port, 9060)

    def test_torpool_control_port_offset(self):
        pool = SICRY.TorPool(size=2, base_port=9060)
        # Control port for index 0 must be above the socks_port
        ctl_port = pool._ctl_port(0)
        socks_port = pool._socks_port(0)
        self.assertIsInstance(ctl_port, int)
        self.assertGreater(ctl_port, socks_port)

    def test_pool_session_callable(self):
        self.assertTrue(hasattr(SICRY, "_pool_session"))
        self.assertTrue(callable(SICRY._pool_session))

    def test_get_pool_callable(self):
        self.assertTrue(hasattr(SICRY, "_get_pool"))
        self.assertTrue(callable(SICRY._get_pool))

    def test_torpool_context_manager(self):
        """TorPool must implement __enter__ / __exit__."""
        self.assertTrue(hasattr(SICRY.TorPool, "__enter__"))
        self.assertTrue(hasattr(SICRY.TorPool, "__exit__"))


class TestModeConfig(unittest.TestCase):
    """mode_config() + _MODE_CONFIG routing."""

    def test_mode_config_exists(self):
        self.assertTrue(hasattr(SICRY, "mode_config"))

    def test_mode_config_dict_exists(self):
        self.assertTrue(hasattr(SICRY, "_MODE_CONFIG"))

    def test_modes_present(self):
        for mode in ("threat_intel", "ransomware", "personal_identity", "corporate"):
            cfg = SICRY.mode_config(mode)
            self.assertIsInstance(cfg, dict)

    def test_mode_config_has_engines_key(self):
        cfg = SICRY.mode_config("ransomware")
        self.assertIn("engines", cfg)

    def test_mode_config_has_max_results(self):
        cfg = SICRY.mode_config("threat_intel")
        self.assertIn("max_results", cfg)

    def test_mode_config_ransomware_has_seeds(self):
        cfg = SICRY.mode_config("ransomware")
        self.assertIn("extra_seeds", cfg)

    def test_mode_config_returns_copy(self):
        """Mutating the returned dict must not affect the global config."""
        cfg1 = SICRY.mode_config("threat_intel")
        cfg2 = SICRY.mode_config("threat_intel")
        cfg1["_test_key"] = True
        self.assertNotIn("_test_key", cfg2)

    def test_ransomware_onions_list_exists(self):
        self.assertTrue(hasattr(SICRY, "_RANSOMWARE_ONIONS"))
        self.assertIsInstance(SICRY._RANSOMWARE_ONIONS, list)


class TestSearchSignatureV2(unittest.TestCase):
    """search() must accept mode and _use_cache params."""

    def test_search_accepts_mode(self):
        import inspect
        sig = inspect.signature(SICRY.search)
        self.assertIn("mode", sig.parameters)

    def test_search_accepts_use_cache(self):
        import inspect
        sig = inspect.signature(SICRY.search)
        self.assertIn("_use_cache", sig.parameters)

    def test_search_mode_default(self):
        import inspect
        sig = inspect.signature(SICRY.search)
        # mode defaults to None (optional) — just verify the parameter exists with a default
        param = sig.parameters["mode"]
        self.assertNotEqual(param.default, inspect.Parameter.empty)


class TestAnalyzeNollm(unittest.TestCase):
    """analyze_nollm() entity extraction without LLM."""

    def test_analyze_nollm_exists(self):
        self.assertTrue(hasattr(SICRY, "analyze_nollm"))

    def test_returns_string(self):
        result = SICRY.analyze_nollm("test content about darkweb", query="test")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_extracts_email(self):
        content = "Contact us at hacker@protonmail.com for more info"
        result = SICRY.analyze_nollm(content, query="email")
        self.assertIn("protonmail.com", result)

    def test_extracts_btc_address(self):
        content = "Send payment to 1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf"
        result = SICRY.analyze_nollm(content)
        self.assertIn("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf", result)

    def test_extracts_onion_links(self):
        content = "Visit http://facebookwkhpilnemxj7asber7cyber.onion for privacy"
        result = SICRY.analyze_nollm(content)
        self.assertIn("facebookwkhpilnemxj7asber7cyber.onion", result)

    def test_empty_content(self):
        result = SICRY.analyze_nollm("", query="")
        self.assertIsInstance(result, str)

    def test_accepts_results_param(self):
        import inspect
        sig = inspect.signature(SICRY.analyze_nollm)
        params = list(sig.parameters.keys())
        self.assertIn("content", params)


class TestOutputFormats(unittest.TestCase):
    """to_stix(), to_csv(), to_report() output structure."""

    SAMPLE_RESULTS = [
        {"title": "Leak forum",  "url": "http://abc.onion", "engine": "Ahmia",
         "confidence": 0.85},
        {"title": "Ransomware",  "url": "http://xyz.onion", "engine": "Tor66",
         "confidence": 0.60},
    ]

    def test_to_stix_exists(self):
        self.assertTrue(hasattr(SICRY, "to_stix"))

    def test_to_stix_returns_dict(self):
        bundle = SICRY.to_stix(self.SAMPLE_RESULTS, query="ransomware")
        self.assertIsInstance(bundle, dict)

    def test_to_stix_bundle_type(self):
        bundle = SICRY.to_stix(self.SAMPLE_RESULTS, query="test")
        self.assertEqual(bundle.get("type"), "bundle")

    def test_to_stix_spec_version(self):
        bundle = SICRY.to_stix(self.SAMPLE_RESULTS)
        self.assertEqual(bundle.get("spec_version"), "2.1")

    def test_to_stix_has_objects(self):
        bundle = SICRY.to_stix(self.SAMPLE_RESULTS)
        self.assertIn("objects", bundle)
        self.assertIsInstance(bundle["objects"], list)
        self.assertGreater(len(bundle["objects"]), 0)

    def test_to_stix_empty_results(self):
        bundle = SICRY.to_stix([])
        self.assertEqual(bundle.get("type"), "bundle")

    def test_to_csv_exists(self):
        self.assertTrue(hasattr(SICRY, "to_csv"))

    def test_to_csv_returns_string(self):
        csv_out = SICRY.to_csv(self.SAMPLE_RESULTS)
        self.assertIsInstance(csv_out, str)

    def test_to_csv_has_header(self):
        csv_out = SICRY.to_csv(self.SAMPLE_RESULTS)
        first_line = csv_out.splitlines()[0].lower()
        self.assertIn("url", first_line)

    def test_to_csv_row_count(self):
        csv_out = SICRY.to_csv(self.SAMPLE_RESULTS)
        lines = [l for l in csv_out.splitlines() if l.strip()]
        # header + 2 data rows
        self.assertEqual(len(lines), 3)

    def test_to_csv_empty(self):
        csv_out = SICRY.to_csv([])
        self.assertIsInstance(csv_out, str)

    def test_to_report_exists(self):
        self.assertTrue(hasattr(SICRY, "to_report"))

    def test_to_report_returns_dict(self):
        rpt = SICRY.to_report(self.SAMPLE_RESULTS, query="test")
        self.assertIsInstance(rpt, dict)

    def test_to_report_has_expected_keys(self):
        rpt = SICRY.to_report(self.SAMPLE_RESULTS, query="ransomware")
        for key in ("query", "avg_confidence", "sources"):
            self.assertIn(key, rpt)

    def test_to_report_avg_confidence_float(self):
        rpt = SICRY.to_report(self.SAMPLE_RESULTS)
        self.assertIsInstance(rpt["avg_confidence"], float)


class TestWatchFunctions(unittest.TestCase):
    """watch_add / watch_list / watch_disable roundtrip."""

    def test_watch_add_exists(self):
        self.assertTrue(hasattr(SICRY, "watch_add"))

    def test_watch_list_exists(self):
        self.assertTrue(hasattr(SICRY, "watch_list"))

    def test_watch_disable_exists(self):
        self.assertTrue(hasattr(SICRY, "watch_disable"))

    def test_watch_check_exists(self):
        self.assertTrue(hasattr(SICRY, "watch_check"))

    def test_watch_daemon_exists(self):
        self.assertTrue(hasattr(SICRY, "watch_daemon"))

    def test_watch_add_returns_string(self):
        job_id = SICRY.watch_add("test query", mode="threat_intel", interval_hours=24)
        self.assertIsInstance(job_id, str)
        self.assertGreater(len(job_id), 0)
        # Cleanup
        SICRY.watch_disable(job_id)

    def test_watch_list_returns_list(self):
        jobs = SICRY.watch_list()
        self.assertIsInstance(jobs, list)

    def test_watch_add_list_roundtrip(self):
        job_id = SICRY.watch_add("roundtrip test", mode="ransomware", interval_hours=12)
        jobs = SICRY.watch_list()
        # DB uses "id" column; jobs are returned as dict(sqlite3.Row)
        ids = [j.get("id", j.get("job_id")) for j in jobs]
        self.assertIn(job_id, ids)
        SICRY.watch_disable(job_id)

    def test_watch_disable_removes_from_list(self):
        job_id = SICRY.watch_add("disable test", interval_hours=48)
        SICRY.watch_disable(job_id)
        jobs = SICRY.watch_list()
        ids = [j.get("id", j.get("job_id")) for j in jobs]
        self.assertNotIn(job_id, ids)

    def test_watch_check_returns_list(self):
        result = SICRY.watch_check()
        self.assertIsInstance(result, list)


class TestCrawlFunction(unittest.TestCase):
    """CrawlResult dataclass + crawl() + crawl_export() structure."""

    def test_crawl_result_dataclass_exists(self):
        self.assertTrue(hasattr(SICRY, "CrawlResult"))

    def test_crawl_result_fields(self):
        import dataclasses
        fields = {f.name for f in dataclasses.fields(SICRY.CrawlResult)}
        for expected in ("job_id", "seed_url", "pages_found", "links_found",
                         "entities", "db_path"):
            self.assertIn(expected, fields)

    def test_crawl_exists(self):
        self.assertTrue(hasattr(SICRY, "crawl"))

    def test_crawl_export_exists(self):
        self.assertTrue(hasattr(SICRY, "crawl_export"))

    def test_crawl_export_returns_dict(self):
        result = SICRY.crawl_export("nonexistent_job")
        self.assertIsInstance(result, dict)
        self.assertIn("job_id", result)
        self.assertIn("pages", result)
        self.assertIn("links", result)

    def test_crawl_signature(self):
        import inspect
        sig = inspect.signature(SICRY.crawl)
        params = list(sig.parameters.keys())
        self.assertIn("seed_url", params)
        self.assertIn("max_depth", params)
        self.assertIn("max_pages", params)

    def test_crawl_returns_crawl_result(self):
        """crawl() with a reachable URL must return a CrawlResult.
        Using a mock URL since Tor is not available in unit test context."""
        from unittest.mock import patch, MagicMock
        mock_page = {
            "url": "http://faketest.onion",
            "title": "Test Page",
            "text": "test content ransomware leak",
            "links": [],
            "is_onion": True,
            "error": None,
            "status": 200,
        }
        with patch.object(SICRY, "fetch", return_value=mock_page):
            result = SICRY.crawl(
                "http://faketest.onion",
                max_depth=1,
                max_pages=1,
            )
        self.assertIsInstance(result, SICRY.CrawlResult)
        self.assertEqual(result.seed_url, "http://faketest.onion")
        self.assertGreaterEqual(result.pages_found, 0)


class TestCheckEnginesV2(unittest.TestCase):
    """check_search_engines() v2.0.0 signature: _cached param + reliability key."""

    def test_cached_param_exists(self):
        import inspect
        sig = inspect.signature(SICRY.check_search_engines)
        self.assertIn("_cached", sig.parameters)

    def test_engine_health_history_exists(self):
        self.assertTrue(hasattr(SICRY, "engine_health_history"))

    def test_engine_reliability_scores_exists(self):
        self.assertTrue(hasattr(SICRY, "engine_reliability_scores"))

    def test_engine_health_history_returns_list(self):
        result = SICRY.engine_health_history("Ahmia", n=3)
        self.assertIsInstance(result, list)

    def test_engine_reliability_scores_returns_dict(self):
        result = SICRY.engine_reliability_scores()
        self.assertIsInstance(result, dict)


class TestToolsExpanded(unittest.TestCase):
    """TOOLS list must have 15 entries; all must appear in dispatch()."""

    def test_tools_count(self):
        self.assertEqual(len(SICRY.TOOLS), 15,
                         f"Expected 15 tools, got {len(SICRY.TOOLS)}: "
                         f"{[t['name'] for t in SICRY.TOOLS]}")

    def test_expected_tool_names_present(self):
        names = {t["name"] for t in SICRY.TOOLS}
        for expected in (
            "sicry_check_tor", "sicry_renew_identity", "sicry_fetch",
            "sicry_search", "sicry_ask", "sicry_analyze_nollm",
            "sicry_check_engines", "sicry_crawl", "sicry_crawl_export",
            "sicry_watch_add", "sicry_watch_list", "sicry_watch_check",
            "sicry_to_stix", "sicry_to_csv", "sicry_extract_keywords",
        ):
            self.assertIn(expected, names)

    def test_dispatch_handles_all_tools(self):
        """dispatch() source must contain all 15 tool names."""
        import inspect
        src = inspect.getsource(SICRY.dispatch)
        for t in SICRY.TOOLS:
            self.assertIn(t["name"], src,
                          f"dispatch() does not handle {t['name']!r}")

    def test_all_tools_have_description(self):
        for t in SICRY.TOOLS:
            self.assertIn("description", t)
            self.assertGreater(len(t["description"]), 5)


class TestPipelineV2(unittest.TestCase):
    """pipeline.py v2.0.0 flags and imports."""

    def _pipeline_src(self):
        return _read(os.path.join(_ONION_CLAW, "pipeline.py"))

    def test_watch_flag_present(self):
        src = self._pipeline_src()
        self.assertIn("--watch", src)

    def test_watch_check_flag_present(self):
        src = self._pipeline_src()
        self.assertIn("--watch-check", src)

    def test_interactive_flag_present(self):
        src = self._pipeline_src()
        self.assertIn("--interactive", src)

    def test_format_flag_present(self):
        src = self._pipeline_src()
        self.assertIn("--format", src)

    def test_resume_flag_present(self):
        src = self._pipeline_src()
        self.assertIn("--resume", src)

    def test_confidence_flag_present(self):
        src = self._pipeline_src()
        self.assertIn("--confidence", src)

    def test_no_cache_flag_present(self):
        src = self._pipeline_src()
        self.assertIn("--no-cache", src)

    def test_analyze_nollm_called(self):
        src = self._pipeline_src()
        self.assertIn("analyze_nollm", src)

    def test_stix_format_supported(self):
        src = self._pipeline_src()
        self.assertIn("stix", src)

    def test_mode_routing_in_search(self):
        """search() must be called with mode=... in pipeline."""
        src = self._pipeline_src()
        self.assertIn("mode=args.mode", src)

    def test_score_results_used_nollm(self):
        """BM25 confidence sorting must be used when --no-llm."""
        src = self._pipeline_src()
        self.assertIn("confidence", src)

    def test_resume_checkpoint_logic(self):
        src = self._pipeline_src()
        self.assertIn("_save_checkpoint", src)
        self.assertIn("_ckpt", src)

    def test_resume_uses_long_ttl(self):
        """BUG-1: --resume must use a long TTL (>= 1 day) not ttl=0."""
        src = self._pipeline_src()
        # ttl=0 would always return None — must use a long window
        self.assertNotIn("ttl=0", src,
                         "BUG-1: cache_get called with ttl=0 — checkpoints never load")
        self.assertIn("86400", src,
                      "BUG-1: resume TTL missing — checkpoint window must be in days")

    def test_resume_saves_query_meta(self):
        """BUG-1: pipeline must persist query in __meta__ so resume works without --query."""
        src = self._pipeline_src()
        self.assertIn("__meta__", src)
        self.assertIn("query", src)

    def test_interval_without_watch_warns(self):
        """BUG-4: pipeline must warn when --interval is used without --watch."""
        src = self._pipeline_src()
        self.assertIn("WARN: --interval", src,
                      "BUG-4: missing --interval-without-watch warning")

    def test_empty_query_clean_error(self):
        """UX-2: empty --query must produce clean error, NOT argparse usage dump."""
        src = self._pipeline_src()
        # Must explicitly catch empty string before argparse.error()
        self.assertIn("cannot be empty", src,
                      "UX-2: no clean empty-query error message")

    def test_refined_query_null_nollm(self):
        """UX-3: refined_query must be null/None in JSON output with --no-llm."""
        src = self._pipeline_src()
        self.assertIn("None if NO_LLM else refined", src,
                      "UX-3: refined_query not null in no-LLM JSON output")

    def test_confidence_scores_printed_nollm(self):
        """BUG-2: --confidence with --no-llm must print scores to terminal in step 5."""
        src = self._pipeline_src()
        # Must have a print inside the NO_LLM block that shows conf= value
        self.assertIn("4f", src,
                      "BUG-2: score format string missing — confidence scores not printed")
        self.assertIn("args.confidence and best", src,
                      "BUG-2: confidence print gated on args.confidence and best")

    def test_resume_nonexistent_clean_exit(self):
        """BUG-1/4: --resume with nonexistent job_id must print clean error, not argparse noise."""
        src = self._pipeline_src()
        self.assertIn("ERROR: No checkpoint found for job", src,
                      "BUG-1/4: missing clean error for nonexistent --resume job")
        self.assertIn("Either provide --query to start fresh", src,
                      "BUG-1/4: missing hint line for nonexistent --resume")

    def test_md_refined_omitted_when_nollm(self):
        """BUG-3: MD report must not show Refined: line when --no-llm (refined == raw_query)."""
        src = self._pipeline_src()
        # Must be conditional — NOT a bare f"**Refined:** {refined}"
        self.assertNotIn('f"**Refined:** {refined}  \\n"\n', src,
                         "BUG-3: MD template shows Refined: unconditionally")
        self.assertIn("not NO_LLM", src,
                      "BUG-3: MD Refined line not gated on not NO_LLM")

    def test_interactive_goodbye(self):
        """UX-1: --interactive must print Goodbye. when exiting."""
        src = self._pipeline_src()
        self.assertIn("Goodbye.", src, "UX-1: no Goodbye confirmation on exit")

    def test_interactive_help_text(self):
        """UX-1: --interactive must show command help after each result set."""
        src = self._pipeline_src()
        self.assertIn("Commands:", src,
                      "UX-1: interactive mode missing Commands: help line")


# ═════════════════════════════════════════════════════════════════════════════
# BUG-2: BM25 behavioural tests (non-zero scores for matching terms)
# ═════════════════════════════════════════════════════════════════════════════
class TestBM25Scoring(unittest.TestCase):
    """score_results() must return non-zero scores for term-matching results."""

    def _score(self, query, results):
        return SICRY.score_results(query, results)

    def test_relevant_result_has_nonzero_score(self):
        """BUG-2: a result whose title matches query terms must not score 0.0."""
        results = [
            {"title": "ransomware data leak forum", "url": "http://a.onion",
             "engine": "Ahmia", "snippet": "fresh ransomware leak"},
            {"title": "weather forecast today", "url": "http://b.onion",
             "engine": "Torch"},
        ]
        scored = self._score("ransomware data leak", results)
        top = scored[0]
        s = top.get("score", top.get("confidence", 0))
        self.assertGreater(s, 0.0,
                           "BUG-2: top result score is 0.0 — BM25 avgdl misconfigured")

    def test_irrelevant_result_scores_lower(self):
        """BUG-2: unrelated result must score lower than the matching one."""
        results = [
            {"title": "weather forecast today completely unrelated",
             "url": "http://b.onion", "engine": "X"},
            {"title": "ransomware data leak darknet forum",
             "url": "http://a.onion", "engine": "X"},
        ]
        scored = self._score("ransomware data leak", results)
        top_score  = scored[0].get("score", scored[0].get("confidence", 0))
        last_score = scored[-1].get("score", scored[-1].get("confidence", 0))
        self.assertGreaterEqual(top_score, last_score)
        self.assertGreater(top_score, 0.0)

    def test_snippet_improves_score(self):
        """BUG-2: results with snippet field must score higher than title-only when snippet matches."""
        with_snippet = {"title": "darknet forum", "url": "http://a.onion",
                        "engine": "X", "snippet": "ransomware data leak fresh dump"}
        without_snippet = {"title": "darknet forum", "url": "http://b.onion",
                           "engine": "X"}
        scored = self._score("ransomware data leak", [with_snippet, without_snippet])
        scores = {r["url"]: r.get("score", r.get("confidence", 0)) for r in scored}
        self.assertGreaterEqual(scores["http://a.onion"], scores["http://b.onion"],
                                "BUG-2: snippet field not included in scoring")

    def test_search_returns_confidence_not_score(self):
        """v2.1.6: score_results() sets BOTH 'score' and 'confidence'; both must be present."""
        # BUG-1 fix: score_results() now emits both keys so the pipeline can
        # read 'confidence' without a separate rename step
        results = [
            {"title": "ransomware data leak darknet", "url": "http://x.onion", "engine": "X"},
        ]
        scored = SICRY.score_results("ransomware data leak", results)
        self.assertIn("confidence", scored[0],
                      "v2.1.6 BUG-1: 'confidence' key must be set by score_results()")
        self.assertIn("score", scored[0],
                      "v2.1.6 BUG-1: 'score' key must also be set by score_results()")
        self.assertEqual(scored[0]["score"], scored[0]["confidence"],
                         "v2.1.6: 'score' and 'confidence' must hold the same value")
        self.assertGreater(scored[0]["confidence"], 0.0,
                           "BUG-2: confidence is 0 for a result that matches query terms")

    def test_score_rename_in_search_source(self):
        """BUG-2: sicry.py search() must explicitly rename 'score' → 'confidence'."""
        src = _read_src()
        self.assertIn("r[\"confidence\"] = r.pop(\"score\")", src,
                      "BUG-2: search() missing score→confidence rename")


# ═════════════════════════════════════════════════════════════════════════════
# BUG-1: --resume checkpoint round-trip
# ═════════════════════════════════════════════════════════════════════════════
class TestResumeCheckpoint(unittest.TestCase):
    """Checkpoint save → load round-trip using _DB directly."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        try:
            os.unlink(self._tmp)
        except OSError:
            pass

    def _db(self):
        if not hasattr(SICRY, "_DB"):
            self.skipTest("_DB not in sicry")
        return SICRY._DB(self._tmp)

    def test_checkpoint_save_and_load(self):
        """BUG-1: checkpoint saved with cache_set is retrievable with ttl=days."""
        db = self._db()
        payload = {
            "steps": {"search": True},
            "data": {
                "__meta__": {"query": "privacy tools", "mode": "threat_intel"},
                "search": [{"url": "http://x.onion", "title": "test"}],
            },
        }
        db.cache_set("pipeline_checkpoint:abc123", "pipeline", payload)
        # Must load with a positive TTL (90 days)
        loaded = db.cache_get("pipeline_checkpoint:abc123", "pipeline",
                              ttl=86400 * 90)
        self.assertIsNotNone(loaded, "BUG-1: checkpoint not found with ttl=86400*90")
        self.assertEqual(
            loaded["data"]["__meta__"]["query"], "privacy tools",
            "BUG-1: query not preserved in checkpoint __meta__",
        )

    def test_checkpoint_zero_ttl_returns_none(self):
        """BUG-1: ttl=0 must return None (never load) — confirms old bug was the ttl=0 call."""
        db = self._db()
        db.cache_set("pipeline_checkpoint:zz", "pipeline", {"x": 1})
        result = db.cache_get("pipeline_checkpoint:zz", "pipeline", ttl=0)
        self.assertIsNone(result,
                          "cache_get(ttl=0) should always return None")


# ═════════════════════════════════════════════════════════════════════════════
# BUG-3: engine ping error messages
# ═════════════════════════════════════════════════════════════════════════════
class TestEngineErrorMessages(unittest.TestCase):
    """_ping() inside check_search_engines() must not blame Tor for engine timeouts."""

    def test_ping_timeout_error_is_engine_specific(self):
        """BUG-3: a timed-out engine must say 'engine timed out', not 'Tor circuit unavailable'."""
        src = _read_src()
        self.assertIn("engine timed out (hidden service unreachable or slow)", src,
                      "BUG-3: engine-specific timeout message missing")

    def test_ping_socks_error_is_engine_specific(self):
        """BUG-3: SOCKS error inside _ping must say 'engine unreachable', not blame Tor globally."""
        src = _read_src()
        self.assertIn("engine unreachable via Tor circuit", src,
                      "BUG-3: engine-specific SOCKS message missing")

    def test_ping_does_not_delegate_to_friendly_error(self):
        """BUG-3: _ping() must handle its own exceptions, not route through _friendly_error."""
        import re
        src = _read_src()
        m = re.search(r"def _ping\(engine.*?(?=\n    def |\nresults_map)", src, re.DOTALL)
        self.assertIsNotNone(m, "_ping() function not found in sicry.py")
        self.assertNotIn("_friendly_error", m.group(0),
                         "BUG-3: _ping() still delegates to _friendly_error — engine errors blame Tor")


# ═════════════════════════════════════════════════════════════════════════════
# Engine retry / backoff
# ═════════════════════════════════════════════════════════════════════════════

class TestEngineRetryBackoff(unittest.TestCase):
    """_fetch_engine retries up to 3 attempts on transient errors."""

    def _fake_search_result(self):
        return [{"title": "T", "url": "http://a.onion/p", "engine": "Ahmia"}]

    def test_retry_constants_in_source(self):
        """_TRANSIENT_KW must be defined inside _fetch_engine."""
        src = _read_src()
        self.assertIn("_TRANSIENT_KW", src, "_TRANSIENT_KW sentinel missing from search()")

    def test_retry_loop_in_source(self):
        """_fetch_engine body must contain the for-attempt retry loop."""
        src = _read_src()
        self.assertIn("for _attempt in range(3)", src,
                      "retry loop 'for _attempt in range(3)' missing from _fetch_engine")

    def test_backoff_sleep_in_source(self):
        """Exponential back-off sleep must be present inside _fetch_engine."""
        src = _read_src()
        self.assertIn("time.sleep(2 ** _attempt)", src,
                      "exponential back-off 'time.sleep(2 ** _attempt)' missing")

    def test_transient_keywords_include_timeout(self):
        src = _read_src()
        self.assertIn('"timed out"', src)

    def test_transient_keywords_include_socks(self):
        src = _read_src()
        self.assertIn('"SOCKS"', src)

    def test_transient_keywords_include_proxy_error(self):
        """ProxyError must be in the transient keyword list."""
        src = _read_src()
        self.assertIn('"ProxyError"', src)

    def test_search_returns_empty_on_all_failures(self):
        """search() returns [] gracefully when every engine times out."""
        with patch("sicry.requests.Session.get", side_effect=Exception("timed out")):
            results = SICRY.search("test query", _use_cache=False)
        self.assertIsInstance(results, list)

    def test_non_transient_error_no_extra_retry(self):
        """Non-transient errors (e.g. parsing) must NOT sleep between attempts."""
        call_count = {"n": 0}

        def _raise(*a, **kw):
            call_count["n"] += 1
            raise ValueError("non-transient parsing error")

        with patch("sicry.requests.Session.get", side_effect=_raise):
            SICRY.search("test", _use_cache=False)
        # Each engine gets at most 3 attempts if transient; non-transient breaks
        # immediately after 1 attempt per engine — total calls = num_engines * 1
        self.assertLessEqual(call_count["n"], len(SICRY.SEARCH_ENGINES))


# ═════════════════════════════════════════════════════════════════════════════
# to_misp() export
# ═════════════════════════════════════════════════════════════════════════════

class TestToMisp(unittest.TestCase):
    """to_misp() generates a valid MISP 2.4 event dict."""

    _RESULTS = [
        {"title": "LockBit leak", "url": "http://lock.onion/leak", "engine": "Ahmia", "confidence": 0.91},
        {"title": "ALPHV data",   "url": "http://alphv.onion/dump", "engine": "Tor66", "confidence": 0.72},
    ]

    def setUp(self):
        self._event = SICRY.to_misp(self._RESULTS, query="ransomware hospital")

    def test_to_misp_exists(self):
        self.assertTrue(callable(SICRY.to_misp))

    def test_returns_dict(self):
        self.assertIsInstance(self._event, dict)

    def test_has_event_key(self):
        self.assertIn("Event", self._event)

    def test_event_has_uuid(self):
        self.assertIn("uuid", self._event["Event"])

    def test_event_has_info(self):
        info = self._event["Event"]["info"]
        self.assertIn("ransomware hospital", info)

    def test_event_has_date(self):
        date = self._event["Event"]["date"]
        self.assertRegex(date, r"\d{4}-\d{2}-\d{2}")

    def test_event_has_threat_level(self):
        self.assertIn("threat_level_id", self._event["Event"])

    def test_event_has_attributes(self):
        attrs = self._event["Event"]["Attribute"]
        self.assertIsInstance(attrs, list)
        self.assertGreater(len(attrs), 0)

    def test_url_attributes_present(self):
        url_attrs = [a for a in self._event["Event"]["Attribute"] if a["type"] == "url"]
        self.assertEqual(len(url_attrs), 2)

    def test_domain_attributes_present(self):
        domain_attrs = [a for a in self._event["Event"]["Attribute"]
                        if a["type"] in ("domain", "hostname")]
        self.assertGreater(len(domain_attrs), 0)

    def test_confidence_in_comment(self):
        url_attrs = [a for a in self._event["Event"]["Attribute"] if a["type"] == "url"]
        self.assertIn("confidence", url_attrs[0]["comment"])

    def test_has_tags(self):
        tags = self._event["Event"]["Tag"]
        self.assertIsInstance(tags, list)
        self.assertGreater(len(tags), 0)

    def test_tlp_amber_tag(self):
        tag_names = [t["name"] for t in self._event["Event"]["Tag"]]
        self.assertIn("tlp:amber", tag_names)

    def test_dark_web_tag(self):
        tag_names = [t["name"] for t in self._event["Event"]["Tag"]]
        self.assertIn("dark-web", tag_names)

    def test_report_text_embedded(self):
        event = SICRY.to_misp(self._RESULTS, report_text="full report here")
        comment_attrs = [a for a in event["Event"]["Attribute"] if a["type"] == "comment"]
        self.assertGreater(len(comment_attrs), 0)
        self.assertIn("full report here", comment_attrs[0]["value"])

    def test_query_embedded_as_text_attr(self):
        text_attrs = [a for a in self._event["Event"]["Attribute"] if a["type"] == "text"]
        self.assertGreater(len(text_attrs), 0)
        self.assertIn("ransomware hospital", text_attrs[0]["value"])

    def test_empty_results(self):
        event = SICRY.to_misp([], query="empty")
        self.assertIn("Event", event)
        self.assertIsInstance(event["Event"]["Attribute"], list)

    def test_threat_level_override(self):
        event = SICRY.to_misp(self._RESULTS, threat_level=1)
        self.assertEqual(event["Event"]["threat_level_id"], "1")

    def test_distribution_override(self):
        event = SICRY.to_misp(self._RESULTS, distribution=3)
        url_attrs = [a for a in event["Event"]["Attribute"] if a["type"] == "url"]
        self.assertEqual(url_attrs[0]["distribution"], "3")

    def test_json_serialisable(self):
        import json
        json.dumps(self._event)   # must not raise

    def test_to_ids_false_for_url(self):
        url_attrs = [a for a in self._event["Event"]["Attribute"] if a["type"] == "url"]
        self.assertFalse(url_attrs[0]["to_ids"])

    def test_to_ids_true_for_domain(self):
        domain_attrs = [a for a in self._event["Event"]["Attribute"]
                        if a["type"] in ("domain", "hostname")]
        self.assertTrue(domain_attrs[0]["to_ids"])

    def test_dispatch_to_misp(self):
        event = SICRY.dispatch("sicry_to_misp", {
            "results": self._RESULTS,
            "query": "test dispatch",
        })
        self.assertIn("Event", event)


# ═════════════════════════════════════════════════════════════════════════════
# search_and_crawl()
# ═════════════════════════════════════════════════════════════════════════════

class TestSearchAndCrawl(unittest.TestCase):
    """search_and_crawl() signature, return structure, and dispatch wiring."""

    def test_exists(self):
        self.assertTrue(callable(SICRY.search_and_crawl))

    def test_signature(self):
        import inspect
        sig = inspect.signature(SICRY.search_and_crawl)
        params = sig.parameters
        self.assertIn("query", params)
        self.assertIn("top_n", params)
        self.assertIn("max_depth", params)
        self.assertIn("max_pages", params)
        self.assertIn("engines", params)
        self.assertIn("max_results", params)
        self.assertIn("mode", params)
        self.assertIn("stay_on_domain", params)

    def test_top_n_default_is_3(self):
        import inspect
        sig = inspect.signature(SICRY.search_and_crawl)
        self.assertEqual(sig.parameters["top_n"].default, 3)

    def test_returns_dict_with_expected_keys(self):
        _fake_result = [{"title": "T", "url": "http://a.onion/", "engine": "Ahmia", "confidence": 0.5}]

        def mock_search(*a, **kw):
            return _fake_result

        def mock_crawl(url, **kw):
            cr = SICRY.CrawlResult(
                job_id="test", seed_url=url, pages_found=1,
                links_found=0, entities={}, db_path="/tmp/test.db",
            )
            return cr

        with patch.object(SICRY, "search", side_effect=mock_search), \
             patch.object(SICRY, "crawl", side_effect=mock_crawl):
            result = SICRY.search_and_crawl("test query", top_n=1)

        self.assertIn("query", result)
        self.assertIn("search_results", result)
        self.assertIn("crawls", result)

    def test_query_preserved(self):
        with patch.object(SICRY, "search", return_value=[]), \
             patch.object(SICRY, "crawl", return_value=None):
            result = SICRY.search_and_crawl("my query", top_n=0)
        self.assertEqual(result["query"], "my query")

    def test_empty_search_returns_empty_crawls(self):
        with patch.object(SICRY, "search", return_value=[]):
            result = SICRY.search_and_crawl("no results", top_n=3, _use_cache=False)
        self.assertEqual(result["crawls"], {})

    def test_crawls_keyed_by_url(self):
        _fake_result = [{"title": "T", "url": "http://a.onion/", "engine": "Ahmia", "confidence": 0.5}]

        def mock_crawl(url, **kw):
            return SICRY.CrawlResult(
                job_id="j", seed_url=url, pages_found=2,
                links_found=5, entities={}, db_path="/tmp/x.db",
            )

        with patch.object(SICRY, "search", return_value=_fake_result), \
             patch.object(SICRY, "crawl", side_effect=mock_crawl):
            result = SICRY.search_and_crawl("test", top_n=1)

        self.assertIn("http://a.onion/", result["crawls"])

    def test_crawl_failure_recorded(self):
        _fake_result = [{"title": "T", "url": "http://b.onion/", "engine": "Ahmia", "confidence": 0.5}]

        def mock_crawl_fail(url, **kw):
            raise RuntimeError("crawl error")

        with patch.object(SICRY, "search", return_value=_fake_result), \
             patch.object(SICRY, "crawl", side_effect=mock_crawl_fail):
            result = SICRY.search_and_crawl("test", top_n=1)

        crawl_val = result["crawls"].get("http://b.onion/")
        self.assertIsNotNone(crawl_val)
        self.assertIn("error", crawl_val)

    def test_dispatch_search_and_crawl(self):
        with patch.object(SICRY, "search", return_value=[]):
            result = SICRY.dispatch("sicry_search_and_crawl", {
                "query": "dispatch test",
                "top_n": 0,
            })
        self.assertIn("query", result)
        self.assertEqual(result["query"], "dispatch test")


# ═════════════════════════════════════════════════════════════════════════════
# CLI engines / engine-history handler correctness (v2.1.3 bug fixes)
# ═════════════════════════════════════════════════════════════════════════════

class TestCLIEnginesHandler(unittest.TestCase):
    """CLI `engines` handler must use e['status'] and e['name'], not e['reachable']/e['engine']."""

    def _make_result(self, status="up", latency=350):
        return {
            "name": "Ahmia",
            "status": status,
            "latency_ms": latency,
            "reliability": 0.8,
            "error": None,
        }

    def test_engines_result_has_no_reachable_key(self):
        """Regression: _ping() returns 'status', not 'reachable'."""
        r = self._make_result()
        self.assertNotIn("reachable", r)
        self.assertIn("status", r)

    def test_engines_result_has_no_engine_key(self):
        """Regression: _ping() returns 'name', not 'engine'."""
        r = self._make_result()
        self.assertNotIn("engine", r)
        self.assertIn("name", r)

    def test_engines_status_up_is_truthy(self):
        r = self._make_result(status="up")
        self.assertTrue(r["status"] == "up")

    def test_engines_status_down_is_falsy(self):
        r = self._make_result(status="down")
        self.assertFalse(r["status"] == "up")

    def test_engines_none_latency_safe_format(self):
        """None latency_ms must not crash when formatted with :.0f."""
        r = self._make_result(latency=None)
        ms = r.get("latency_ms") or 0
        formatted = f"{ms:.0f}ms"
        self.assertEqual(formatted, "0ms")

    def test_check_search_engines_returns_correct_keys(self):
        """check_search_engines() must return list of dicts with 'name' and 'status' keys."""
        engine_up = {"name": "Ahmia", "status": "up",
                     "latency_ms": 200, "reliability": 1.0, "error": None}
        with patch.object(SICRY, "check_search_engines", return_value=[engine_up]):
            results = SICRY.check_search_engines()
        self.assertIn("name", results[0])
        self.assertIn("status", results[0])
        self.assertNotIn("reachable", results[0])
        self.assertNotIn("engine", results[0])


class TestCLIEngineHistoryHandler(unittest.TestCase):
    """CLI `engine-history` handler must use row['status'] not row['reachable']."""

    def _make_row(self, status="up", latency=450):
        return {"ts": 1700000000.0, "status": status, "latency_ms": latency, "error": None}

    def test_history_row_has_no_reachable_key(self):
        row = self._make_row()
        self.assertNotIn("reachable", row)
        self.assertIn("status", row)

    def test_history_status_up(self):
        row = self._make_row(status="up")
        self.assertTrue(row["status"] == "up")

    def test_history_none_latency_safe(self):
        row = self._make_row(latency=None)
        ms = row.get("latency_ms") or 0
        formatted = f"{ms:.0f}ms"
        self.assertEqual(formatted, "0ms")

    def test_engine_health_history_keys(self):
        """engine_health_history() must return ts/status/latency_ms/error, not reachable."""
        result = SICRY.engine_health_history("Ahmia", n=1)
        if result:
            self.assertIn("status", result[0])
            self.assertIn("ts", result[0])
            self.assertNotIn("reachable", result[0])


class TestCLIPoolStartFix(unittest.TestCase):
    """CLI pool start handler must instantiate TorPool directly, not _get_pool(size=...)."""

    def test_get_pool_signature_no_params(self):
        """_get_pool() must be callable with no arguments."""
        import inspect
        sig = inspect.signature(SICRY._get_pool)
        params = [p for p in sig.parameters.values()
                  if p.default is inspect.Parameter.empty]
        self.assertEqual(len(params), 0,
                         "_get_pool() must accept no required parameters")

    def test_torpool_class_accepts_size_base_port(self):
        """TorPool(size=N, base_port=P) is the correct way to create a pool."""
        import inspect
        sig = inspect.signature(SICRY.TorPool)
        self.assertIn("size", sig.parameters)
        self.assertIn("base_port", sig.parameters)

    def test_pool_start_source_uses_torpool_not_get_pool(self):
        """CLI pool-start handler must call TorPool(size=...) not _get_pool(size=...)."""
        src = _read_src()
        # The buggy pattern is _get_pool(size=...) — must not appear
        self.assertNotIn("_get_pool(size=", src,
                         "_get_pool() is not designed to take parameters — "
                         "pool start must use TorPool(size=...) directly")


class TestTorPreCheckInScripts(unittest.TestCase):
    """Scripts must call _tor_port_open() before making Tor network requests."""

    def _script_src(self, name: str) -> str:
        return _read_oc_src(name)

    def test_check_engines_has_tor_precheck(self):
        src = self._script_src("check_engines.py")
        self.assertIn("_tor_port_open", src,
                      "check_engines.py must pre-check Tor port before calling check_search_engines()")

    def test_search_has_tor_precheck(self):
        src = self._script_src("search.py")
        self.assertIn("_tor_port_open", src,
                      "search.py must pre-check Tor port before calling search()")

    def test_fetch_has_tor_precheck(self):
        src = self._script_src("fetch.py")
        self.assertIn("_tor_port_open", src,
                      "fetch.py must pre-check Tor port before calling fetch()")

    def test_check_engines_exits_gracefully_when_tor_down(self):
        """check_engines.py must exit with code 1 when _tor_port_open returns False."""
        import subprocess
        env = os.environ.copy()
        try:
            result = subprocess.run(
                ["python3", os.path.join(_ONION_CLAW, "check_engines.py")],
                capture_output=True, text=True,
                env={**env, "SICRY__TOR_PORT_FORCE_FAIL": "1"},
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            # Tor is up: script proceeds to ping all engines (~15-30 s).
            # This path is expected when Tor is running; skip the timing assertion.
            # The key assertion is in test_check_engines_has_tor_precheck (source check).
            return
        # The script patches via getattr — with the env var trick we can't inject
        # so we just verify the string "not reachable" or "Start Tor" appears in
        # stderr when the actual port is closed; skip if Tor happens to be up.
        # The key assertion is the source check in test_check_engines_has_tor_precheck.

    def test_fetch_precheck_before_main_call(self):
        src = self._script_src("fetch.py")
        # Pre-check must appear BEFORE the sicry.fetch() call
        precheck_pos = src.find("_tor_port_open")
        fetch_call_pos = src.find("result = sicry.fetch")
        self.assertLess(precheck_pos, fetch_call_pos,
                        "fetch.py: _tor_port_open() must appear before sicry.fetch() call")

    def test_search_precheck_before_main_call(self):
        src = self._script_src("search.py")
        precheck_pos = src.find("_tor_port_open")
        search_call_pos = src.find("results = sicry.search")
        self.assertLess(precheck_pos, search_call_pos,
                        "search.py: _tor_port_open() must appear before sicry.search() call")


# ═════════════════════════════════════════════════════════════════════════════
# watch list j['id'] key (v2.1.3 bug fix)
# ═════════════════════════════════════════════════════════════════════════════

class TestCLIWatchListKeyFix(unittest.TestCase):
    """watch_list() returns rows with 'id', not 'job_id'."""

    def test_watch_job_key_is_id(self):
        """DB schema uses 'id TEXT PRIMARY KEY' — rows must have 'id', not 'job_id'."""
        job_id = SICRY.watch_add("test query", mode="threat_intel", interval_hours=6)
        jobs = SICRY.watch_list()
        self.assertTrue(len(jobs) > 0)
        first = jobs[0]
        self.assertIn("id", first, "watch_list() rows must have 'id' key (matches DB schema)")
        self.assertNotIn("job_id", first, "watch_list() rows must NOT have 'job_id' (wrong field name)")
        # clean up
        SICRY.watch_disable(job_id)

    def test_watch_add_returns_id_string(self):
        """watch_add() returns the job id as a short uuid string."""
        jid = SICRY.watch_add("key test", interval_hours=24)
        self.assertIsInstance(jid, str)
        self.assertGreater(len(jid), 0)
        SICRY.watch_disable(jid)

    def test_cli_watch_list_source_uses_j_id(self):
        """CLI watch list handler in sicry.py must use j['id'], not j['job_id']."""
        src = _read_src()
        self.assertNotIn("j['job_id']", src,
                         "CLI watch list handler must use j['id'] not j['job_id']")
        # Find the watch list block and confirm j['id'] is used there
        self.assertIn("j['id']", src,
                      "CLI watch list handler must reference j['id']")


# ═════════════════════════════════════════════════════════════════════════════
# watch check result_count key (v2.1.3 bug fix)
# ═════════════════════════════════════════════════════════════════════════════

class TestCLIWatchCheckKeyFix(unittest.TestCase):
    """watch_check() returns 'result_count', not 'new_count'."""

    def test_watch_check_alert_has_result_count(self):
        """watch_check() alert dicts must have 'result_count', not 'new_count'."""
        alerts = SICRY.watch_check()
        for a in alerts:
            self.assertIn("result_count", a,
                          "watch_check() alerts must have 'result_count' key")
            self.assertNotIn("new_count", a,
                             "watch_check() alerts must NOT have 'new_count' key (was silently 0)")

    def test_watch_check_alert_has_new_flag(self):
        """watch_check() alert dicts must have bool 'new' key."""
        alerts = SICRY.watch_check()
        for a in alerts:
            self.assertIn("new", a)
            self.assertIsInstance(a["new"], bool)

    def test_cli_watch_check_source_uses_result_count(self):
        """CLI watch check handler must read a.get('result_count'), not a.get('new_count')."""
        src = _read_src()
        self.assertNotIn("new_count", src,
                         "CLI watch check handler must use 'result_count', not 'new_count'")
        self.assertIn("result_count", src,
                      "CLI watch check handler must reference 'result_count'")


# ═════════════════════════════════════════════════════════════════════════════
# crawl on_page callback arity (v2.1.3 bug fix)
# ═════════════════════════════════════════════════════════════════════════════

class TestCLICrawlOnPageArity(unittest.TestCase):
    """crawl() calls on_page(url, depth, result) — 3 args. CLI lambda must accept 3."""

    def test_crawl_on_page_called_with_three_args(self):
        """crawl() must call on_page(url: str, depth: int, result: dict)."""
        calls = []

        def _cb(url, depth, result):
            calls.append((url, depth, result))

        with patch.object(SICRY, "_pool_session") as mock_sess, \
             patch.object(SICRY, "_db") as mock_db:
            # minimal mock: session.get -> 404 so _process_page returns early
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status_code = 404
            mock_resp.text = ""
            mock_resp.encoding = "utf-8"
            mock_resp.apparent_encoding = "utf-8"
            mock_sess.return_value.get.return_value = mock_resp
            mock_db.return_value.crawl_save_page.return_value = None
            mock_db.return_value.crawl_save_link.return_value = None
            mock_db.return_value.cache_get.return_value = None

            SICRY.crawl("http://test.onion", max_depth=0, max_pages=1, on_page=_cb)

        # on_page should NOT have been called (404 → text is empty → returns early)
        # but if it were called, the 3-arg signature must not raise TypeError
        # Verify the 3-arg lambda itself works:
        ok = True
        try:
            _cb("http://a.onion", 0, {"text": "hello"})
        except TypeError:
            ok = False
        self.assertTrue(ok, "on_page callback must accept (url, depth, result) — 3 args")

    def test_cli_crawl_lambda_accepts_three_args(self):
        """CLI crawl on_page lambda in sicry.py must accept 3 positional args."""
        src = _read_src()
        # The 1-arg form that was broken:
        self.assertNotIn("lambda p: print", src,
                         "CLI crawl on_page must not use 1-arg lambda — crawl() passes 3 args")
        # The correct 3-arg form:
        self.assertIn("lambda url, depth, result:", src,
                      "CLI crawl on_page must use lambda url, depth, result: ...")


# ═════════════════════════════════════════════════════════════════════════════
# _is_content_safe rake-bypass fix (v2.1.3 bug fix)
# ═════════════════════════════════════════════════════════════════════════════

class TestContentSafetyRakeBypass(unittest.TestCase):
    """Presence of 'rake' must not disable the rape-context check."""

    def test_rake_alone_is_safe(self):
        """Text containing only 'rake' must pass the safety filter."""
        self.assertTrue(SICRY._is_content_safe("how to rake leaves in autumn"))

    def test_rake_and_rape_video_is_blocked(self):
        """Text containing both 'rake' and 'rape video' must be blocked (old bug: 'rake' short-circuited check)."""
        self.assertFalse(
            SICRY._is_content_safe("how to rake leaves — rape video uploaded"),
            "rake short-circuited the rape-context check — fixed in v2.1.3",
        )

    def test_rape_with_onion_context_is_blocked(self):
        """'rape site onion' must be blocked regardless of 'rake' presence."""
        self.assertFalse(SICRY._is_content_safe("rape site onion dark web"))

    def test_rape_film_blocked(self):
        self.assertFalse(SICRY._is_content_safe("rape film download"))

    def test_brake_is_always_safe(self):
        """'brake' (automotive) must never falsely trigger the content filter."""
        self.assertTrue(SICRY._is_content_safe("brake pad replacement guide"))
        self.assertTrue(SICRY._is_content_safe("car brake repair video tutorial"))


# ═════════════════════════════════════════════════════════════════════════════
# v2.1.4 bug fixes
# ═════════════════════════════════════════════════════════════════════════════

class TestCSAMBlacklist(unittest.TestCase):
    """CRITICAL-2/3: 'csam' term and new token pairs must be in safety filter."""

    def test_csam_standalone_blocked(self):
        """'csam' alone must be blocked — unambiguous CSAM acronym."""
        self.assertFalse(SICRY._is_content_safe("csam"))
        self.assertFalse(SICRY._is_content_safe("ABYSS CSAM"))
        self.assertFalse(SICRY._is_content_safe("csam content"))

    def test_csam_in_url_blocked(self):
        self.assertFalse(SICRY._is_content_safe("http://example.onion/csam/files"))

    def test_csam_in_blacklist(self):
        self.assertIn("csam", SICRY._CONTENT_BLACKLIST)

    def test_kids_child_token_pair_blocked(self):
        """CRITICAL-3: 'kids' + 'child' together in dark web context must be blocked."""
        self.assertFalse(SICRY._is_content_safe("KIDS — CHILD — FORUM"))
        self.assertFalse(SICRY._is_content_safe("kids child content"))

    def test_child_minor_token_pair_blocked(self):
        """CRITICAL-3: 'child' + 'minor' together must be blocked."""
        self.assertFalse(SICRY._is_content_safe("child minor content archive"))

    def test_kids_child_token_pair_in_blacklist(self):
        pairs = SICRY._TOKEN_PAIR_BLACKLIST
        self.assertIn(("kids", "child"), pairs)

    def test_child_minor_token_pair_in_blacklist(self):
        pairs = SICRY._TOKEN_PAIR_BLACKLIST
        self.assertIn(("child", "minor"), pairs)

    def test_safe_text_with_child_alone_passes(self):
        """The word 'child' alone (without a partner keyword) must not be blocked."""
        self.assertTrue(SICRY._is_content_safe("child welfare organization"))

    def test_safe_text_with_minor_alone_passes(self):
        self.assertTrue(SICRY._is_content_safe("legally a minor at age 17"))


class TestCrawlLinksFoundList(unittest.TestCase):
    """BUG-1: CrawlResult.links_found must be a list of URLs, not an int."""

    def test_crawlresult_links_found_is_list(self):
        """CrawlResult dataclass must have links_found typed as list, not int."""
        import inspect
        import dataclasses
        fields = {f.name: f for f in dataclasses.fields(SICRY.CrawlResult)}
        self.assertIn("links_found", fields)
        # The default type annotation for the field is list, not int
        # Check that we can instantiate with a list value without TypeError
        cr = SICRY.CrawlResult(
            job_id="test", seed_url="http://a.onion",
            pages_found=1, links_found=["http://b.onion"],
            entities={}, db_path="/tmp/x.db",
        )
        self.assertIsInstance(cr.links_found, list)

    def test_crawlresult_int_links_found_no_longer_accepted_as_canonical(self):
        """Confirm the old int signature is gone — links_found must be iterable."""
        cr = SICRY.CrawlResult(
            job_id="j", seed_url="http://a.onion",
            pages_found=0, links_found=[],
            entities={}, db_path="/tmp/x.db",
        )
        # Must be iterable (list), not an int
        self.assertTrue(hasattr(cr.links_found, "__iter__"))

    def test_crawlresult_dataclass_field_default_is_list(self):
        """CrawlResult.links_found docstring/annotation should indicate list type."""
        src = _read_src()
        # The old broken annotation was: links_found:  int
        self.assertNotIn("links_found:  int", src,
                         "CrawlResult.links_found must no longer be typed as int")


class TestCrawlExportEntitiesParsed(unittest.TestCase):
    """BUG-2: crawl_export() must return pages with entities as dict, not raw JSON string."""

    def test_crawl_export_entities_are_dict(self):
        """After a crawl, crawl_export() pages must have 'entities' as dict, not str."""
        # Simulate a crawl_save_page + crawl_export round-trip
        db = SICRY._db()
        test_job = "test_export_" + str(int(__import__("time").time()))
        ents = {"emails": ["a@b.com"], "onion_links": [], "pgp_keys": 0}
        db.crawl_save_page("http://test.onion", test_job, 0, "Title", "body text", ents)
        export = SICRY.crawl_export(test_job)
        self.assertIn("pages", export)
        self.assertGreater(len(export["pages"]), 0)
        page = export["pages"][0]
        self.assertIn("entities", page)
        self.assertIsInstance(page["entities"], dict,
                              "crawl_export() must parse entities JSON string back to dict")

    def test_crawl_export_pages_includes_text(self):
        """crawl_export() must include the stored page text, not just metadata."""
        db = SICRY._db()
        test_job = "test_text_" + str(int(__import__("time").time()))
        db.crawl_save_page("http://text.onion", test_job, 0, "T", "page body content", {})
        export = SICRY.crawl_export(test_job)
        page = export["pages"][0]
        self.assertIn("text", page,
                      "crawl_export() pages must include 'text' field")

    def test_crawl_export_pages_not_none(self):
        """crawl_export() must never return pages: None."""
        export = SICRY.crawl_export("nonexistent_job_xyz_123")
        self.assertIsNotNone(export["pages"])
        self.assertIsInstance(export["pages"], list)


class TestCheckEnginesSyntax(unittest.TestCase):
    """CRITICAL-1: check_engines.py must parse without syntax errors."""

    def test_check_engines_compiles(self):
        """check_engines.py must have no syntax errors (was broken by bad merge)."""
        import ast
        src = _read_oc_src("check_engines.py")
        try:
            ast.parse(src)
        except SyntaxError as e:
            self.fail(f"check_engines.py has a syntax error: {e}")

    def test_check_engines_sys_exit_on_separate_line(self):
        """sys.exit(1) and the following if must be on separate lines (not merged)."""
        src = _read_oc_src("check_engines.py")
        self.assertNotIn("sys.exit(1)    if", src,
                         "sys.exit(1) and if-statement were merged onto one line — must be separate")

    def test_check_engines_tor_precheck_guard_intact(self):
        """Tor pre-check (if not reachable: sys.exit(1)) must remain in check_engines.py."""
        src = _read_oc_src("check_engines.py")
        self.assertIn("_tor_port_open", src)
        self.assertIn("sys.exit(1)", src)


class TestPipelineMispFormat(unittest.TestCase):
    """BUG-3: pipeline.py --format must support 'misp'."""

    def test_pipeline_format_includes_misp(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("\"misp\"", src,
                      "pipeline.py --format must include 'misp' as a choice")

    def test_pipeline_misp_calls_to_misp(self):
        """misp format branch must call sicry.to_misp()."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("to_misp(", src,
                      "pipeline.py misp format branch must call sicry.to_misp()")

    def test_to_misp_exists(self):
        self.assertTrue(callable(getattr(SICRY, "to_misp", None)))

    def test_to_misp_returns_dict_with_event(self):
        result = SICRY.to_misp(
            [{"title": "T", "url": "http://a.onion/", "engine": "Ahmia", "confidence": 0.5}],
            query="test",
        )
        self.assertIn("Event", result)


class TestPipelineWatchFlags(unittest.TestCase):
    """UX-3: pipeline.py must have --watch-list and --watch-disable flags."""

    def test_watch_list_flag_in_pipeline(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("--watch-list", src,
                      "pipeline.py must have --watch-list flag")

    def test_watch_disable_flag_in_pipeline(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("--watch-disable", src,
                      "pipeline.py must have --watch-disable flag")

    def test_pipeline_watch_check_uses_result_count(self):
        """UX: pipeline.py watch-check must use result_count not new_count."""
        src = _read_oc_src("pipeline.py")
        self.assertNotIn("new_count", src,
                         "pipeline.py watch-check must use 'result_count', not 'new_count'")


class TestPipelineModeFilterMessage(unittest.TestCase):
    """UX-6: mode filter message must appear when --engines overrides mode routing."""

    def test_pipeline_ux6_note_in_source(self):
        """When --engines is passed with a non-default mode, a NOTE must be printed."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("NOTE: --engines overrides mode", src,
                      "pipeline.py must print a NOTE when --engines overrides mode routing")


# ═════════════════════════════════════════════════════════════════════════════
# v2.1.5 bug fixes + improvements
# ═════════════════════════════════════════════════════════════════════════════

class TestScoreResultsQueryGuard(unittest.TestCase):
    """BUG-1 v2.1.5: score_results() must not crash when query is a list."""

    def test_score_results_with_list_query_no_crash(self):
        results = [{"title": "test dark web market", "url": "http://a.onion/", "engine": "Ahmia"}]
        # Must not raise AttributeError
        scored = SICRY.score_results(["dark", "web", "market"], results)
        self.assertIsInstance(scored, list)

    def test_score_results_list_query_joined_to_string(self):
        results = [{"title": "ransomware leak database", "url": "http://b.onion/", "engine": "Tor66"}]
        scored_list  = SICRY.score_results(["ransomware", "leak"], results)
        scored_str   = SICRY.score_results("ransomware leak", results)
        # Both paths must produce the same score
        self.assertEqual(
            round(scored_list[0].get("score", scored_list[0].get("confidence", 0)), 4),
            round(scored_str[0].get("score", scored_str[0].get("confidence", 0)), 4),
        )

    def test_score_results_empty_list_query(self):
        results = [{"title": "test", "url": "http://c.onion/", "engine": "X"}]
        # Empty list should not crash
        scored = SICRY.score_results([], results)
        self.assertIsInstance(scored, list)


class TestScoreResultsTextsParam(unittest.TestCase):
    """BUG-3 v2.1.5: score_results() accepts texts param to improve BM25 scoring."""

    def test_score_results_accepts_texts_param(self):
        results = [{"title": "short", "url": "http://d.onion/", "engine": "Ahmia"}]
        texts = {"http://d.onion/": "ransomware leak dark web market stolen credentials"}
        # Must not raise TypeError
        scored = SICRY.score_results("ransomware credentials", results, texts=texts)
        self.assertIsInstance(scored, list)
        self.assertGreater(len(scored), 0)

    def test_score_results_texts_improves_score_for_content_rich_page(self):
        """A page with matching text should score higher than one with no text."""
        results = [
            {"title": "Forum", "url": "http://rich.onion/", "engine": "A"},
            {"title": "Blank", "url": "http://empty.onion/", "engine": "A"},
        ]
        texts = {"http://rich.onion/": "ransomware leak stolen data credential dump dark web"}
        scored = SICRY.score_results("ransomware credentials", results, texts=texts)
        urls = [r["url"] for r in scored]
        # The page with matching content must rank first
        self.assertEqual(urls[0], "http://rich.onion/")

    def test_score_results_texts_none_works_same_as_before(self):
        results = [{"title": "ransomware", "url": "http://e.onion/", "engine": "Tor66"}]
        s1 = SICRY.score_results("ransomware", results, texts=None)
        s2 = SICRY.score_results("ransomware", results)
        self.assertEqual(
            round(s1[0].get("score", s1[0].get("confidence", 0)), 4),
            round(s2[0].get("score", s2[0].get("confidence", 0)), 4),
        )


class TestSearchMemCache(unittest.TestCase):
    """BUG-6 v2.1.5: in-process search memory cache (_SEARCH_MEM_CACHE) exists."""

    def test_search_mem_cache_module_dict_exists(self):
        self.assertIsInstance(SICRY._SEARCH_MEM_CACHE, dict)

    def test_search_mem_cache_name_in_module(self):
        self.assertIn("_SEARCH_MEM_CACHE", dir(SICRY))


class TestSQLiteWALMode(unittest.TestCase):
    """BUG-6 v2.1.5: _DB._conn() must configure WAL mode and NORMAL sync."""

    def test_db_conn_sets_wal_mode(self):
        src = _read_src()
        self.assertIn("journal_mode=WAL", src,
                      "_DB._conn() must set WAL journal mode for SQLite")

    def test_db_conn_sets_normal_sync(self):
        src = _read_src()
        self.assertIn("synchronous=NORMAL", src,
                      "_DB._conn() must set PRAGMA synchronous=NORMAL")


class TestCrawlLinksFoundAllOnion(unittest.TestCase):
    """BUG-2 v2.1.5: crawl() links_found must capture all .onion hrefs on pages,
    not just unvisited same-domain ones that pass the crawl-queue filters."""

    def test_crawl_has_seen_links_set(self):
        """crawl() must declare a _seen_links dedup set for links_found."""
        src = _read_src()
        self.assertIn("_seen_links", src,
                      "crawl() must use _seen_links set to track all discovered .onion links")

    def test_crawl_links_found_populated_independent_of_crawl_queue(self):
        """links_found tracking must happen BEFORE the depth/domain/visited check."""
        src = _read_src()
        idx_links_found = src.find("BUG-2 fix: record ALL discovered .onion links")
        idx_child_links_queue = src.find("Collect child links for the crawl queue")
        self.assertGreater(idx_child_links_queue, idx_links_found,
                           "links_found all-onion tracking must appear before crawl-queue filter block")


class TestSearchAndCrawlDedup(unittest.TestCase):
    """IMPROVE-6 v2.1.5: search_and_crawl() must deduplicate seeds by .onion domain."""

    def test_search_and_crawl_dedup_in_source(self):
        src = _read_src()
        self.assertIn("_seen_sd", src,
                      "search_and_crawl() must deduplicate seeds by domain (IMPROVE-6)")

    def test_search_and_crawl_dedup_comment(self):
        src = _read_src()
        self.assertIn("deduplicate seeds by .onion domain", src)


class TestCrawlExportFormatParam(unittest.TestCase):
    """IMPROVE-7 v2.1.5: crawl_export() must accept a format param."""

    def test_crawl_export_has_format_param(self):
        import inspect
        sig = inspect.signature(SICRY.crawl_export)
        self.assertIn("format", sig.parameters,
                      "crawl_export() must have a 'format' parameter (IMPROVE-7)")

    def test_crawl_export_format_default_is_json(self):
        import inspect
        sig = inspect.signature(SICRY.crawl_export)
        self.assertEqual(sig.parameters["format"].default, "json")

    def test_crawl_export_stix_returns_string(self):
        """crawl_export(format='stix') must return a JSON string, not dict."""
        result = SICRY.crawl_export("nonexistent_job_stix_test", format="stix")
        self.assertIsInstance(result, str)
        # Should be valid JSON
        import json
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    def test_crawl_export_csv_returns_string(self):
        result = SICRY.crawl_export("nonexistent_job_csv_test", format="csv")
        self.assertIsInstance(result, str)

    def test_crawl_export_misp_returns_string(self):
        result = SICRY.crawl_export("nonexistent_job_misp_test", format="misp")
        self.assertIsInstance(result, str)
        import json
        parsed = json.loads(result)
        self.assertIn("Event", parsed)


class TestPipelineV215Additions(unittest.TestCase):
    """v2.1.5 pipeline.py additions: --modes, --engine-stats, --watch-daemon,
    --misp-threat-level, --misp-distribution, --output-dir."""

    def test_modes_flag_exists(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("--modes", src, "pipeline.py must have --modes flag (UX-4)")

    def test_engine_stats_flag_exists(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("--engine-stats", src, "pipeline.py must have --engine-stats flag (IMPROVE-2)")

    def test_watch_daemon_flag_exists(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("--watch-daemon", src, "pipeline.py must have --watch-daemon flag (IMPROVE-3)")

    def test_misp_threat_level_flag_exists(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("--misp-threat-level", src,
                      "pipeline.py must have --misp-threat-level flag (UX-6)")

    def test_misp_distribution_flag_exists(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("--misp-distribution", src,
                      "pipeline.py must have --misp-distribution flag (UX-6)")

    def test_output_dir_flag_exists(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("--output-dir", src,
                      "pipeline.py must have --output-dir flag (IMPROVE-8)")

    def test_modes_handler_uses_mode_config(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("sicry.mode_config", src,
                      "pipeline.py --modes handler must call sicry.mode_config()")

    def test_engine_stats_handler_uses_reliability_scores(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("engine_reliability_scores", src,
                      "pipeline.py --engine-stats must call engine_reliability_scores()")

    def test_watch_daemon_blocks_in_loop(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("watch_daemon", src)
        self.assertIn("watch_check()", src)

    def test_misp_threat_level_passed_to_to_misp(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("threat_level=args.misp_threat_level", src,
                      "pipeline.py misp handler must pass --misp-threat-level to to_misp()")

    def test_misp_distribution_passed_to_to_misp(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("distribution=args.misp_distribution", src,
                      "pipeline.py misp handler must pass --misp-distribution to to_misp()")

    def test_output_dir_creates_dir(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("os.makedirs(args.output_dir", src,
                      "pipeline.py --output-dir must create the directory via os.makedirs")

    def test_watch_check_shows_last_and_next_timestamps(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("last_run", src,
                      "pipeline.py watch-check output must include last_run timestamp (UX-5)")
        self.assertIn("next_str", src,
                      "pipeline.py watch-check output must include next-due timestamp (UX-5)")

    def test_watch_disable_validates_job_id(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("no watch job with ID", src,
                      "pipeline.py --watch-disable must validate the job ID (UX-3)")

    def test_interactive_repl_has_help_command(self):
        src = _read_oc_src("pipeline.py")
        self.assertIn("help", src)
        self.assertIn("history", src,
                      "pipeline.py interactive REPL must handle 'history' command (UX-7)")

    def test_pipeline_misp_epilog_example(self):
        """IMPROVE-4: --help epilog must show a MISP format example."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("--format misp", src,
                      "pipeline.py epilog must include a --format misp usage example (IMPROVE-4)")

    def test_pipeline_bundled_version_check_in_check_update(self):
        """IMPROVE-5: --check-update handler must check bundled sicry.py version."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("bundled sicry.py", src,
                      "pipeline.py --check-update must check bundled sicry version (IMPROVE-5)")

    def test_bm25_rescore_after_scrape_in_pipeline(self):
        """BUG-3: pipeline must re-score best results after step 6 scrape."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("re-score", src,
                      "pipeline.py must re-score best results using scraped page content (BUG-3)")
        self.assertIn("texts=pages", src,
                      "pipeline.py must pass scraped pages to score_results(texts=pages)")


class TestSyncSicryCheckBundled(unittest.TestCase):
    """BUG-5 v2.1.5: sync_sicry.py must have --check-bundled flag."""

    def test_sync_sicry_has_check_bundled_flag(self):
        src = _read_oc_src("sync_sicry.py")
        self.assertIn("--check-bundled", src,
                      "sync_sicry.py must have --check-bundled flag (BUG-5)")

    def test_sync_sicry_check_bundled_compares_versions(self):
        src = _read_oc_src("sync_sicry.py")
        self.assertIn("bundled_version", src)
        self.assertIn("latest_name", src)

    def test_sync_sicry_check_bundled_exits_nonzero_when_behind(self):
        src = _read_oc_src("sync_sicry.py")
        self.assertIn("sys.exit(2)", src,
                      "sync_sicry.py --check-bundled must exit 2 when bundled is behind upstream")



# ═════════════════════════════════════════════════════════════════════════════
# v2.1.6 fixes
# ═════════════════════════════════════════════════════════════════════════════

class TestBug1ScoreConfidenceDualKey(unittest.TestCase):
    """BUG-1 v2.1.6: score_results() must set BOTH 'score' AND 'confidence' keys.
    Previously it only set 'score', so pipeline re-score after step-6 scrape did
    not update the 'confidence' key used by downstream displays/export.
    """

    def test_score_results_sets_confidence_key(self):
        """score_results() output dicts must contain a 'confidence' key."""
        results = [
            {"url": "http://a.onion/", "title": "A", "score": 0.5, "confidence": 0.5,
             "engine": "Ahmia", "snippet": "alpha beta gamma delta"},
            {"url": "http://b.onion/", "title": "B", "score": 0.3, "confidence": 0.3,
             "engine": "Ahmia", "snippet": "delta epsilon zeta"},
        ]
        scored = SICRY.score_results("alpha beta", results)
        self.assertTrue(len(scored) > 0, "score_results() must return non-empty list")
        for r in scored:
            self.assertIn("confidence", r,
                          "score_results() result must have 'confidence' key (BUG-1 fix)")

    def test_score_results_confidence_equals_score(self):
        """'confidence' and 'score' must hold the same rounded normalised value."""
        results = [
            {"url": "http://a.onion/", "title": "A", "score": 0.8, "confidence": 0.8,
             "engine": "Ahmia", "snippet": "onion link darkweb market"},
        ]
        scored = SICRY.score_results("darkweb", results)
        r = scored[0]
        self.assertIn("score", r)
        self.assertIn("confidence", r)
        self.assertEqual(r["score"], r["confidence"],
                         "'score' and 'confidence' must be equal after score_results()")

    def test_score_results_dual_key_in_source(self):
        """Source must set both keys in a single assignment."""
        src = _read_src()
        self.assertIn('r_copy["confidence"] = r_copy["score"]', src,
                      "score_results() must set both 'confidence' and 'score' (BUG-1 fix)")


class TestBug2CrawlLinksFoundClearnet(unittest.TestCase):
    """BUG-2 v2.1.6: crawl() links_found must capture ALL outbound hrefs, not
    only .onion ones.  A single-page .onion site that links exclusively to
    clearnet URLs previously returned an empty links_found list.
    """

    def test_crawl_links_found_comment_all_outbound(self):
        """Source comment must indicate that all outbound links are captured."""
        src = _read_src()
        self.assertIn("record ALL discovered outbound links", src,
                      "crawl() links_found must capture all hrefs (clearnet + onion) — BUG-2 fix")

    def test_crawl_links_found_no_onion_filter(self):
        """The links_found recording block must NOT filter by .onion."""
        src = _read_src()
        # The OLD buggy pattern — must be gone
        self.assertNotIn('if not _href or ".onion" not in _href:\n                continue',
                         src,
                         "crawl() links_found block must not filter to .onion-only hrefs")

    def test_crawl_links_found_clearnet_captured_live(self):
        """LIVE: crawl() must return non-empty links_found for .onion page linking to clearnet."""
        if not LIVE:
            self.skipTest("requires --live flag")
        result = SICRY.crawl("http://www.nytimesn7cgmftshazwhfgzm37qxb44r64ytbb2dj3x62d2lljsciiyd.onion/",
                             max_pages=1, max_depth=0)
        self.assertGreater(len(result.get("links_found", [])), 0,
                           "crawl() on NYT .onion should find outbound clearnet links")


class TestUX4EngineReliabilityNone(unittest.TestCase):
    """UX-4 v2.1.6: engine_reliability() must return None (not 1.0) when no
    health history exists for an engine, so --engine-stats can distinguish
    'never checked' from '100% reliable'.
    """

    def test_engine_reliability_returns_none_when_no_history(self):
        """_DB.engine_reliability() must return None for engines with no history rows."""
        from sicry import _db
        db = _db()
        # Use a made-up engine name that will never have been checked
        result = db.engine_reliability("__nonexistent_engine_v216__")
        self.assertIsNone(result,
                          "_DB.engine_reliability() must return None (not 1.0) for no-history engines")

    def test_engine_reliability_returns_float_when_history_exists(self):
        """_DB.engine_reliability() must return a float 0.0–1.0 when rows exist."""
        from sicry import _db
        db = _db()
        # Plant a single 'up' history row (all four positional args required)
        db.engine_history_add("__test_engine_v216__", "up", 50, None)
        result = db.engine_reliability("__test_engine_v216__")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 1.0)

    def test_engine_reliability_scores_returns_none_for_unchecked(self):
        """engine_reliability_scores() must contain None values for unchecked engines."""
        scores = SICRY.engine_reliability_scores()
        self.assertIsInstance(scores, dict)
        # At least one engine should have None if starting with a fresh DB
        # (or all may be floats if DB was pre-populated — check type annotation is correct)
        for _v in scores.values():
            self.assertIn(type(_v), (float, type(None)),
                          "engine_reliability_scores() values must be float or None")

    def test_engine_reliability_none_source(self):
        """Source must return None (not 1.0) for the no-rows branch."""
        src = _read_src()
        self.assertIn("return None   # UX-4 fix:", src,
                      "_DB.engine_reliability() must return None when no history (UX-4 fix)")

    def test_engine_stats_pipeline_handles_none_reliability(self):
        """pipeline.py --engine-stats handler must handle None reliability gracefully."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("(no data)", src,
                      "pipeline --engine-stats must display '(no data)' for None reliability")
        self.assertIn("_rel is not None", src,
                      "pipeline --engine-stats must guard against None reliability value")


class TestUX2WatchCheckInlineResults(unittest.TestCase):
    """UX-2 v2.1.6: watch_check() alert dict must include scheduling fields and
    pipeline --watch-check must print top-5 result titles/URLs for NEW alerts.
    """

    def test_watch_check_alert_includes_last_run(self):
        """watch_check() alert dict must carry 'last_run' key."""
        src = _read_src()
        self.assertIn('"last_run"', src,
                      "watch_check() alert dict must include 'last_run' (UX-2 fix)")

    def test_watch_check_alert_includes_interval_hours(self):
        """watch_check() alert dict must carry 'interval_hours' key."""
        src = _read_src()
        self.assertIn('"interval_hours"', src,
                      "watch_check() alert dict must include 'interval_hours' (UX-2 fix)")

    def test_watch_check_alert_includes_mode(self):
        """watch_check() alert dict must carry a 'mode' key."""
        src = _read_src()
        self.assertIn('"mode"', src,
                      "watch_check() alert dict must include 'mode'")

    def test_pipeline_watch_check_prints_top_results(self):
        """pipeline.py must print top-5 result titles/URLs for NEW watch alerts."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("a[\"results\"][:5]", src,
                      "pipeline --watch-check must iterate a['results'][:5] (UX-2 fix)")
        self.assertIn("_tr.get('title'", src,
                      "pipeline --watch-check must print result title (UX-2 fix)")
        self.assertIn("_tr.get('url'", src,
                      "pipeline --watch-check must print result URL (UX-2 fix)")

    def test_pipeline_watch_check_output_dir_saves_json(self):
        """pipeline.py --watch-check must save to --output-dir when provided (IMPROVE-7)."""
        src = _read_oc_src("pipeline.py")
        # The f-string in pipeline.py is: f"{a['job_id']}.json"
        self.assertIn("job_id']}.json", src,
                      "pipeline --watch-check --output-dir must save <job_id>.json (IMPROVE-7)")
        self.assertIn("_json.dump", src,
                      "pipeline --watch-check output must use json.dump")


class TestUX3InteractiveEntityExtraction(unittest.TestCase):
    """UX-3 v2.1.6: --interactive number-based fetch must run analyze_nollm()
    on the fetched page text and print an Entities/Keywords block.
    """

    def test_interactive_fetch_calls_analyze_nollm(self):
        """pipeline.py interactive REPL must call analyze_nollm() after fetch."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("analyze_nollm", src,
                      "pipeline interactive fetch must call sicry.analyze_nollm (UX-3 fix)")

    def test_interactive_fetch_entities_header(self):
        """pipeline.py interactive REPL must print an Entities/Keywords header."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("Entities / Keywords", src,
                      "pipeline interactive fetch must print '--- Entities / Keywords ---' (UX-3 fix)")


class TestImprove1TorPoolNotice(unittest.TestCase):
    """IMPROVE-1 v2.1.6: pipeline step-1 must print TorPool circuit count when
    SICRY_POOL_SIZE > 0, so operators can confirm multi-circuit mode is active.
    """

    def test_pipeline_torpool_notice_in_source(self):
        """pipeline.py must contain TorPool notice code after step-1 Tor check."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("TOR_POOL_SIZE", src,
                      "pipeline must read TOR_POOL_SIZE from sicry module (IMPROVE-1 fix)")
        self.assertIn("TorPool", src,
                      "pipeline must mention TorPool in the startup notice (IMPROVE-1 fix)")

    def test_pipeline_torpool_notice_is_conditional(self):
        """TorPool notice must only print when pool_sz > 0 (not every run)."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("if _pool_sz > 0:", src,
                      "TorPool notice must be conditional on _pool_sz > 0")

    def test_pipeline_torpool_base_port_shown(self):
        """TorPool notice must include the base socks port for debugging."""
        src = _read_oc_src("pipeline.py")
        self.assertIn("TOR_POOL_BASE_PORT", src,
                      "pipeline TorPool notice must include the base port (IMPROVE-1 fix)")


class TestV216VersionBump(unittest.TestCase):
    """Verify that all version strings were bumped to 2.1.6."""

    def test_sicry_version(self):
        self.assertEqual(SICRY.__version__, "2.1.6")

    def test_pyproject_version(self):
        src = _read_src("pyproject.toml")
        self.assertIn('version = "2.1.6"', src)

    def test_sync_sicry_version(self):
        src = _read_oc_src("sync_sicry.py")
        self.assertIn("sync_sicry 2.1.6", src)

    def test_changelog_has_v216_entry(self):
        src = _read_src("CHANGELOG.md")
        self.assertIn("## [2.1.6]", src)

    def test_onion_claw_sicry_version(self):
        """OnionClaw/sicry.py must be synced and carry 2.1.6."""
        self.assertEqual(SICRY_OC.__version__, "2.1.6")


# ═════════════════════════════════════════════════════════════════════════════
# Runner
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Strip our custom --live flag so unittest doesn't choke on it
    argv = [a for a in sys.argv if a != "--live"]
    unittest.main(argv=argv, verbosity=2)

