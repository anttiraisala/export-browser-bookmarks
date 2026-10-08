#!/usr/bin/env python3
"""Read-only diagnostic probe for browser bookmark storage on Linux.

It looks for Firefox, Chromium, Brave, Microsoft Edge and Opera profiles, checks
that their bookmark stores can be read, and prints a summary. It also writes
the same data to probe-report.json in the current directory.

Privacy: the report contains only paths, counts and structure information.
It never contains bookmark titles or URLs.

Usage:
    python3 probe.py
"""

import configparser
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HOME = Path.home()

CHROMIUM_ROOTS = {
    "chromium": [
        ("deb/native", HOME / ".config/chromium"),
        ("snap", HOME / "snap/chromium/common/chromium"),
        ("flatpak", HOME / ".var/app/org.chromium.Chromium/config/chromium"),
    ],
    "brave": [
        ("deb/native", HOME / ".config/BraveSoftware/Brave-Browser"),
        ("snap", HOME / "snap/brave/current/.config/BraveSoftware/Brave-Browser"),
        ("flatpak", HOME / ".var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser"),
    ],
    "edge": [
        ("deb/native", HOME / ".config/microsoft-edge"),
        ("flatpak", HOME / ".var/app/com.microsoft.Edge/config/microsoft-edge"),
    ],
    # Opera usually keeps its profile directly in the root folder (no "Default").
    "opera": [
        ("deb/native", HOME / ".config/opera"),
        ("beta", HOME / ".config/opera-beta"),
        ("developer", HOME / ".config/opera-developer"),
        ("snap", HOME / "snap/opera/current/.config/opera"),
        ("flatpak", HOME / ".var/app/com.opera.Opera/config/opera"),
    ],
}

FIREFOX_ROOTS = [
    ("deb/native", HOME / ".mozilla/firefox"),
    ("xdg", HOME / ".config/mozilla/firefox"),
    ("snap", HOME / "snap/firefox/common/.mozilla/firefox"),
    ("flatpak", HOME / ".var/app/org.mozilla.firefox/.mozilla/firefox"),
]

BINARIES = {
    "firefox": ["firefox"],
    "chromium": ["chromium", "chromium-browser"],
    "brave": ["brave-browser", "brave"],
    "edge": ["microsoft-edge", "microsoft-edge-stable"],
    "opera": ["opera", "opera-beta", "opera-developer"],
}

PROCESS_NAMES = {
    "firefox": {"firefox", "firefox-bin"},
    "chromium": {"chromium", "chromium-browse"},
    "brave": {"brave", "brave-browser"},
    "edge": {"msedge", "microsoft-edge"},
    "opera": {"opera"},
}


def system_info():
    info = {
        "python": sys.version.split()[0],
        "kernel": platform.release(),
        "machine": platform.machine(),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "session_type": os.environ.get("XDG_SESSION_TYPE", ""),
    }
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith(("PRETTY_NAME=", "VERSION_ID=")):
                key, _, value = line.partition("=")
                info[key.lower()] = value.strip('"')
    except OSError:
        pass
    return info


def find_binaries():
    return {
        browser: [shutil.which(name) for name in names if shutil.which(name)]
        for browser, names in BINARIES.items()
    }


def running_browsers():
    found = set()
    for comm_file in Path("/proc").glob("[0-9]*/comm"):
        try:
            name = comm_file.read_text().strip()
        except OSError:
            continue
        for browser, names in PROCESS_NAMES.items():
            if name in names:
                found.add(browser)
    return sorted(found)


def count_chromium_nodes(node, counts):
    if node.get("type") == "url":
        counts["urls"] += 1
        if not str(node.get("url", "")).startswith(("http://", "https://")):
            counts["non_http_urls"] += 1
    elif node.get("type") == "folder":
        counts["folders"] += 1
        for child in node.get("children", []):
            count_chromium_nodes(child, counts)


