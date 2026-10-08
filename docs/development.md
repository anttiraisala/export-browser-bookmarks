# Development

## Layout

```
bookmark_export.py            the tool (single file, standard library only)
tests/test_bookmark_export.py unit tests
tools/probe.py                read-only diagnostic report of browser stores
docs/                         documentation
```

## Running the tests

```bash
python3 -m unittest discover -s tests -v
```

The tests build small synthetic profiles in a temporary directory: a Chromium `Bookmarks` file, an Opera-style profile with nested roots and a root-level profile, and a Firefox `places.sqlite` with folders, separators, tags, a smart bookmark and an untitled bookmark. They cover timestamp conversion, all readers, HTML round-trip verification, discovery, file permissions, option handling and the generated import guide.

### Checking the Firefox backup against a real file

The unit tests use small synthetic databases. The backup writer was additionally checked with a real Firefox backup: the `moz_bookmarks`, `moz_places` and `favicons.sqlite` tables were rebuilt from that file, the exporter was run on them, and the output was compared with the original. It was byte-identical. This proves that the writer reproduces Firefox's serialization (key order, empty folders, positions, timestamps, icons); it does not exercise the SQL queries against a real database, which the probe reports and the field use cover. The real file contains private data and is not part of the repository. To repeat the check with your own backup, rebuild the tables from it as described and compare the bytes.

## The probe

`tools/probe.py` prints which browsers and profiles exist on a machine and how their bookmark stores are structured. It writes `probe-report.json` in the current directory.

```bash
python3 tools/probe.py
```

The report contains paths, counts and column names only. It never contains bookmark titles or URLs, so it is safe to attach to an issue. The probe was used to design the reader for each layout.

## Adding a browser

1. If it is Chromium based, add its profile roots to `chromium_family_roots()`, its name to `BROWSERS` and `CHROMIUM_FAMILY`, its process name to `PROCESS_NAMES`, a label to `BROWSER_LABELS` and import steps to `IMPORT_STEPS`. The existing reader handles the `Bookmarks` file.
2. If it uses another storage format, write a `read_<name>(source) -> ReadResult` function that builds a tree of `Node` objects and register it in `READERS`.
3. Add a fixture and tests.

## Conventions

* Python standard library only. Keep the tool a single file so it can be copied to a fresh machine.
* Never write to a browser's own files. Copy first, then read the copy.
* Never put bookmark titles or URLs in logs, probe reports or test output.
* Everything in the repository is written in English: code, comments, user-facing text, documentation, tests, commit messages and branch names.
* The default branch is `master`.

## Releasing

There is no packaging step. Update `__version__` in `bookmark_export.py`, run the tests and tag the commit.
