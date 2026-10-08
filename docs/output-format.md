# Output format reference

An export creates one directory with these files.

```
<out>/
  <browser>_<profile>.html
  <browser>_<profile>.json
  firefox_<profile>.firefox-backup.json   (Firefox profiles only)
  manifest.json
  IMPORT.md
```

All files are UTF-8 with Unix line endings. Files have mode `0600`, the directory `0700`.

## HTML files

Netscape bookmark format (`<!DOCTYPE NETSCAPE-Bookmark-file-1>`):

* a folder is `<DT><H3>name</H3>` followed by a `<DL><p>` block,
* a bookmark is `<DT><A HREF="...">title</A>`,
* a separator is `<HR>`.

Attributes written when known:

| Attribute | On | Meaning |
|---|---|---|
| `ADD_DATE` | folder, bookmark | Unix timestamp in seconds |
| `LAST_MODIFIED` | folder, bookmark | Unix timestamp in seconds |
| `TAGS` | bookmark | comma separated tags (Firefox) |
| `PERSONAL_TOOLBAR_FOLDER="true"` | folder | the bookmarks bar / toolbar |

Titles and attribute values are HTML-escaped.

Top-level folders (empty ones are left out):

* Chromium family: Bookmarks bar, Other bookmarks, Mobile bookmarks, and for Opera and Edge also Speed Dial, User bookmarks, Unsorted, Pinboard and Workspaces when present.
* Firefox: Bookmarks Toolbar, Bookmarks Menu, Other Bookmarks and Mobile Bookmarks.

## JSON archives

A lossless description of the exported tree. It is meant for archiving and for other tools, not for browser import.

```json
{
  "format": "bookmark-export/1",
  "exported_at": "2026-10-08T12:00:00+00:00",
  "browser": "firefox",
  "install": "snap",
  "profile": "default",
  "display_name": "",
  "roots": [
    {
      "type": "folder",
      "title": "Bookmarks Toolbar",
      "toolbar": true,
      "children": [
        {
          "type": "url",
          "title": "Example",
          "url": "https://example.com/",
          "added": 1577836800,
          "modified": 1577836800,
          "tags": ["reading"]
        },
        { "type": "separator" }
      ]
    }
  ]
}
```

Node fields:

| Field | Applies to | Notes |
|---|---|---|
| `type` | all | `folder`, `url` or `separator` |
| `title` | folder, url | |
| `url` | url | |
| `added`, `modified` | folder, url | Unix seconds, omitted when unknown |
| `tags` | url | omitted when empty |
| `toolbar` | folder | `true` only for the bookmarks bar / toolbar |
| `children` | folder | nodes in browser order |

## Firefox backup files

`firefox_<profile>.firefox-backup.json` has the format of the file that Firefox writes with Bookmarks, Manage, Import and Backup, Backup (`bookmarks-YYYY-MM-DD.json`). It can be loaded with **Restore**. See [importing.md](importing.md).

Serialization: compact JSON on a single line, raw UTF-8 (no `\uXXXX` escapes for letters), no trailing newline.

The top-level object is the places root (`"root": "placesRoot"`). Its `children` are, in position order, the four root folders that exist in the profile database: `bookmarksMenuFolder`, `toolbarFolder`, `unfiledBookmarksFolder` and `mobileFolder`. The tags root is not part of the file.

Node fields, in the order they are written:

| Field | Applies to | Notes |
|---|---|---|
| `guid` | all | Firefox's item GUID |
| `title` | all | empty string when the item has no title; separators always have an empty title |
| `index` | all | position among its siblings, as stored in the database (gaps are kept) |
| `dateAdded`, `lastModified` | all | microseconds since the Unix epoch |
| `id` | all | database id; informational, restore uses the GUID |
| `typeCode` | all | `1` bookmark, `2` folder, `3` separator |
| `iconUri` | bookmark | widest known icon of the page; only when `favicons.sqlite` has one |
| `type` | all | `text/x-moz-place`, `text/x-moz-place-container` or `text/x-moz-place-separator` |
| `uri` | bookmark | includes `place:` queries and non-web URLs |
| `tags` | bookmark | comma separated, sorted; only when the bookmark has tags |
| `root` | root folders | one of the four names above, or `placesRoot` |
| `children` | folder | omitted when the folder is empty |

Not included yet: search keywords and annotations such as bookmark descriptions.

The `.firefox-backup.json` file is not the same as the `.json` archive of this tool. The archive is a simplified tree that is identical for all browsers; the backup is Firefox's own format.

## manifest.json

```json
{
  "format": "bookmark-export/1",
  "tool_version": "0.2.0",
  "exported_at": "2026-10-08T12:00:00+00:00",
  "host": { "os": "Ubuntu 24.04.4 LTS", "python": "3.12.3" },
  "entries": [
    {
      "browser": "brave",
      "install": "native",
      "profile": "Default",
      "display_name": "Personal",
      "source_path": "/home/you/.config/BraveSoftware/Brave-Browser/Default/Bookmarks",
      "status": "ok",
      "html_file": "brave_Default.html",
      "json_file": "brave_Default.json",
      "stats": { "bookmarks": 44, "folders": 15, "separators": 0, "non_http_urls": 0 },
      "skipped": {},
      "verified": true,
      "warnings": []
    }
  ]
}
```

Entry fields:

| Field | Meaning |
|---|---|
| `browser`, `install`, `profile`, `display_name` | which profile this is |
| `source_path` | the store that was read |
| `status` | `ok`, `no-data` (no bookmark file), `verification-failed` or `error` |
| `html_file`, `json_file` | file names in the output directory (not present for `no-data` and `error`) |
| `firefox_backup_file` | name of the Firefox backup file (Firefox profiles only, unless `--no-firefox-backup`) |
| `firefox_backup_stats` | `bookmarks`, `folders` (the four root folders included, the places root excluded) and `separators` in the backup. Unlike `stats`, it counts empty roots and smart bookmarks. |
| `stats` | counts of bookmarks, folders, separators and bookmarks that are not http(s) URLs |
| `skipped` | items left out: `place_queries` (Firefox smart bookmarks) or `root:<name>` (skipped Chromium/Opera roots such as trash), each with a count |
| `verified` | `true` when the HTML read back matches the source |
| `warnings` | for example the Firefox-was-running notice or the verification problems |
| `error` | the error message when `status` is `error` |

Firefox counts: the manifest counts bookmarks as the tool exports them. Firefox's own database also holds rows used for tags, so its raw bookmark row count is higher than the exported count.

## IMPORT.md

A table of the exported files with their counts, and import steps for each exported browser. Generated per run.