def probe_chromium_profile(profile_dir):
    result = {"profile": profile_dir.name, "path": str(profile_dir)}
    bookmarks_file = profile_dir / "Bookmarks"
    if not bookmarks_file.is_file():
        result["bookmarks_file"] = False
        return result
    result["bookmarks_file"] = True
    result["size_bytes"] = bookmarks_file.stat().st_size
    try:
        data = json.loads(bookmarks_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result["error"] = f"cannot parse: {exc}"
        return result
    result["json_version"] = data.get("version")
    result["has_checksum"] = "checksum" in data
    roots = data.get("roots", {})
    result["root_keys"] = sorted(roots.keys())
    per_root = {}
    for key, node in roots.items():
        if not isinstance(node, dict):
            continue
        if "children" in node:
            candidates = [(key, node)]
        else:
            # Opera nests extra roots (for example speed dial) one level deeper.
            candidates = [
                (f"{key}/{sub_key}", sub)
                for sub_key, sub in node.items()
                if isinstance(sub, dict) and "children" in sub
            ]
        for name, candidate in candidates:
            counts = {"urls": 0, "folders": 0, "non_http_urls": 0}
            count_chromium_nodes(candidate, counts)
            per_root[name] = counts
    result["per_root"] = per_root
    result["total_urls"] = sum(c["urls"] for c in per_root.values())
    return result


def probe_chromium(browser):
    entries = []
    for install, root in CHROMIUM_ROOTS[browser]:
        if not root.is_dir():
            continue
        entry = {"install": install, "root": str(root), "profiles": []}
        local_state = root / "Local State"
        names = {}
        if local_state.is_file():
            try:
                state = json.loads(local_state.read_text(encoding="utf-8"))
                cache = state.get("profile", {}).get("info_cache", {})
                names = {k: v.get("name", "") for k, v in cache.items()}
            except (OSError, ValueError):
                pass
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child.name == "Default" or child.name.startswith("Profile ")):
                profile = probe_chromium_profile(child)
                profile["display_name"] = names.get(child.name, "")
                entry["profiles"].append(profile)
        if (root / "Bookmarks").is_file():
            # Profile stored directly in the root folder (typical for Opera).
            profile = probe_chromium_profile(root)
            profile["profile"] = "(root)"
            profile["display_name"] = ""
            entry["profiles"].append(profile)
        entries.append(entry)
    return entries


def read_firefox_profiles(root):
    ini = root / "profiles.ini"
    profiles = []
    if ini.is_file():
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(ini, encoding="utf-8")
        for section in parser.sections():
            if not section.startswith("Profile"):
                continue
            path = parser.get(section, "Path", fallback=None)
            if not path:
                continue
            is_relative = parser.get(section, "IsRelative", fallback="1") == "1"
            full = root / path if is_relative else Path(path)
            profiles.append(
                {
                    "name": parser.get(section, "Name", fallback=""),
                    "default": parser.get(section, "Default", fallback="0") == "1",
                    "path": full,
                }
            )
    return profiles


def probe_firefox_profile(profile):
    path = profile["path"]
    result = {"name": profile["name"], "default": profile["default"], "path": str(path)}
    db = path / "places.sqlite"
    if not db.is_file():
        result["places_sqlite"] = False
        return result
    result["places_sqlite"] = True
    result["wal_present"] = (path / "places.sqlite-wal").is_file()
    backup_dir = path / "bookmarkbackups"
    result["backup_files"] = (
        len(list(backup_dir.glob("*.jsonlz4"))) if backup_dir.is_dir() else 0
    )
    with tempfile.TemporaryDirectory() as tmp:
        for suffix in ("", "-wal", "-shm"):
            src = path / f"places.sqlite{suffix}"
            if src.is_file():
                shutil.copy2(src, Path(tmp) / src.name)
        try:
            conn = sqlite3.connect(f"file:{Path(tmp) / 'places.sqlite'}?mode=ro", uri=True)
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(moz_bookmarks)")]
                result["moz_bookmarks_columns"] = cols
                result["moz_places_columns"] = [
                    r[1] for r in conn.execute("PRAGMA table_info(moz_places)")
                ]
                query = "SELECT type, COUNT(*) FROM moz_bookmarks GROUP BY type"
                type_counts = dict(conn.execute(query).fetchall())
                result["type_counts"] = {
                    "bookmarks": type_counts.get(1, 0),
                    "folders": type_counts.get(2, 0),
                    "separators": type_counts.get(3, 0),
                }
                result["place_queries"] = conn.execute(
                    "SELECT COUNT(*) FROM moz_bookmarks b JOIN moz_places p ON p.id=b.fk "
                    "WHERE b.type=1 AND p.url LIKE 'place:%'"
                ).fetchone()[0]
                result["non_http_urls"] = conn.execute(
                    "SELECT COUNT(*) FROM moz_bookmarks b JOIN moz_places p ON p.id=b.fk "
                    "WHERE b.type=1 AND p.url NOT LIKE 'http%' AND p.url NOT LIKE 'place:%'"
                ).fetchone()[0]
                result["root_folders"] = [
                    r[0]
                    for r in conn.execute(
                        "SELECT title FROM moz_bookmarks WHERE parent="
                        "(SELECT id FROM moz_bookmarks WHERE parent=0 LIMIT 1) AND type=2"
                    )
                ]
            finally:
                conn.close()
        except sqlite3.Error as exc:
            result["error"] = f"sqlite: {exc}"
    return result


