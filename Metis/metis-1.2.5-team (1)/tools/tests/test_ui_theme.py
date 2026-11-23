import http.cookiejar
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def lum(hexcol):
    h = hexcol.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (text token, background token): every pairing the stylesheet actually uses for text
PAIRS = [("fg", "bg"), ("fg", "surface"), ("fg", "panel"), ("fg", "soft"), ("fg", "hover"), ("fg", "sel-bg"), ("fg", "field-bg"),
         ("muted", "bg"), ("muted", "surface"), ("muted", "panel"), ("muted", "soft"), ("muted", "field-bg"),
         ("sub", "panel"), ("link", "bg"), ("link", "panel"), ("link", "soft"), ("tag", "bg"), ("code-fg", "code-bg") if False else ("fg", "code-bg"),
         ("ok", "bg"), ("no", "bg"), ("warn", "bg"), ("ok", "panel"), ("no", "panel"), ("warn", "panel"),
         ("pill-ok-fg", "pill-ok-bg"), ("pill-no-fg", "pill-no-bg"), ("pill-warn-fg", "pill-warn-bg"), ("pill-blue-fg", "pill-blue-bg"),
         ("on-accent", "accent"), ("rail-fg", "rail-bg"), ("rail-ico", "rail-bg"), ("rail-on-fg", "rail-on"), ("sb-fg", "sb-bg"),
         ("fg", "ok-bg"), ("fg", "no-bg"), ("on-accent", "bad"), ("fg", "diff-add"), ("fg", "diff-del"), ("fg", "diff-hunk")]


class ContrastTests(unittest.TestCase):
    def test_every_text_pairing_reaches_4_5_in_both_themes(self):
        for name, tokens in (("light", C.TOKENS_LIGHT), ("dark", C.TOKENS_DARK)):
            for fg, bg in PAIRS:
                r = ratio(tokens[fg], tokens[bg])
                self.assertGreaterEqual(r, 4.5, "%s theme: %s on %s is %.2f (%s on %s)" % (name, fg, bg, r, tokens[fg], tokens[bg]))

    def test_both_themes_define_the_same_tokens(self):
        self.assertEqual(set(C.TOKENS_LIGHT), set(C.TOKENS_DARK))

    def test_body_text_is_well_above_the_minimum(self):
        self.assertGreaterEqual(ratio(C.TOKENS_LIGHT["fg"], C.TOKENS_LIGHT["bg"]), 7)
        self.assertGreaterEqual(ratio(C.TOKENS_DARK["fg"], C.TOKENS_DARK["bg"]), 7)

    def test_the_css_uses_the_tokens_it_defines(self):
        used = set(re.findall(r"var\(--([a-z0-9-]+)\)", C.CSS))
        self.assertFalse(used - set(C.TOKENS_LIGHT), "undefined tokens: %s" % (used - set(C.TOKENS_LIGHT)))


