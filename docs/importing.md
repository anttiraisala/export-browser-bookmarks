# Importing on the new machine

Each `.html` file in the export folder is a standard Netscape bookmark file. Import it into the matching browser and profile.

The generated `IMPORT.md` in the export folder lists the files and steps for exactly the browsers that were exported. Menu names differ a little between browser versions, so treat these steps as a guide.

## Before you start

1. Install the browsers and start each one once so that it creates its profile.
2. Sign in to sync accounts only after importing, or decide beforehand which source wins. Importing into a profile that already syncs the same bookmarks creates duplicates.
3. Pick the right file. Profile names are in the file names, for example `chromium_Default.html` for the Chromium profile "Default".

## Firefox

1. Press `Ctrl+Shift+O` to open the Library.
2. Choose **Import and Backup**, then **Import Bookmarks from HTML...**
3. Select the Firefox `.html` file.

Folders, tags, separators and the toolbar folder are restored. Firefox places the content in the matching roots (toolbar, menu, other bookmarks).

## Chromium

1. Open `chrome://bookmarks` and use the three-dot menu in the top right.
2. Choose **Import bookmarks** and select the Chromium `.html` file.

An alternative is `chrome://settings/importData`, then **Bookmarks HTML file**.

## Brave

1. Open `brave://settings/importData`.
2. Choose **Bookmarks HTML File** as the source and select the Brave `.html` file.

## Microsoft Edge

1. Open `edge://settings/profiles/importBrowsingData`.
2. Choose the bookmarks HTML file as the source and select the Edge `.html` file.

## Opera

1. Open `opera://settings/importData`.
2. Choose **Bookmarks HTML file** and select the Opera `.html` file.

Opera Speed Dial entries arrive as normal bookmarks in a folder named "Speed Dial". Pin them to Speed Dial again if you want them there.

## After importing

* Chromium-based browsers often put imported bookmarks in a new folder such as "Imported". Drag the contents where you want them.
* Compare a few folders with the old machine. The counts in `manifest.json` are the numbers to compare against.
* Delete the export folder when you are done. It contains your bookmarks in plain text.

## Why there is no command-line import

Writing bookmarks directly into a browser profile is fragile: Chromium-family browsers keep a checksum in the `Bookmarks` file and rewrite it while running, and Firefox keeps recent state in a write-ahead log. A wrong write can corrupt the profile. The browsers' own HTML importers are stable, so the tool leaves import to them.
