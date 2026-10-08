#!/usr/bin/env python3
"""Export browser bookmarks on Linux to Netscape HTML and JSON files.

Supported browsers: Firefox, Chromium, Brave, Microsoft Edge and Opera
(deb/native, snap and flatpak installs, all profiles).

The tool is strictly read-only with respect to the browsers' own files.
Firefox databases are copied to a temporary directory before they are read,
so the export also works while Firefox is running.

For every browser profile the tool writes:

* ``<browser>_<profile>.html``  Netscape bookmark file for importing
* ``<browser>_<profile>.json``  lossless archive of the exported tree

and, once per run, ``manifest.json`` and ``IMPORT.md``.

Usage:
    python3 bookmark_export.py detect
    python3 bookmark_export.py export --out DIR [--browser NAME ...]

Only the Python standard library is used (Python 3.9 or newer).
"""

from __future__ import annotations

import argparse
import configparser
import html
import json
import os
import platform
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

__version__ = "0.1.0"
FORMAT_ID = "bookmark-export/1"

BROWSERS = ("firefox", "chromium", "brave", "edge", "opera")
CHROMIUM_FAMILY = ("chromium", "brave", "edge", "opera")

CHROMIUM_EPOCH_OFFSET = 11644473600  # seconds between 1601-01-01 and 1970-01-01


