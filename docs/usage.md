# Usage

## Requirements

* Linux with Python 3.9 or newer. The tool is written against the standard library only. It was developed on Python 3.13, and Ubuntu 24.04 and Linux Mint 22 ship Python 3.12.
* Read access to your home directory.

No installation step is needed. Run `bookmark_export.py` from anywhere, or copy that single file to the machine.

## Commands

### `detect`

Lists every browser profile found, whether it holds bookmarks, and which browsers are running. It reads nothing but directory listings and small profile index files.

```bash
python3 bookmark_export.py detect
python3 bookmark_export.py detect --browser opera
```

Example output:

```
Detected browser profiles (read-only check):
  BROWSER  INSTALL   PROFILE               DATA  PATH
  firefox  snap      default               yes   /home/you/snap/firefox/common/.mozilla/firefox/abcd.default
  brave    native    Default (Personal)    yes   /home/you/.config/BraveSoftware/Brave-Browser/Default
Running now: none
```

### `export`

Writes the HTML and JSON files, `manifest.json` and `IMPORT.md`.

```bash
python3 bookmark_export.py export --out ~/bookmarks-export
```

| Option | Meaning |
|---|---|
| `--out DIR` | Output directory. Default: `./bookmarks-export-YYYY-MM-DD`. |
| `--browser NAME` | Limit to a browser. Repeatable. Choices: `firefox`, `chromium`, `brave`, `edge`, `opera`. |
| `--profile NAME` | Limit to a profile. Matches the profile name, the directory name or the display name, ignoring case. Repeatable. |
| `--install TYPE` | Limit to an install type: `native`, `xdg`, `snap`, `flatpak`, `beta`, `developer`. Repeatable. |
| `--no-json` | Skip the JSON archives. |
| `--no-firefox-backup` | Skip the Firefox backup file (`*.firefox-backup.json`). |
| `--force` | Write into a non-empty output directory. Existing files with the same names are overwritten. |

### Examples

Export only the Work profile of Chromium:

```bash
python3 bookmark_export.py export --out ~/bm --browser chromium --profile Work
```

Export only snap-installed browsers:

```bash
python3 bookmark_export.py export --out ~/bm --install snap
```

Export again into the same folder:

```bash
python3 bookmark_export.py export --out ~/bm --force
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Everything found was exported and verified. |
| `1` | Nothing could be exported (no bookmark stores found, or the output directory is not empty). |
| `2` | The run finished, but at least one profile failed or did not verify. The messages and `manifest.json` say which. |

Profiles with no bookmark file are reported as `no-data` and do not cause a failure.

## Using several machines

If the same browser account is synced on several machines, the bookmarks are usually identical. Export from one machine only, otherwise you will import duplicates.

## Troubleshooting

**`no bookmark stores found for the selected browsers`**
Run `detect`. If your browser is missing, it may use a profile location the tool does not know. Run `python3 tools/probe.py` and check the paths it prints, then open an issue with the path layout (the report contains no bookmark titles or URLs).

**A Firefox profile shows `no places.sqlite`**
Firefox keeps one profile per entry in `profiles.ini`, and unused profiles may be empty. The profile you actually use is usually named `default-release` or `default`.

**`Firefox was running; the export is a snapshot` warning**
The copy is consistent, but changes Firefox has not yet written to disk may be missing. Close Firefox and export again for a fully current copy.

**Chromium-based browser: bookmarks changed recently but are missing**
These browsers write the `Bookmarks` file shortly after a change. Wait a few seconds or close the browser, then export again.

**`output directory is not empty`**
Choose another `--out` folder, or add `--force`.

**The count after import differs from the count in `manifest.json`**
Chromium-based browsers and Firefox count differently (folders, separators, Firefox tags). Compare the bookmarks, not the total item numbers. The `stats` in `manifest.json` list bookmarks, folders and separators separately.

**Non-web bookmarks**
Bookmarks with other schemes (`javascript:`, `about:` and similar) are exported, and counted as `non_http_urls` in the manifest. Some browsers refuse to import them.
