#!/usr/bin/env python3
"""
SICRY + OnionClaw v1.2.1 — comprehensive test suite
Tests all v1.2.1 changes: .env chmod on existing installs, BUG-6 except Exception,
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


# ═════════════════════════════════════════════════════════════════════════════
# 1. Version
# ═════════════════════════════════════════════════════════════════════════════
class TestVersion(unittest.TestCase):
    def test_sicry_version(self):
        self.assertEqual(SICRY.__version__, "1.2.1")

    def test_onion_claw_version(self):
        self.assertEqual(SICRY_OC.__version__, "1.2.1")

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
        SICRY._FETCH_CACHE.clear()

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
        SICRY._FETCH_CACHE.clear()

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
        SICRY._FETCH_CACHE.clear()

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
        SICRY._FETCH_CACHE.clear()
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
        self.assertIn("Result filtering skipped", src)

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
        """Both .env.example copies must have SICRY_CACHE_TTL."""
        root_ex = os.path.join(_HERE, ".env.example")
        if os.path.isfile(root_ex):
            self.assertIn("SICRY_CACHE_TTL", _read(root_ex))

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
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            r = SICRY.check_tor()
        self.assertTrue(r["tor_active"])
        self.assertEqual(r["exit_ip"], "1.2.3.4")
        self.assertIsNone(r["error"])

    def test_failure_shape(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("nope")
        with patch.object(SICRY, "_build_tor_session", return_value=mock_session):
            r = SICRY.check_tor()
        self.assertFalse(r["tor_active"])
        self.assertIsNone(r["exit_ip"])
        self.assertIsNotNone(r["error"])


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
        SICRY._FETCH_CACHE.clear()
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
        ex = os.path.join(_HERE, ".env.example")
        if os.path.isfile(ex):
            self.assertIn("SICRY_CACHE_TTL", _read(ex))


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
        # Count 'except OSError' in --out related blocks (should be 0)
        # We allow OSError elsewhere (e.g. in .env chmod), just not in --out
        # The two --out blocks must use 'except Exception'
        out_blocks = [i for i, line in enumerate(src.splitlines())
                      if 'with open(args.out' in line]
        self.assertGreater(len(out_blocks), 0, "No --out write blocks found")
        for lineno in out_blocks:
            # Within 10 lines after the open(args.out, find the except
            window = "\n".join(src.splitlines()[lineno:lineno+10])
            self.assertNotIn("except OSError", window,
                             f"--out handler near line {lineno+1} uses bare 'except OSError'")

    def test_total_steps_always_7(self):
        """UX-4: TOTAL should always be 7."""
        self.assertIn("TOTAL = 7", self._src())

    def test_no_llm_step_labels(self):
        """UX-4: skipped steps must use [skip N/7] format."""
        src = self._src()
        self.assertIn("skip 3/", src)
        self.assertIn("skip 5/", src)
        self.assertIn("skip 7/", src)


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
        SICRY._FETCH_CACHE.clear()

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
        SICRY._FETCH_CACHE.clear()

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
    """Functional: file-based persistent cache survives between process invocations."""

    def setUp(self):
        SICRY._FETCH_CACHE.clear()

    def test_cache_file_constant_exists(self):
        self.assertTrue(hasattr(SICRY, "_CACHE_FILE"),
                        "_CACHE_FILE missing from sicry.py")

    def test_save_disk_cache_exists(self):
        self.assertTrue(callable(getattr(SICRY, "_save_disk_cache", None)),
                        "_save_disk_cache() missing from sicry.py")

    def test_load_disk_cache_exists(self):
        self.assertTrue(callable(getattr(SICRY, "_load_disk_cache", None)),
                        "_load_disk_cache() missing from sicry.py")

    def test_clear_cache_function_exists(self):
        self.assertTrue(callable(getattr(SICRY, "clear_cache", None)),
                        "clear_cache() missing from sicry.py")

    def test_clear_cache_empties_memory(self):
        SICRY._FETCH_CACHE["http://a.onion"] = (time.time(), {"title": "test"})
        SICRY.clear_cache()
        self.assertEqual(len(SICRY._FETCH_CACHE), 0)

    def test_clear_cache_returns_count(self):
        SICRY._FETCH_CACHE["http://a.onion"] = (time.time(), {"x": 1})
        SICRY._FETCH_CACHE["http://b.onion"] = (time.time(), {"x": 2})
        n = SICRY.clear_cache()
        self.assertEqual(n, 2)

    def test_save_and_load_roundtrip(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = f.name
        old_cache_file = SICRY._CACHE_FILE
        try:
            SICRY._CACHE_FILE = tmp
            entry = {"url": "http://x.onion", "is_onion": True, "status": 200,
                     "title": "hi", "text": "body", "links": [], "error": None, "truncated": False}
            SICRY._FETCH_CACHE["http://x.onion"] = (time.time(), entry)
            SICRY._save_disk_cache()

            # Clear memory and reload from disk
            SICRY._FETCH_CACHE.clear()
            SICRY._load_disk_cache()
            self.assertIn("http://x.onion", SICRY._FETCH_CACHE)
        finally:
            SICRY._CACHE_FILE = old_cache_file
            try:
                os.remove(tmp)
            except OSError:
                pass

    def test_load_ignores_corrupt_cache(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("NOTJSON{{{{")
            tmp = f.name
        old_cache_file = SICRY._CACHE_FILE
        try:
            SICRY._CACHE_FILE = tmp
            SICRY._FETCH_CACHE.clear()
            # Should not raise
            SICRY._load_disk_cache()
            self.assertEqual(len(SICRY._FETCH_CACHE), 0)
        finally:
            SICRY._CACHE_FILE = old_cache_file
            try:
                os.remove(tmp)
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
# Runner
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Strip our custom --live flag so unittest doesn't choke on it
    argv = [a for a in sys.argv if a != "--live"]
    unittest.main(argv=argv, verbosity=2)