class ExportError(Exception):
    """A problem that stops the export of one profile or the whole run."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """One element of a bookmark tree: a folder, a bookmark or a separator."""

    kind: str  # "folder", "url" or "separator"
    title: str = ""
    url: str = ""
    added: Optional[int] = None  # seconds since the Unix epoch
    modified: Optional[int] = None
    tags: list[str] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    toolbar: bool = False  # True for the bookmarks toolbar/bar folder

    def to_dict(self) -> dict:
        data: dict = {"type": self.kind}
        if self.kind == "url":
            data["title"] = self.title
            data["url"] = self.url
        elif self.kind == "folder":
            data["title"] = self.title
        if self.added is not None:
            data["added"] = self.added
        if self.modified is not None:
            data["modified"] = self.modified
        if self.tags:
            data["tags"] = list(self.tags)
        if self.toolbar:
            data["toolbar"] = True
        if self.kind == "folder":
            data["children"] = [child.to_dict() for child in self.children]
        return data


@dataclass
class Source:
    """One browser profile that may contain bookmarks."""

    browser: str
    install: str  # "native", "snap" or "flatpak" (plus "beta"/"developer" for Opera)
    profile: str
    display_name: str
    path: Path  # profile directory

    @property
    def store(self) -> Path:
        name = "places.sqlite" if self.browser == "firefox" else "Bookmarks"
        return self.path / name

    @property
    def has_data(self) -> bool:
        return self.store.is_file()


@dataclass
class ReadResult:
    roots: list[Node]
    skipped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def firefox_roots(home: Path) -> list[tuple[str, Path]]:
    return [
        ("native", home / ".mozilla/firefox"),
        ("xdg", home / ".config/mozilla/firefox"),
        ("snap", home / "snap/firefox/common/.mozilla/firefox"),
        ("flatpak", home / ".var/app/org.mozilla.firefox/.mozilla/firefox"),
    ]


def chromium_family_roots(home: Path) -> dict[str, list[tuple[str, Path]]]:
    return {
        "chromium": [
            ("native", home / ".config/chromium"),
            ("snap", home / "snap/chromium/common/chromium"),
            ("flatpak", home / ".var/app/org.chromium.Chromium/config/chromium"),
        ],
        "brave": [
            ("native", home / ".config/BraveSoftware/Brave-Browser"),
            ("snap", home / "snap/brave/current/.config/BraveSoftware/Brave-Browser"),
            (
                "flatpak",
                home / ".var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser",
            ),
        ],
        "edge": [
            ("native", home / ".config/microsoft-edge"),
            ("flatpak", home / ".var/app/com.microsoft.Edge/config/microsoft-edge"),
        ],
        "opera": [
            ("native", home / ".config/opera"),
            ("beta", home / ".config/opera-beta"),
            ("developer", home / ".config/opera-developer"),
            ("snap", home / "snap/opera/current/.config/opera"),
            ("flatpak", home / ".var/app/com.opera.Opera/config/opera"),
        ],
    }


PROCESS_NAMES = {
    "firefox": {"firefox", "firefox-bin"},
    "chromium": {"chromium", "chromium-browse"},
    "brave": {"brave", "brave-browser"},
    "edge": {"msedge", "microsoft-edge"},
    "opera": {"opera"},
}


def running_browsers() -> list[str]:
    """Return the browsers that currently have a running process."""
    found: set[str] = set()
    for comm_file in Path("/proc").glob("[0-9]*/comm"):
        try:
            name = comm_file.read_text().strip()
        except OSError:
            continue
        for browser, names in PROCESS_NAMES.items():
            if name in names:
                found.add(browser)
    return sorted(found)


def _firefox_profiles(root: Path) -> list[dict]:
    ini = root / "profiles.ini"
    profiles: list[dict] = []
    if not ini.is_file():
        return profiles
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(ini, encoding="utf-8")
    except (configparser.Error, OSError):
        return profiles
    for section in parser.sections():
        if not section.startswith("Profile"):
            continue
        path = parser.get(section, "Path", fallback=None)
        if not path:
            continue
        is_relative = parser.get(section, "IsRelative", fallback="1") == "1"
        profiles.append(
            {
                "name": parser.get(section, "Name", fallback=""),
                "path": root / path if is_relative else Path(path),
            }
        )
    return profiles


def _chromium_display_names(root: Path) -> dict[str, str]:
    local_state = root / "Local State"
    if not local_state.is_file():
        return {}
    try:
        state = json.loads(local_state.read_text(encoding="utf-8"))
        cache = state.get("profile", {}).get("info_cache", {})
        return {key: value.get("name", "") for key, value in cache.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def discover(home: Path, browsers: tuple[str, ...] = BROWSERS) -> list[Source]:
    """Find all browser profiles under ``home`` (whether or not they hold data)."""
    sources: list[Source] = []
    seen: set[tuple[str, Path]] = set()

    def add(source: Source) -> None:
        key = (source.browser, source.path.resolve())
        if key not in seen:
            seen.add(key)
            sources.append(source)

    if "firefox" in browsers:
        for install, root in firefox_roots(home):
            if not root.is_dir():
                continue
            for profile in _firefox_profiles(root):
                add(
                    Source(
                        "firefox",
                        install,
                        profile["name"] or profile["path"].name,
                        "",
                        profile["path"],
                    )
                )

    families = chromium_family_roots(home)
    for browser in CHROMIUM_FAMILY:
        if browser not in browsers:
            continue
        for install, root in families[browser]:
            if not root.is_dir():
                continue
            names = _chromium_display_names(root)
            try:
                children = sorted(root.iterdir())
            except OSError:
                children = []
            for child in children:
                if child.is_dir() and (
                    child.name == "Default" or child.name.startswith("Profile ")
                ):
                    add(Source(browser, install, child.name, names.get(child.name, ""), child))
            if (root / "Bookmarks").is_file():
                # Profile stored directly in the root folder.
                add(Source(browser, install, "(root)", "", root))
    return sources


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


def chromium_time(value) -> Optional[int]:
    """Convert a Chromium timestamp (microseconds since 1601) to Unix seconds."""
    try:
        micros = int(value)
    except (TypeError, ValueError):
        return None
    if micros <= 0:
        return None
    seconds = micros // 1_000_000 - CHROMIUM_EPOCH_OFFSET
    return seconds if seconds > 0 else None


CHROMIUM_ROOT_ORDER = ("bookmark_bar", "other", "synced")
CHROMIUM_ROOT_TITLES = {
    "bookmark_bar": "Bookmarks bar",
    "other": "Other bookmarks",
    "synced": "Mobile bookmarks",
    "speedDial": "Speed Dial",
    "userRoot": "User bookmarks",
    "unsorted": "Unsorted",
    "pinboard": "Pinboard",
    "workspaces_v2": "Workspaces",
}
CHROMIUM_SKIPPED_ROOTS = {"trash", "unsyncedPinboard"}


def _chromium_node(raw: dict) -> Optional[Node]:
    kind = raw.get("type")
    if kind == "url":
        return Node(
            "url",
            title=str(raw.get("name", "")),
            url=str(raw.get("url", "")),
            added=chromium_time(raw.get("date_added")),
        )
    if kind == "folder":
        node = Node(
            "folder",
            title=str(raw.get("name", "")),
            added=chromium_time(raw.get("date_added")),
            modified=chromium_time(raw.get("date_modified")),
        )
        for child in raw.get("children", []):
            converted = _chromium_node(child)
            if converted is not None:
                node.children.append(converted)
        return node
    return None


def read_chromium(source: Source) -> ReadResult:
    try:
        data = json.loads(source.store.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExportError(f"cannot read {source.store}: {exc}") from exc

    candidates: list[tuple[str, dict]] = []
    for key, raw in data.get("roots", {}).items():
        if not isinstance(raw, dict):
            continue
        if "children" in raw:
            candidates.append((key, raw))
        else:
            # Opera nests additional roots (speed dial and others) one level down.
            for sub_key, sub_raw in raw.items():
                if isinstance(sub_raw, dict) and "children" in sub_raw:
                    candidates.append((f"{key}/{sub_key}", sub_raw))

    def sort_key(item: tuple[str, dict]) -> tuple[int, str]:
        key = item[0]
        return (CHROMIUM_ROOT_ORDER.index(key) if key in CHROMIUM_ROOT_ORDER else 99, key)

    result = ReadResult(roots=[])
    for key, raw in sorted(candidates, key=sort_key):
        tail = key.rsplit("/", 1)[-1]
        node = _chromium_node(raw)
        if node is None or not node.children:
            continue
        if tail in CHROMIUM_SKIPPED_ROOTS:
            count = len(collect_urls([node]))
            if count:
                result.skipped[f"root:{key}"] = count
            continue
        node.title = CHROMIUM_ROOT_TITLES.get(tail) or node.title or tail
        node.toolbar = key == "bookmark_bar"
        result.roots.append(node)
    return result


FIREFOX_ROOT_TITLES = {
    "toolbar_____": "Bookmarks Toolbar",
    "menu________": "Bookmarks Menu",
    "unfiled_____": "Other Bookmarks",
    "mobile______": "Mobile Bookmarks",
}
FIREFOX_ROOT_ORDER = ("toolbar_____", "menu________", "unfiled_____", "mobile______")
FIREFOX_TREE_ROOT = "root________"
FIREFOX_TAGS_ROOT = "tags________"

_FIREFOX_QUERY = (
    "SELECT b.id, b.type, b.fk, b.parent, b.title, b.dateAdded, b.lastModified, "
    "b.guid, p.url "
    "FROM moz_bookmarks b LEFT JOIN moz_places p ON p.id = b.fk "
    "ORDER BY b.parent, b.position"
)


def _firefox_seconds(value) -> Optional[int]:
    try:
        micros = int(value)
    except (TypeError, ValueError):
        return None
    return micros // 1_000_000 if micros > 0 else None


def _query_firefox(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(_FIREFOX_QUERY).fetchall()
    finally:
        conn.close()


def read_firefox(source: Source) -> ReadResult:
    rows: Optional[list[tuple]] = None
    last_error: Optional[Exception] = None
    with tempfile.TemporaryDirectory(prefix="bookmark-export-") as tmp:
        copy = Path(tmp) / "places.sqlite"
        # The browser may write while we copy; retry if the snapshot is inconsistent.
        for _ in range(3):
            try:
                shutil.copyfile(source.store, copy)
                wal = source.path / "places.sqlite-wal"
                wal_copy = Path(tmp) / "places.sqlite-wal"
                if wal.is_file():
                    shutil.copyfile(wal, wal_copy)
                elif wal_copy.exists():
                    wal_copy.unlink()
                rows = _query_firefox(copy)
                break
            except (OSError, sqlite3.Error) as exc:
                last_error = exc
    if rows is None:
        raise ExportError(f"cannot read {source.store}: {last_error}")

    by_parent: dict[int, list[tuple]] = {}
    by_guid: dict[str, tuple] = {}
    for row in rows:
        by_parent.setdefault(row[3], []).append(row)
        by_guid[row[7]] = row
    tree_root = by_guid.get(FIREFOX_TREE_ROOT)
    if tree_root is None:
        raise ExportError("places.sqlite has no bookmark root (unexpected schema)")

    # Tags are stored as folders below the tags root; map place id -> tag names.
    tags_by_place: dict[int, list[str]] = {}
    tags_root = by_guid.get(FIREFOX_TAGS_ROOT)
    if tags_root is not None:
        for tag_folder in by_parent.get(tags_root[0], []):
            if tag_folder[1] != 2:
                continue
            for entry in by_parent.get(tag_folder[0], []):
                if entry[1] == 1 and entry[2] is not None:
                    tags_by_place.setdefault(entry[2], []).append(tag_folder[4] or "")

    result = ReadResult(roots=[])
    place_queries = 0

    def build(row: tuple) -> Optional[Node]:
        nonlocal place_queries
        _id, kind, fk, _parent, title, added, modified, _guid, url = row
        if kind == 2:
            node = Node(
                "folder",
                title=title or "",
                added=_firefox_seconds(added),
                modified=_firefox_seconds(modified),
            )
            for child in by_parent.get(_id, []):
                converted = build(child)
                if converted is not None:
                    node.children.append(converted)
            return node
        if kind == 3:
            return Node("separator")
        if kind == 1 and url:
            if url.startswith("place:"):
                place_queries += 1
                return None
            return Node(
                "url",
                title=title or url,
                url=url,
                added=_firefox_seconds(added),
                modified=_firefox_seconds(modified),
                tags=sorted({tag for tag in tags_by_place.get(fk, []) if tag}),
            )
        return None

    top = {row[7]: row for row in by_parent.get(tree_root[0], [])}
    for guid in FIREFOX_ROOT_ORDER:
        row = top.get(guid)
        if row is None:
            continue
        node = build(row)
        if node is None or not node.children:
            continue
        node.title = FIREFOX_ROOT_TITLES[guid]
        node.toolbar = guid == "toolbar_____"
        result.roots.append(node)
    if place_queries:
        result.skipped["place_queries"] = place_queries
    return result


READERS: dict[str, Callable[[Source], ReadResult]] = {
    "firefox": read_firefox,
    "chromium": read_chromium,
    "brave": read_chromium,
    "edge": read_chromium,
    "opera": read_chromium,
}


# ---------------------------------------------------------------------------
# Tree helpers
# ---------------------------------------------------------------------------


def count_tree(roots: list[Node]) -> dict[str, int]:
    stats = {"bookmarks": 0, "folders": 0, "separators": 0, "non_http_urls": 0}
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node.kind == "url":
            stats["bookmarks"] += 1
            if not node.url.lower().startswith(("http://", "https://")):
                stats["non_http_urls"] += 1
        elif node.kind == "folder":
            stats["folders"] += 1
            stack.extend(node.children)
        else:
            stats["separators"] += 1
    return stats


def collect_urls(roots: list[Node]) -> list[str]:
    urls: list[str] = []
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node.kind == "url":
            urls.append(node.url)
        elif node.kind == "folder":
            stack.extend(node.children)
    return urls


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _attrs(**values) -> str:
    parts = []
    for name, value in values.items():
        if value is None or value == "":
            continue
        parts.append(f' {name}="{html.escape(str(value), quote=True)}"')
    return "".join(parts)


def _emit(node: Node, depth: int, out: list[str]) -> None:
    pad = "    " * depth
    if node.kind == "separator":
        out.append(f"{pad}<HR>")
    elif node.kind == "url":
        attrs = _attrs(
            HREF=node.url,
            ADD_DATE=node.added,
            LAST_MODIFIED=node.modified,
            TAGS=",".join(node.tags),
        )
        out.append(f"{pad}<DT><A{attrs}>{_escape(node.title or node.url)}</A>")
    else:
        attrs = _attrs(
            ADD_DATE=node.added,
            LAST_MODIFIED=node.modified,
            PERSONAL_TOOLBAR_FOLDER="true" if node.toolbar else None,
        )
        out.append(f"{pad}<DT><H3{attrs}>{_escape(node.title)}</H3>")
        out.append(f"{pad}<DL><p>")
        for child in node.children:
            _emit(child, depth + 1, out)
        out.append(f"{pad}</DL><p>")


def render_html(roots: list[Node], title: str = "Bookmarks") -> str:
    """Render a Netscape bookmark file, understood by all supported browsers."""
    out = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- This is an automatically generated file. -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        f"<TITLE>{_escape(title)}</TITLE>",
        f"<H1>{_escape(title)}</H1>",
        "<DL><p>",
    ]
    for root in roots:
        _emit(root, 1, out)
    out.append("</DL><p>")
    return "\n".join(out) + "\n"


class _BookmarkHtmlParser(HTMLParser):
    """Collects what a browser would import from a Netscape bookmark file."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.folders = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href is not None:
                self.hrefs.append(href)
        elif tag == "h3":
            self.folders += 1


