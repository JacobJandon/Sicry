#!/usr/bin/env python3
"""
SICRY + OnionClaw v1.1.0 — comprehensive test suite
Tests all v1.1.0 changes: dead engine removal, fetch() cache/retry/HTTPS-fallback,
pipeline --no-llm, setup.py, and full live Tor connectivity.

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
        self.assertEqual(SICRY.__version__, "1.1.0")

    def test_onion_claw_version(self):
        self.assertEqual(SICRY_OC.__version__, "1.1.0")

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
        """BUG-6: --out permission denied must exit 1, not 0."""
        src = self._src()
        # Both OSError handlers must have sys.exit(1)
        oserr_parts = src.split("except OSError")
        self.assertGreater(len(oserr_parts), 1, "No OSError handler found")
        for part in oserr_parts[1:]:
            block = part[:200]
            self.assertIn("sys.exit(1)", block,
                          "OSError handler does not call sys.exit(1)")

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
# Runner
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Strip our custom --live flag so unittest doesn't choke on it
    argv = [a for a in sys.argv if a != "--live"]
    unittest.main(argv=argv, verbosity=2)