class PageTests(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        # experimental.enable: all, because these tests check that the rail can hold every screen; hiding is tested in test_features.py
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"product": {"name": "Demo"}, "experimental": {"enable": "all"}}))

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def html(self, **kw):
        return C.page(C.Ctx(self.kb, "tok", "Pat Lee", **kw), "T", "/", "<p>x</p>")

    def test_html_has_tokens_dark_block_viewport_and_breakpoint(self):
        h = self.html()
        self.assertIn(":root{--bg:#ffffff", h)
        self.assertIn("prefers-color-scheme:dark", h)
        self.assertIn(":root[data-theme=dark]", h)
        self.assertIn('<meta name="viewport" content="width=device-width,initial-scale=1">', h)
        self.assertIn("@media(max-width:800px)", h)
        self.assertIn("overflow-x:auto", h)  # tables scroll sideways on a narrow screen
        self.assertIn("min-height:40px", h)  # touch sized buttons
        self.assertIn("flex-direction:column", h)  # panes stack
        for old in ("class=\"rail\"", "class=\"lp\"" if False else "class=\"mn\"", 'class="tb"', 'class="sb"'):
            self.assertIn(old, h)  # existing class names are kept

    def test_theme_attribute_follows_the_ctx(self):
        self.assertIn('<html lang="en" data-theme="dark">', self.html(theme="dark"))
        self.assertIn('<html lang="en" data-theme="light">', self.html(theme="light"))
        self.assertIn('<html lang="en">', self.html(theme="auto"))
        self.assertIn('<html lang="en">', self.html(theme="evil\"><script>"))
        self.assertIn("Theme: dark", self.html(theme="dark"))
        self.assertIn('href="/theme?set=dark"', self.html())  # auto -> dark
        self.assertIn('href="/theme?set=light"', self.html(theme="dark"))
        self.assertIn('href="/theme?set=auto"', self.html(theme="light"))

    def test_no_javascript_anywhere_in_the_frame(self):
        h = self.html().lower()
        self.assertNotIn("<script", h)
        self.assertNotIn("javascript:", h)
        self.assertNotRegex(h, r"\son[a-z]+=")

    def test_icon_rail_scrolls_and_holds_every_new_screen(self):
        extra = [("/owners", "Owners"), ("/search", "Search"), ("/chat", "Chat"), ("/quality", "Quality"), ("/notify", "Notify"),
                 ("/federation", "Federation"), ("/suggest", "Suggest"), ("/map", "Map")]
        before = list(C.NAV_MORE)
        try:
            C.NAV_MORE.extend(x for x in extra if x not in C.NAV_MORE)
            h = self.html()
        finally:
            C.NAV_MORE[:] = before
        for href, _ in extra:
            self.assertIn('<a href="%s"' % href, h)
        self.assertRegex(C.CSS, r"\.rail \.top\{[^}]*overflow-y:auto")  # a long rail scrolls instead of overflowing the page
        self.assertRegex(C.CSS, re.compile(r"@media\(max-width:800px\)\{.*\.rail\{[^}]*flex-direction:row;[^}]*overflow-x:auto", re.S))

    def test_search_form_is_files_until_search_exists(self):
        self.assertEqual(C.SEARCH_FORM, ("/files", "find", "Search KB files")) if "/search" not in server.SCREENS else None
        old = C.SEARCH_FORM
        try:
            C.SEARCH_FORM = ("/search", "q", "Search the KB")
            h = self.html()
            self.assertIn('action="/search"', h)
            self.assertIn('name="q"', h)
        finally:
            C.SEARCH_FORM = old
        self.assertIn('action="%s"' % old[0], self.html())
        if "/search" not in server.SCREENS:
            self.assertIn('name="find"', self.html())

    def test_inline_colours_of_other_screens_follow_the_theme(self):
        self.assertIn('[style*="background:#e6ffec"]', C.CSS)


class ServerThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.kb = os.path.join(cls.d, "kb")
        write(os.path.join(cls.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"product": {"name": "Demo"}, "experimental": {"enable": "all"}}))
        cls.srv = server.serve(cls.kb, host="127.0.0.1", port=0, password=None)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.d, ignore_errors=True)

    def opener(self):
        jar = http.cookiejar.CookieJar()

        class NoFollow(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoFollow), jar

    def get(self, op, path, headers=None):
        try:
            r = op.open(urllib.request.Request(self.base + path, headers=headers or {}))
        except urllib.error.HTTPError as err:
            r = err
        return r.code, dict(r.headers), r.read().decode("utf-8", "replace")

    def token(self, op):
        return re.search(r'name="_t" value="([^"]+)"', self.get(op, "/")[2]).group(1)

    def test_get_theme_sets_a_cookie_and_goes_back(self):
        op, jar = self.opener()
        code, hdr, _ = self.get(op, "/theme?set=dark", {"Referer": self.base + "/files?find=a&m=hi"})
        self.assertEqual(code, 303)
        self.assertEqual(hdr["Location"], "/files?find=a")  # the page it came from, flash text dropped
        self.assertIn("theme=dark", hdr["Set-Cookie"])
        self.assertIn("HttpOnly", hdr["Set-Cookie"])
        self.assertIn("SameSite=Lax", hdr["Set-Cookie"])

    def test_cookie_changes_the_page_and_auto_clears_it(self):
        op, _ = self.opener()
        self.assertIn('<html lang="en">', self.get(op, "/")[2])
        self.assertIn('data-theme="dark"', self.get(op, "/", {"Cookie": "theme=dark"})[2])
        self.assertIn('data-theme="light"', self.get(op, "/", {"Cookie": "theme=light"})[2])
        self.assertNotIn("data-theme", self.get(op, "/", {"Cookie": "theme=auto"})[2].split("<style>")[0])
        self.assertNotIn("data-theme", self.get(op, "/", {"Cookie": "theme=%3Cscript%3E"})[2].split("<style>")[0])  # junk is ignored

    def test_unknown_theme_is_refused(self):
        op, _ = self.opener()
        code, hdr, body = self.get(op, "/theme?set=neon")
        self.assertEqual(code, 400)
        self.assertNotIn("Set-Cookie", hdr)
        self.assertIn("must be one of", body)

    def test_post_theme_needs_the_page_token(self):
        op, _ = self.opener()
        tok = self.token(op)
        data = urllib.parse.urlencode({"set": "light", "_t": tok}).encode()
        try:
            op.open(urllib.request.Request(self.base + "/theme", data=data))
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 303)
            self.assertIn("theme=light", err.headers["Set-Cookie"])
        bad = urllib.parse.urlencode({"set": "light", "_t": "nope"}).encode()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            op.open(urllib.request.Request(self.base + "/theme", data=bad))
        self.assertEqual(cm.exception.code, 403)

    def test_rail_renders_with_all_registered_screens(self):
        op, _ = self.opener()
        body = self.get(op, "/")[2]
        for href in server.SCREENS:
            if href in {n for n, _ in server.C.NAV_MORE}:
                self.assertIn('<a href="%s"' % href, body)
        self.assertEqual(self.get(op, "/files?find=x")[0], 200)  # the old filter still works


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"product": {"name": "Demo"}}))

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def envs(self, names, ref):
        write(os.path.join(self.kb, ".metis", "db-environments.yaml"), yaml.safe_dump({
            "reference_environment": ref,
            "environments": {n: {"databases": [{"label": "main", "engine": "postgres", "database": "d"}]} for n in names}}))

    def test_one_environment_keeps_todays_header(self):
        self.envs(["PROD"], "PROD")
        h = C.page(C.Ctx(self.kb, "t", ""), "T", "/", "")
        self.assertIn('<span class="env">PROD</span>', h)
        self.assertNotIn('action="/env"', h)

    def test_no_environment_says_so(self):
        self.assertIn('<span class="env">no environment</span>', C.page(C.Ctx(self.kb, "t", ""), "T", "/", ""))

    def test_several_environments_show_a_switcher_with_the_reference_selected(self):
        self.envs(["DEV", "UAT", "PROD"], "PROD")
        h = C.page(C.Ctx(self.kb, "t", ""), "T", "/", "")
        self.assertIn('action="/env"', h)
        self.assertIn('<option value="PROD" selected>PROD (reference)</option>', h)
        self.assertIn('<option value="DEV">DEV</option>', h)

    def test_choice_is_used_when_on_the_list_and_ignored_when_not(self):
        self.envs(["DEV", "PROD"], "PROD")
        self.assertEqual(C.current_env(C.Ctx(self.kb, "t", "", env="DEV")), "DEV")
        self.assertEqual(C.current_env(C.Ctx(self.kb, "t", "", env="HACK")), "PROD")
        self.assertEqual(C.current_env(C.Ctx(self.kb, "t", "")), "PROD")
        self.assertIn('<option value="DEV" selected>DEV</option>', C.page(C.Ctx(self.kb, "t", "", env="DEV"), "T", "/", ""))

    def test_build_and_compare_screens_use_the_chosen_environment(self):
        import views
        import screens_compare
        self.envs(["DEV", "PROD"], "PROD")
        self.assertIn("<td>DEV</td>", views.build(C.Ctx(self.kb, "t", "Pat", env="DEV"), {}))
        html = screens_compare.compare_view(C.Ctx(self.kb, "t", "Pat", env="DEV"), {})
        self.assertIn("Database environment", html)
        self.assertIn("<b>DEV</b>", html)

    def test_env_action_over_http(self):
        self.envs(["DEV", "PROD"], "PROD")
        srv = server.serve(self.kb, host="127.0.0.1", port=0, password=None)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            jar = http.cookiejar.CookieJar()

            class NoFollow(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k):
                    return None
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoFollow)
            tok = re.search(r'name="_t" value="([^"]+)"', op.open(base + "/").read().decode()).group(1)

            def post(name):
                try:
                    op.open(urllib.request.Request(base + "/env", data=urllib.parse.urlencode({"name": name, "_t": tok}).encode(),
                                                   headers={"Referer": base + "/build"}))
                except urllib.error.HTTPError as err:
                    return err
            err = post("DEV")
            self.assertEqual(err.code, 303)
            self.assertTrue(err.headers["Location"].startswith("/build"))
            self.assertIn("metis_env=DEV", err.headers["Set-Cookie"])
            self.assertEqual(post("EVIL").code, 400)
            page = op.open(urllib.request.Request(base + "/", headers={"Cookie": "metis_env=DEV"})).read().decode()
            self.assertIn('<option value="DEV" selected>', page)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