def _normalize(text: str) -> str:
    return text.encode("utf-8", "replace").decode("utf-8")


def verify_html(text: str, roots: list[Node]) -> list[str]:
    """Read the generated HTML back and compare it with the source tree.

    Returns a list of problems; an empty list means the file is consistent.
    """
    parser = _BookmarkHtmlParser()
    parser.feed(text)
    parser.close()
    problems: list[str] = []
    stats = count_tree(roots)
    if parser.folders != stats["folders"]:
        problems.append(f"folder count differs: html={parser.folders} source={stats['folders']}")
    expected = sorted(_normalize(url) for url in collect_urls(roots))
    actual = sorted(parser.hrefs)
    if len(actual) != len(expected):
        problems.append(f"bookmark count differs: html={len(actual)} source={len(expected)}")
    elif actual != expected:
        problems.append("bookmark URLs differ between html and source")
    return problems


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="\n") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.")
    return cleaned or "profile"


IMPORT_STEPS = {
    "firefox": [
        "Press Ctrl+Shift+O to open the Library.",
        "Choose Import and Backup, then Import Bookmarks from HTML...",
        "Select the Firefox .html file. Folders, tags and the toolbar are restored.",
    ],
    "chromium": [
        "Open chrome://bookmarks and use the three-dot menu in the top right.",
        "Choose Import bookmarks and select the Chromium .html file.",
        "Alternative: chrome://settings/importData, then choose Bookmarks HTML file.",
    ],
    "brave": [
        "Open brave://settings/importData.",
        "Select Bookmarks HTML File as the source and choose the Brave .html file.",
    ],
    "edge": [
        "Open edge://settings/profiles/importBrowsingData.",
        "Select Favorites or bookmarks HTML file as the source and choose the Edge .html file.",
    ],
    "opera": [
        "Open opera://settings/importData.",
        "Select Bookmarks HTML file as the source and choose the Opera .html file.",
        "Speed Dial entries are imported as normal bookmarks; pin them to Speed Dial again if needed.",
    ],
}
BROWSER_LABELS = {
    "firefox": "Firefox",
    "chromium": "Chromium",
    "brave": "Brave",
    "edge": "Microsoft Edge",
    "opera": "Opera",
}


