# How it works

The tool has four stages: discovery, reading, writing and verification. Everything lives in `bookmark_export.py`.

```
discover profiles -> read bookmarks into a tree -> write HTML (+ JSON) -> read the HTML back and compare
```

## 1. Discovery

For each supported browser the tool checks the known profile locations under your home directory. A location that does not exist is ignored.

| Browser | Location | Install label |
|---|---|---|
| Firefox | `~/.mozilla/firefox` | native |
| Firefox | `~/.config/mozilla/firefox` | xdg |
| Firefox | `~/snap/firefox/common/.mozilla/firefox` | snap |
| Firefox | `~/.var/app/org.mozilla.firefox/.mozilla/firefox` | flatpak |
| Chromium | `~/.config/chromium` | native |
| Chromium | `~/snap/chromium/common/chromium` | snap |
| Chromium | `~/.var/app/org.chromium.Chromium/config/chromium` | flatpak |
| Brave | `~/.config/BraveSoftware/Brave-Browser` | native |
| Brave | `~/snap/brave/current/.config/BraveSoftware/Brave-Browser` | snap |
| Brave | `~/.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser` | flatpak |
| Edge | `~/.config/microsoft-edge` | native |
| Edge | `~/.var/app/com.microsoft.Edge/config/microsoft-edge` | flatpak |
| Opera | `~/.config/opera` (also `opera-beta`, `opera-developer`) | native, beta, developer |
| Opera | `~/snap/opera/current/.config/opera` | snap |
| Opera | `~/.var/app/com.opera.Opera/config/opera` | flatpak |

**Firefox profiles** are listed in `profiles.ini` in the Firefox root. Each `[ProfileN]` section gives a name and a path (relative to the root or absolute).

**Chromium-family profiles** are the directories named `Default` and `Profile N` inside the root. The display name (for example "Work") comes from `Local State`. If a `Bookmarks` file sits directly in the root folder, that is treated as a profile named `(root)`.

A profile counts as having data when `places.sqlite` (Firefox) or `Bookmarks` (others) exists.

## 2. Reading

All readers produce the same tree of folders, bookmarks and separators.

### Chromium, Brave, Edge and Opera

The `Bookmarks` file is plain JSON. The tool reads `roots`:

* `bookmark_bar`, `other` and `synced` become "Bookmarks bar", "Other bookmarks" and "Mobile bookmarks". The original names in the file are localized, so fixed English names are used instead.
* Opera nests extra roots one level deeper under `custom_root`, for example `speedDial`, `userRoot`, `unsorted` and `pinboard`. These are exported as additional top-level folders.
* `trash` and `unsyncedPinboard` are skipped. The number of skipped bookmarks is recorded in the manifest under `skipped`.
* Empty roots are left out.
* Timestamps are microseconds since 1601-01-01 and are converted to Unix seconds.
* The `checksum` field is ignored, since the tool never writes to the file.

### Firefox

Firefox stores bookmarks in an SQLite database, `places.sqlite`, with the tables `moz_bookmarks` (the tree) and `moz_places` (the URLs).

A running Firefox keeps the database open and keeps recent changes in a write-ahead log, `places.sqlite-wal`. To get a consistent snapshot without touching the original, the tool:

1. copies `places.sqlite` and `places.sqlite-wal` to a temporary directory,
2. opens the copy,
3. retries up to three times if the snapshot turns out to be inconsistent (the browser may write while copying),
4. deletes the temporary directory afterwards.

From the copy it builds the tree starting at the root with GUID `root________`:

* `toolbar_____`, `menu________`, `unfiled_____` and `mobile______` become "Bookmarks Toolbar", "Bookmarks Menu", "Other Bookmarks" and "Mobile Bookmarks". Empty roots are left out.
* Row type 1 is a bookmark, 2 a folder, 3 a separator.
* Tags are stored as folders below the `tags________` root. They are mapped back to the bookmarks they belong to and written as a `TAGS` attribute, so they survive an import into Firefox.
* Bookmarks whose URL starts with `place:` are smart bookmarks (saved queries) and are skipped. The number is recorded in the manifest.
* A bookmark without a title gets its URL as the title.

## 3. Writing

For each profile with data, the tool writes:

* A Netscape bookmark HTML file, the de facto standard that all supported browsers import.
* A JSON archive of the same tree (unless `--no-json` is given).

Files are named `<browser>_<profile>`. Characters outside letters, digits, `.`, `_` and `-` in the profile name are replaced with `-`. If two profiles would get the same name, the install label and then a counter are appended.

Files are created with mode `0600` and the output directory with `0700`.

The tool also writes `manifest.json` and `IMPORT.md`. See [output-format.md](output-format.md).

### Firefox backup file

For Firefox profiles the tool also writes a file in the format of Firefox's own backup (Bookmarks, Manage, Import and Backup, Backup). It is built from the same snapshot of `places.sqlite` as the HTML file, so the two always agree.

Unlike the HTML file, the backup is meant to restore a profile exactly, so it keeps what HTML cannot carry: GUIDs, ids, positions, microsecond timestamps, smart bookmarks and non-web URLs. Page icons are added from `favicons.sqlite`, which is copied and read the same way as `places.sqlite`. If that database is missing, the backup is written without `iconUri` values. The widest known icon of a page is used.

The format is described in [output-format.md](output-format.md).

## 4. Verification

After rendering the HTML, the tool parses it again with Python's `html.parser` and compares it with the tree it started from:

* the number of folders must match,
* the sorted list of bookmark URLs must match exactly.

A mismatch marks the profile as `verification-failed`, prints the reason and makes the program exit with code 2. This catches escaping errors and lost entries before you rely on the files.

The Firefox backup is verified differently: it is parsed again and must equal the tree it was serialized from, and all GUIDs must be unique.

The check proves that the file contains what was read. It cannot prove that the browser's own importer accepts every entry, so test the import once on the new machine.

## Design decisions

* **HTML as the interchange format.** Every browser already ships an importer for it, so the new machine needs no tools.
* **One file, standard library only.** The tool must run on a freshly installed machine without installing anything.
* **Read-only.** Writing directly into another browser's profile is fragile (the Chromium `Bookmarks` file is checksummed, and browsers overwrite it), so import is left to the browsers.
* **One failure does not stop the run.** If one profile cannot be read, the others are still exported and the problem is reported.
