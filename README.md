# export-browser-bookmarks

Export the bookmarks of Firefox, Chromium, Brave, Microsoft Edge and Opera on Linux into plain HTML files, so you can import them into the same browsers on a fresh machine.

One Python file, no dependencies, read-only with respect to your browsers.

## Quick start (copy and paste)

### 1. On the old machine: export

Close Firefox first (recommended, not required), then run:

```bash
git clone https://github.com/anttiraisala/export-browser-bookmarks.git
cd export-browser-bookmarks
python3 bookmark_export.py detect
python3 bookmark_export.py export --out ~/bookmarks-export
```

`detect` shows which browser profiles were found. `export` writes the files to `~/bookmarks-export`.
If the last command ends with `Done: ... profile(s), ... bookmarks.` and exits normally, every file was read back and verified.

Only want some browsers? Add `--browser`, for example:

```bash
python3 bookmark_export.py export --out ~/bookmarks-export --browser firefox --browser brave
```

### 2. Move the files

Use a USB stick or the network. Examples:

```bash
cp -r ~/bookmarks-export /media/$USER/YOUR_USB_STICK/
scp -r ~/bookmarks-export YOUR_USER@NEW_MACHINE:~/
```

### 3. On the new machine: import

Install your browsers and start each one once. Then import the matching `.html` file from the export folder:

| Browser | How to import the `.html` file |
|---|---|
| Firefox | Press `Ctrl+Shift+O`, then **Import and Backup**, then **Import Bookmarks from HTML...** |
| Chromium | Open `chrome://bookmarks`, three-dot menu, **Import bookmarks** |
| Brave | Open `brave://settings/importData`, choose **Bookmarks HTML File** |
| Edge | Open `edge://settings/profiles/importBrowsingData`, choose the bookmarks HTML file |
| Opera | Open `opera://settings/importData`, choose **Bookmarks HTML file** |

The file `IMPORT.md` in the export folder repeats these steps for exactly the browsers you exported.
Menu names differ a little between browser versions.

### 4. Clean up

The export folder contains your bookmarks in plain text. Delete it when you are done:

```bash
rm -r ~/bookmarks-export
```

## What you get

```
bookmarks-export/
  firefox_default-release.html   import this into Firefox
  firefox_default-release.json   lossless archive (dates, tags), not for import
  chromium_Default.html
  chromium_Default.json
  brave_Default.html
  ...
  manifest.json                  what was exported, counts, warnings, verification result
  IMPORT.md                      import steps for this export
```

Every profile of every detected browser gets its own pair of files, for example when you use a "Work" and a "Personal" profile.

## Supported browsers and installs

| Browser | Install types | Source read |
|---|---|---|
| Firefox | deb, snap, flatpak | `places.sqlite` (copied first, so Firefox may be running) |
| Chromium | deb, snap, flatpak | `Bookmarks` JSON file |
| Brave | deb, snap, flatpak | `Bookmarks` JSON file |
| Microsoft Edge | deb, flatpak | `Bookmarks` JSON file |
| Opera | deb (stable, beta, developer), snap, flatpak | `Bookmarks` JSON file, including Speed Dial |

Developed against probe reports from Ubuntu 24.04 and 26.04 (GNOME and Unity 7) and Linux Mint 22 (Cinnamon).

## Options

| Option | Meaning |
|---|---|
| `--out DIR` | Output directory (default: `./bookmarks-export-YYYY-MM-DD`). Must be empty unless `--force` is given. |
| `--browser NAME` | Only this browser: `firefox`, `chromium`, `brave`, `edge`, `opera`. Repeatable. |
| `--profile NAME` | Only profiles with this name, directory name or display name. Repeatable. |
| `--install TYPE` | Only this install type, such as `snap` or `native`. Repeatable. |
| `--no-json` | Do not write the JSON archives. |
| `--force` | Allow writing into a non-empty output directory. |

Exit codes: `0` success, `1` nothing exported or fatal error, `2` finished, but some profile failed or did not verify.

## Not exported

Favicons, history, passwords, extensions and Firefox smart bookmarks (`place:` queries). Opera Speed Dial entries become normal bookmarks after import. Items in the Opera or Chromium trash are skipped.

## Safety

* The tool never writes to any browser file. Firefox databases are copied to a temporary directory and the copy is read.
* Output files are created readable only by you (`0600`, in a `0700` folder).
* Every HTML file is parsed back and compared with the source (folder count and the exact list of URLs).

## Documentation

* [Usage and troubleshooting](docs/usage.md)
* [How it works](docs/how-it-works.md)
* [Importing on the new machine](docs/importing.md)
* [Output format reference](docs/output-format.md)
* [Development](docs/development.md)

## Status

The exporter is covered by unit tests with synthetic profiles modeled on real probe reports. Confirm your own result by checking that the command finishes with exit code `0` and that you can find your bookmarks after importing. Reports of browser versions that behave differently are welcome as issues.