def render_import_guide(manifest: dict) -> str:
    entries = [e for e in manifest["entries"] if e["status"] == "ok"]
    lines = [
        "# Importing the exported bookmarks",
        "",
        f"Exported at {manifest['exported_at']} by bookmark-export {manifest['tool_version']}.",
        "",
        "Import each `.html` file into the matching browser and profile on the new machine.",
        "The `.json` files are lossless archives and are not meant to be imported.",
        "Menu names differ slightly between browser versions.",
        "",
        "## Files",
        "",
        "| File | Browser | Profile | Bookmarks | Folders |",
        "|---|---|---|---|---|",
    ]
    for entry in entries:
        profile = entry["profile"]
        if entry["display_name"]:
            profile += f" ({entry['display_name']})"
        lines.append(
            f"| {entry['html_file']} | {BROWSER_LABELS[entry['browser']]} | {profile} "
            f"| {entry['stats']['bookmarks']} | {entry['stats']['folders']} |"
        )
    lines.append("")
    lines.append("## Steps")
    for browser in BROWSERS:
        if not any(e["browser"] == browser for e in entries):
            continue
        lines += ["", f"### {BROWSER_LABELS[browser]}", ""]
        for number, step in enumerate(IMPORT_STEPS[browser], start=1):
            lines.append(f"{number}. {step}")
    lines += [
        "",
        "## Notes",
        "",
        "* Chromium-based browsers may place imported bookmarks in a new folder; drag them where you want them.",
        "* The export files contain your bookmarks in plain text. Store and transfer them accordingly.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _matches(source: Source, profiles: Optional[list[str]], installs: Optional[list[str]]) -> bool:
    if installs and source.install.lower() not in {i.lower() for i in installs}:
        return False
    if profiles:
        wanted = {p.lower() for p in profiles}
        names = {source.profile.lower(), source.display_name.lower(), source.path.name.lower()}
        return bool(wanted & names)
    return True


def _os_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.partition("=")[2].strip('"')
    except OSError:
        pass
    return platform.system()


def export_all(
    home: Path,
    out_dir: Path,
    browsers: tuple[str, ...] = BROWSERS,
    profiles: Optional[list[str]] = None,
    installs: Optional[list[str]] = None,
    write_json: bool = True,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> dict:
    """Export all matching profiles and return the manifest."""
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise ExportError(f"output directory is not empty: {out_dir} (use --force to overwrite)")

    sources = [s for s in discover(home, browsers) if _matches(s, profiles, installs)]
    if not any(s.has_data for s in sources):
        raise ExportError("no bookmark stores found for the selected browsers")

    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    exported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    running = running_browsers()
    used_names: set[str] = set()
    entries: list[dict] = []

    for source in sources:
        entry: dict = {
            "browser": source.browser,
            "install": source.install,
            "profile": source.profile,
            "display_name": source.display_name,
            "source_path": str(source.store),
            "status": "ok",
            "warnings": [],
        }
        entries.append(entry)
        label = f"{source.browser}/{source.install}/{source.profile}"
        if not source.has_data:
            entry["status"] = "no-data"
            log(f"  skipped {label}: no bookmark store")
            continue
        try:
            result = READERS[source.browser](source)
            if source.browser == "firefox" and "firefox" in running:
                result.warnings.append(
                    "Firefox was running; the export is a snapshot and the newest changes "
                    "may be missing. Close Firefox and export again for a fully current copy."
                )
            stats = count_tree(result.roots)

            base = f"{source.browser}_{_slug(source.profile)}"
            if base in used_names:
                base = f"{base}_{_slug(source.install)}"
            counter = 2
            unique = base
            while unique in used_names:
                unique = f"{base}-{counter}"
                counter += 1
            used_names.add(unique)

            html_text = render_html(result.roots, title=f"{BROWSER_LABELS[source.browser]} bookmarks")
            problems = verify_html(html_text, result.roots)
            _write_private(out_dir / f"{unique}.html", html_text)
            entry["html_file"] = f"{unique}.html"
            if write_json:
                archive = {
                    "format": FORMAT_ID,
                    "exported_at": exported_at,
                    "browser": source.browser,
                    "install": source.install,
                    "profile": source.profile,
                    "display_name": source.display_name,
                    "roots": [root.to_dict() for root in result.roots],
                }
                _write_private(
                    out_dir / f"{unique}.json",
                    json.dumps(archive, ensure_ascii=False, indent=1) + "\n",
                )
                entry["json_file"] = f"{unique}.json"
            entry["stats"] = stats
            entry["skipped"] = result.skipped
            entry["warnings"] = list(result.warnings)
            entry["verified"] = not problems
            if problems:
                entry["status"] = "verification-failed"
                entry["warnings"].extend(problems)
            log(
                f"  {label}: {stats['bookmarks']} bookmarks, {stats['folders']} folders"
                f" -> {entry['html_file']}"
                + ("" if not problems else "  VERIFICATION FAILED")
            )
            for warning in entry["warnings"]:
                log(f"    warning: {warning}")
        except Exception as exc:  # keep going with the other profiles
            entry["status"] = "error"
            entry["error"] = str(exc)
            log(f"  error in {label}: {exc}")

    manifest = {
        "format": FORMAT_ID,
        "tool_version": __version__,
        "exported_at": exported_at,
        "host": {"os": _os_name(), "python": platform.python_version()},
        "entries": entries,
    }
    _write_private(out_dir / "manifest.json", json.dumps(manifest, indent=1) + "\n")
    _write_private(out_dir / "IMPORT.md", render_import_guide(manifest))
    return manifest


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def cmd_detect(args: argparse.Namespace) -> int:
    home = Path.home()
    sources = discover(home, tuple(args.browser) if args.browser else BROWSERS)
    running = running_browsers()
    if not sources:
        print("No browser profiles found.")
        return 1
    print("Detected browser profiles (read-only check):")
    print(f"  {'BROWSER':<9}{'INSTALL':<10}{'PROFILE':<22}{'DATA':<6}PATH")
    for source in sources:
        profile = source.profile
        if source.display_name:
            profile += f" ({source.display_name})"
        print(
            f"  {source.browser:<9}{source.install:<10}{profile:<22}"
            f"{'yes' if source.has_data else 'no':<6}{source.path}"
        )
    print(f"Running now: {', '.join(running) if running else 'none'}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    home = Path.home()
    out_dir = Path(args.out) if args.out else Path.cwd() / f"bookmarks-export-{datetime.now():%Y-%m-%d}"
    browsers = tuple(args.browser) if args.browser else BROWSERS
    print(f"Exporting bookmarks to {out_dir}")
    try:
        manifest = export_all(
            home,
            out_dir,
            browsers=browsers,
            profiles=args.profile,
            installs=args.install,
            write_json=not args.no_json,
            force=args.force,
        )
    except ExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    ok = [e for e in manifest["entries"] if e["status"] == "ok"]
    failed = [e for e in manifest["entries"] if e["status"] in ("error", "verification-failed")]
    total = sum(e["stats"]["bookmarks"] for e in ok)
    print(f"Done: {len(ok)} profile(s), {total} bookmarks. See IMPORT.md and manifest.json in the output folder.")
    if failed:
        print(f"{len(failed)} profile(s) had problems; see the messages above.", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookmark_export.py",
        description="Export browser bookmarks (Firefox, Chromium, Brave, Edge, Opera) on Linux.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    detect = sub.add_parser("detect", help="list browser profiles and whether they hold bookmarks")
    detect.add_argument("--browser", action="append", choices=BROWSERS, help="limit to a browser (repeatable)")
    detect.set_defaults(func=cmd_detect)

    export = sub.add_parser("export", help="export bookmarks to HTML and JSON files")
    export.add_argument("--out", help="output directory (default: ./bookmarks-export-YYYY-MM-DD)")
    export.add_argument("--browser", action="append", choices=BROWSERS, help="limit to a browser (repeatable)")
    export.add_argument("--profile", action="append", help="limit to a profile name or display name (repeatable)")
    export.add_argument("--install", action="append", help="limit to an install type such as snap or native (repeatable)")
    export.add_argument("--no-json", action="store_true", help="do not write the JSON archives")
    export.add_argument("--force", action="store_true", help="allow writing into a non-empty output directory")
    export.set_defaults(func=cmd_export)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
