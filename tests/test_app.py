"""Unit tests for the parsing and search rules. Run: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_tmp = tempfile.mkdtemp()
os.environ["CACHE_FILE"] = os.path.join(_tmp, "details.json")
os.environ["PREFS_FILE"] = os.path.join(_tmp, "prefs.json")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app  # noqa: E402

# Shape copied from ABB's search page (titles/sizes made up).
SEARCH_PAGE = """
<div class="post"><div class="postTitle"><h2><a href="/abss/book-one/" rel="bookmark">The Dawn of Yangchen - Book 1 - F. C. Yee</a></h2></div>
<p style='text-align:center;'>Posted: 5 Jan 2026<br />Format: <span>MP3</span> / Bitrate: <span>256 Kbps</span><br />File Size: <span>307.66</span> MBs</p>
</div></div><div class="post"><div class="postTitle"><h2><a href="/abss/legacy/" rel="bookmark">The Legacy of Yangchen - F.C.Yee</a></h2></div>
<p>Posted: 29 Jul 2024<br />Format: <span>M4B</span> / Bitrate: <span>64 Kbps</span><br />File Size: <span>1.2</span> GBs</p>
</div></div><div class="navigation"></div>
"""
DETAIL_PAGE = """<table><tr><td>Info Hash:</td><td>ABCDEF0123456789ABCDEF0123456789ABCDEF01</td></tr>
<tr><td>Tracker:</td><td>udp://tracker.example.org:6969/announce</td></tr>
<tr><td>Combined File Size:</td><td>307.66 MBs</td></tr></table>"""


class ParseTests(unittest.TestCase):
    def test_parse_search_reads_title_format_size_and_date(self):
        r = app.parse_search(SEARCH_PAGE)
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0]["title"], "The Dawn of Yangchen - Book 1 - F. C. Yee")
        self.assertEqual(r[0]["href"], app.BASE + "/abss/book-one/")
        self.assertEqual((r[0]["format"], r[0]["size"], r[0]["posted"]), ("MP3", 307660000, "5 Jan 2026"))
        self.assertEqual(r[1]["size"], 1200000000)

    def test_parse_detail_reads_hash_and_trackers(self):
        d = app.parse_detail(DETAIL_PAGE)
        self.assertEqual(d["hash"], "abcdef0123456789abcdef0123456789abcdef01")
        self.assertEqual(d["trackers"], ["udp://tracker.example.org:6969/announce"])
        self.assertIsNone(app.parse_detail("<html>no hash here</html>"))


class StrategyTests(unittest.TestCase):
    def test_clean_query_drops_edition_tags_and_punctuation(self):
        self.assertEqual(app.clean_query("Fire & Blood (HBO Tie-in Edition) George R. R. Martin"), "fire blood george r r martin")
        self.assertEqual(app.clean_query("Harry Potter and the Sorcerer's Stone"), "harry potter and the sorcerers stone")

    def test_variants_try_the_part_after_the_colon(self):
        v = app.query_variants("Avatar, the Last Airbender: The Dawn of Yangchen F. C. Yee")
        self.assertEqual(v[0], "avatar the last airbender the dawn of yangchen f c yee")
        self.assertIn("the dawn of yangchen f c yee", v)
        self.assertIn("the dawn of yangchen", v)
        self.assertLessEqual(len(v), 4)

    def test_rank_puts_the_closest_title_first(self):
        results = [{"title": "The Legacy of Yangchen - F.C.Yee"}, {"title": "The Dawn of Yangchen - Book 1 - F. C. Yee"}]
        ranked = app.rank(results, "Avatar, the Last Airbender: The Dawn of Yangchen")
        self.assertTrue(ranked[0]["title"].startswith("The Dawn"))

    def test_produced_edition_replaces_plain_readings_of_the_same_book(self):
        results = [{"title": "Threshing Day (Wing and Claw Collection) - Rebecca Yarros"},
                   {"title": "Threshing Day [Dramatized Adaptation]: The Empyrean Series - Rebecca Yarros"},
                   {"title": "Some Other Book - Someone"}]
        titles = [r["title"] for r in app.rank(results, "Threshing Day (Wing and Claw Collection) Rebecca Yarros")]
        self.assertIn("Threshing Day [Dramatized Adaptation]: The Empyrean Series - Rebecca Yarros", titles)
        self.assertNotIn("Threshing Day (Wing and Claw Collection) - Rebecca Yarros", titles)
        self.assertIn("Some Other Book - Someone", titles)

    def test_narrated_preference_keeps_the_single_narrator_reading(self):
        results = [{"title": "Threshing Day (Wing and Claw Collection) - Rebecca Yarros"},
                   {"title": "Threshing Day [Dramatized Adaptation]: The Empyrean Series - Rebecca Yarros"}]
        titles = [r["title"] for r in app.rank(results, "Threshing Day Rebecca Yarros", preference="narrated")]
        self.assertEqual(titles, ["Threshing Day (Wing and Claw Collection) - Rebecca Yarros"])

    def test_any_preference_keeps_both_editions(self):
        results = [{"title": "Threshing Day (Wing and Claw Collection) - Rebecca Yarros"},
                   {"title": "Threshing Day [Dramatized Adaptation]: The Empyrean Series - Rebecca Yarros"}]
        self.assertEqual(len(app.rank(results, "Threshing Day Rebecca Yarros", preference="any")), 2)

    def test_plain_readings_stay_when_no_produced_edition_exists(self):
        results = [{"title": "A Feast for Crows - George R. R. Martin"}]
        self.assertEqual(len(app.rank(results, "A Feast for Crows")), 1)


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        app._prefs.clear()

    def test_per_book_choice_overrides_the_default_for_that_book_only(self):
        app.set_preference("Threshing Day (Wing and Claw Collection)", "narrated")
        self.assertEqual(app.preference_for("Threshing Day (Wing and Claw Collection) Rebecca Yarros"), "narrated")
        self.assertEqual(app.preference_for("A Feast for Crows George R. R. Martin"), app.EDITION_PREFERENCE)
        results = [{"title": "Threshing Day (Wing and Claw Collection) - Rebecca Yarros"},
                   {"title": "Threshing Day [Dramatized Adaptation]: The Empyrean Series - Rebecca Yarros"}]
        titles = [r["title"] for r in app.rank(results, "Threshing Day Rebecca Yarros")]
        self.assertEqual(titles, ["Threshing Day (Wing and Claw Collection) - Rebecca Yarros"])

    def test_series_prefixed_titles_match_on_the_title_part(self):
        app.set_preference("Avatar, the Last Airbender: The Dawn of Yangchen", "any")
        self.assertEqual(app.preference_for("Avatar, the Last Airbender: The Dawn of Yangchen F. C. Yee"), "any")

    def test_invalid_preference_is_rejected(self):
        with self.assertRaises(ValueError):
            app.set_preference("Some Book", "louder")


class SearchTests(unittest.TestCase):
    def setUp(self):
        app._searches.clear()
        app._details.clear()

    def test_search_returns_magnet_items_and_rss_renders_them(self):
        pages = lambda url: DETAIL_PAGE if "/abss/" in url else SEARCH_PAGE
        with mock.patch.object(app, "fetch", side_effect=pages):
            items = app.search("The Dawn of Yangchen")
        self.assertTrue(items[0]["magnet"].startswith("magnet:?xt=urn:btih:abcdef0123456789"))
        xml = app.rss(items)
        self.assertIn('<torznab:attr name="infohash"', xml)
        self.assertIn("The Dawn of Yangchen - Book 1 - F. C. Yee [MP3]", xml)

    def test_abb_outage_returns_empty_and_is_not_cached(self):
        with mock.patch.object(app, "fetch", side_effect=OSError("HTTP 500")):
            self.assertEqual(app.search("Threshing Day"), [])
        self.assertNotIn("threshing day", app._searches)


if __name__ == "__main__":
    unittest.main()