def probe_firefox():
    entries = []
    for install, root in FIREFOX_ROOTS:
        if not root.is_dir():
            continue
        profiles = read_firefox_profiles(root)
        entries.append(
            {
                "install": install,
                "root": str(root),
                "profiles_ini": (root / "profiles.ini").is_file(),
                "profiles": [probe_firefox_profile(p) for p in profiles],
            }
        )
    return entries


def print_report(report):
    print("=== System ===")
    for key, value in report["system"].items():
        print(f"  {key}: {value}")
    print("\n=== Executables found on PATH ===")
    for browser, paths in report["binaries"].items():
        print(f"  {browser}: {', '.join(paths) if paths else '-'}")
    print(f"\n=== Running now: {', '.join(report['running']) or 'none'} ===")

    print("\n=== Firefox ===")
    if not report["firefox"]:
        print("  no profile roots found")
    for entry in report["firefox"]:
        print(f"  [{entry['install']}] {entry['root']}")
        for p in entry["profiles"]:
            if not p.get("places_sqlite"):
                print(f"    - {p['name']}: no places.sqlite")
                continue
            tc = p.get("type_counts", {})
            print(
                f"    - {p['name']}{' (default)' if p['default'] else ''}: "
                f"{tc.get('bookmarks', '?')} bookmarks, {tc.get('folders', '?')} folders, "
                f"{p.get('place_queries', '?')} place: queries, "
                f"{p.get('non_http_urls', '?')} non-http, wal={p.get('wal_present')}"
                + (f"  ERROR: {p['error']}" if "error" in p else "")
            )

    for browser in ("chromium", "brave", "edge", "opera"):
        print(f"\n=== {browser.capitalize()} ===")
        if not report[browser]:
            print("  no profile roots found")
        for entry in report[browser]:
            print(f"  [{entry['install']}] {entry['root']}")
            for p in entry["profiles"]:
                if not p.get("bookmarks_file"):
                    print(f"    - {p['profile']}: no Bookmarks file")
                    continue
                label = f" ({p['display_name']})" if p.get("display_name") else ""
                print(
                    f"    - {p['profile']}{label}: {p.get('total_urls', '?')} bookmarks, "
                    f"roots={','.join(p.get('root_keys', []))}"
                    + (f"  ERROR: {p['error']}" if "error" in p else "")
                )


def main():
    report = {
        "system": system_info(),
        "binaries": find_binaries(),
        "running": running_browsers(),
        "firefox": probe_firefox(),
        "chromium": probe_chromium("chromium"),
        "brave": probe_chromium("brave"),
        "edge": probe_chromium("edge"),
        "opera": probe_chromium("opera"),
    }
    print_report(report)
    out = Path("probe-report.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFull report written to {out.resolve()}")
    print("It contains no bookmark titles or URLs, only paths and counts.")


if __name__ == "__main__":
    main()
