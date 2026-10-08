"""Unit tests for bookmark_export.py (standard library only).

Run from the project root:
    python3 -m unittest discover -s tests -v
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bookmark_export as be  # noqa: E402


def chrome_micros(unix_seconds: int) -> str:
    return str((unix_seconds + be.CHROMIUM_EPOCH_OFFSET) * 1_000_000)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def chromium_fixture() -> dict:
    return {
        "version": 1,
        "checksum": "ignored",
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "Localized bar name",
                "children": [
                    {
                        "type": "url",
                        "name": "Café ☕ <b>&</b>",
                        "url": "https://example.com/?a=1&b=2",
                        "date_added": chrome_micros(1577836800),
                    },
                    {
                        "type": "folder",
                        "name": "Work",
                        "children": [
                            {"type": "url", "name": "Inner", "url": "https://example.org/"},
                        ],
                    },
                    {"type": "url", "name": "Script", "url": "javascript:void(0)"},
                ],
            },
            "other": {"type": "folder", "name": "Other", "children": []},
            "synced": {"type": "folder", "name": "Mobile", "children": []},
            "custom_root": {
                "speedDial": {
                    "type": "folder",
                    "name": "Speed Dial",
                    "children": [{"type": "url", "name": "Dial", "url": "https://example.net/"}],
                },
                "trash": {
                    "type": "folder",
                    "name": "Trash",
                    "children": [{"type": "url", "name": "Deleted", "url": "https://deleted.example/"}],
                },
                "unsorted": {"type": "folder", "name": "Unsorted", "children": []},
            },
        },
    }


def create_firefox_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT);
        CREATE TABLE moz_bookmarks (
            id INTEGER PRIMARY KEY, type INTEGER, fk INTEGER, parent INTEGER,
            position INTEGER, title TEXT, dateAdded INTEGER, lastModified INTEGER,
            guid TEXT
        );
        INSERT INTO moz_places VALUES (1, 'https://example.com/', 'Example');
        INSERT INTO moz_places VALUES (2, 'place:type=6&sort=14', 'Recent');
        INSERT INTO moz_places VALUES (3, 'https://example.org/', NULL);
        INSERT INTO moz_bookmarks VALUES (1, 2, NULL, 0, 0, '', 0, 0, 'root________');
        INSERT INTO moz_bookmarks VALUES (2, 2, NULL, 1, 0, 'menu', 0, 0, 'menu________');
        INSERT INTO moz_bookmarks VALUES (3, 2, NULL, 1, 1, 'toolbar', 0, 0, 'toolbar_____');
        INSERT INTO moz_bookmarks VALUES (4, 2, NULL, 1, 2, 'tags', 0, 0, 'tags________');
        INSERT INTO moz_bookmarks VALUES (5, 2, NULL, 1, 3, 'unfiled', 0, 0, 'unfiled_____');
        INSERT INTO moz_bookmarks VALUES (6, 2, NULL, 1, 4, 'mobile', 0, 0, 'mobile______');
        INSERT INTO moz_bookmarks VALUES (10, 2, NULL, 3, 0, 'Folder', 1577836800000000, 1577836800000000, 'g10');
        INSERT INTO moz_bookmarks VALUES (11, 1, 1, 10, 0, 'Example', 1577836800000000, 1577836800000000, 'g11');
        INSERT INTO moz_bookmarks VALUES (12, 3, NULL, 10, 1, NULL, 0, 0, 'g12');
        INSERT INTO moz_bookmarks VALUES (13, 1, 2, 3, 1, 'Smart', 0, 0, 'g13');
        INSERT INTO moz_bookmarks VALUES (14, 1, 3, 5, 0, NULL, 0, 0, 'g14');
        INSERT INTO moz_bookmarks VALUES (20, 2, NULL, 4, 0, 'reading', 0, 0, 'g20');
        INSERT INTO moz_bookmarks VALUES (21, 1, 1, 20, 0, NULL, 0, 0, 'g21');
        """
    )
    conn.commit()
    conn.close()


def make_home(root: Path) -> Path:
    home = root / "home"
    write_json(home / ".config/chromium/Default/Bookmarks", chromium_fixture())
    write_json(
        home / ".config/chromium/Local State",
        {"profile": {"info_cache": {"Default": {"name": "Work"}}}},
    )
    write_json(home / "snap/opera/current/.config/opera/Default/Bookmarks", chromium_fixture())
    # Opera-style profile stored directly in the root folder.
    write_json(home / ".config/opera-beta/Bookmarks", chromium_fixture())
    # Brave profile that exists but has no bookmark file.
    (home / "snap/brave/current/.config/BraveSoftware/Brave-Browser/Default").mkdir(parents=True)

    ff_root = home / "snap/firefox/common/.mozilla/firefox"
    profile_dir = ff_root / "abc.default"
    profile_dir.mkdir(parents=True)
    create_firefox_db(profile_dir / "places.sqlite")
    (ff_root / "profiles.ini").write_text(
        "[Profile0]\nName=default\nIsRelative=1\nPath=abc.default\nDefault=1\n"
        "[Profile1]\nName=empty\nIsRelative=1\nPath=missing.empty\n",
        encoding="utf-8",
    )
    return home


class ChromiumTimeTests(unittest.TestCase):
    def test_converts_known_date(self):
        self.assertEqual(be.chromium_time(chrome_micros(1577836800)), 1577836800)

    def test_invalid_values_give_none(self):
        for value in (None, "", "0", "abc", "-5"):
            self.assertIsNone(be.chromium_time(value))


class ChromiumReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name) / "Default"
        write_json(self.profile / "Bookmarks", chromium_fixture())
        self.source = be.Source("opera", "native", "Default", "", self.profile)

    def test_roots_titles_and_order(self):
        result = be.read_chromium(self.source)
        titles = [root.title for root in result.roots]
        self.assertEqual(titles, ["Bookmarks bar", "Speed Dial"])
        self.assertTrue(result.roots[0].toolbar)
        self.assertFalse(result.roots[1].toolbar)

    def test_trash_is_skipped_and_reported(self):
        result = be.read_chromium(self.source)
        self.assertEqual(result.skipped, {"root:custom_root/trash": 1})
        self.assertNotIn("https://deleted.example/", be.collect_urls(result.roots))

    def test_counts_and_dates(self):
        result = be.read_chromium(self.source)
        stats = be.count_tree(result.roots)
        self.assertEqual(stats["bookmarks"], 4)
        self.assertEqual(stats["non_http_urls"], 1)
        first = result.roots[0].children[0]
        self.assertEqual(first.added, 1577836800)


class FirefoxReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name) / "p.default"
        self.profile.mkdir()
        create_firefox_db(self.profile / "places.sqlite")
        self.source = be.Source("firefox", "native", "default", "", self.profile)

    def test_tree_tags_and_skips(self):
        result = be.read_firefox(self.source)
        titles = [root.title for root in result.roots]
        self.assertEqual(titles, ["Bookmarks Toolbar", "Other Bookmarks"])
        self.assertTrue(result.roots[0].toolbar)
        self.assertEqual(result.skipped, {"place_queries": 1})

        folder = result.roots[0].children[0]
        self.assertEqual(folder.title, "Folder")
        self.assertEqual([c.kind for c in folder.children], ["url", "separator"])
        self.assertEqual(folder.children[0].tags, ["reading"])
        self.assertEqual(folder.children[0].added, 1577836800)

    def test_untitled_bookmark_uses_url(self):
        result = be.read_firefox(self.source)
        untitled = result.roots[1].children[0]
        self.assertEqual(untitled.title, "https://example.org/")

    def test_tag_entries_are_not_exported_as_bookmarks(self):
        result = be.read_firefox(self.source)
        self.assertEqual(be.count_tree(result.roots)["bookmarks"], 2)

    def test_original_database_is_untouched(self):
        before = (self.profile / "places.sqlite").read_bytes()
        be.read_firefox(self.source)
        self.assertEqual((self.profile / "places.sqlite").read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.profile.iterdir()), ["places.sqlite"])


class HtmlTests(unittest.TestCase):
    def test_round_trip_with_special_characters(self):
        roots = [
            be.Node(
                "folder",
                title="Bar & <co>",
                toolbar=True,
                children=[
                    be.Node("url", title='Say "hi" <b>', url="https://x.example/?a=1&b=2", tags=["a", "b"]),
                    be.Node("separator"),
                    be.Node("url", title="Entities", url="https://x.example/?q=&amp;"),
                ],
            )
        ]
        text = be.render_html(roots)
        self.assertEqual(be.verify_html(text, roots), [])
        self.assertIn('PERSONAL_TOOLBAR_FOLDER="true"', text)
        self.assertIn('TAGS="a,b"', text)
        self.assertIn("<HR>", text)

    def test_verification_detects_changes(self):
        roots = [be.Node("folder", title="F", children=[be.Node("url", title="A", url="https://a.example/")])]
        text = be.render_html(roots).replace("https://a.example/", "https://b.example/")
        self.assertTrue(be.verify_html(text, roots))


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = make_home(Path(self.tmp.name))

    def test_finds_all_profiles(self):
        found = {(s.browser, s.install, s.profile, s.has_data) for s in be.discover(self.home)}
        self.assertIn(("firefox", "snap", "default", True), found)
        self.assertIn(("firefox", "snap", "empty", False), found)
        self.assertIn(("chromium", "native", "Default", True), found)
        self.assertIn(("opera", "snap", "Default", True), found)
        self.assertIn(("opera", "beta", "(root)", True), found)
        self.assertIn(("brave", "snap", "Default", False), found)

    def test_display_name_comes_from_local_state(self):
        chromium = [s for s in be.discover(self.home) if s.browser == "chromium"]
        self.assertEqual(chromium[0].display_name, "Work")

    def test_browser_filter(self):
        found = be.discover(self.home, ("firefox",))
        self.assertTrue(found)
        self.assertTrue(all(s.browser == "firefox" for s in found))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = make_home(Path(self.tmp.name))
        self.out = Path(self.tmp.name) / "out"

    def export(self, **kwargs):
        return be.export_all(self.home, self.out, log=lambda _msg: None, **kwargs)

    def test_full_export(self):
        manifest = self.export()
        ok = [e for e in manifest["entries"] if e["status"] == "ok"]
        self.assertEqual(len(ok), 4)  # firefox, chromium, opera snap, opera beta
        self.assertTrue(all(e["verified"] for e in ok))
        statuses = {(e["browser"], e["profile"]): e["status"] for e in manifest["entries"]}
        self.assertEqual(statuses[("brave", "Default")], "no-data")
        self.assertEqual(statuses[("firefox", "empty")], "no-data")

        names = sorted(p.name for p in self.out.iterdir())
        for expected in ("IMPORT.md", "manifest.json", "chromium_Default.html", "chromium_Default.json",
                         "firefox_default.html", "opera_Default.html", "opera_root.html"):
            self.assertIn(expected, names)
        archive = json.loads((self.out / "firefox_default.json").read_text(encoding="utf-8"))
        self.assertEqual(archive["format"], be.FORMAT_ID)
        self.assertEqual(archive["roots"][0]["title"], "Bookmarks Toolbar")

    def test_files_are_private(self):
        self.export()
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o700)
        for path in self.out.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, path.name)

    def test_refuses_non_empty_output_without_force(self):
        self.out.mkdir()
        (self.out / "keep.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(be.ExportError):
            self.export()
        self.export(force=True)
        self.assertTrue((self.out / "keep.txt").exists())

    def test_no_json_option(self):
        self.export(write_json=False)
        self.assertEqual(list(self.out.glob("*.json")), [self.out / "manifest.json"])

    def test_profile_filter_by_display_name(self):
        manifest = self.export(browsers=("chromium",), profiles=["work"])
        self.assertEqual([e["profile"] for e in manifest["entries"]], ["Default"])

    def test_nothing_found_is_an_error(self):
        empty_home = Path(self.tmp.name) / "empty-home"
        empty_home.mkdir()
        with self.assertRaises(be.ExportError):
            be.export_all(empty_home, self.out, log=lambda _msg: None)

    def test_import_guide_mentions_exported_browsers_only(self):
        self.export(browsers=("firefox",))
        guide = (self.out / "IMPORT.md").read_text(encoding="utf-8")
        self.assertIn("### Firefox", guide)
        self.assertNotIn("### Opera", guide)


class CommandLineTests(unittest.TestCase):
    def test_parser_requires_a_command(self):
        with self.assertRaises(SystemExit):
            be.build_parser().parse_args([])

    def test_export_arguments(self):
        args = be.build_parser().parse_args(
            ["export", "--out", "x", "--browser", "brave", "--browser", "edge", "--no-json"]
        )
        self.assertEqual(args.browser, ["brave", "edge"])
        self.assertTrue(args.no_json)


if __name__ == "__main__":
    unittest.main()
