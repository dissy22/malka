# Malka — Personal Music Library Organizer

A modern desktop music library organizer built with Python (**PyQt6** + **Mutagen** + **SQLite**) and managed with **uv**. Current version: **1.0**.

---

## 🚀 Key Features

1. **Drag-and-Drop Album Import**:
   - Drag any album folder directly into the application window (or click **📥 Import Album** in the toolbar).
   - The library holds exactly four audio formats: **MP3**, **AAC (.m4a)**, **ALAC (.m4a)** and **FLAC**. APE and WavPack are accepted only as import sources.
   - The import dialog has three dependent controls — **Quality**, **Format** and **Resample to** — plus a **Library** selector when several library roots are configured:
     - **MP3 / M4A tracks** — only *Keep original lossy quality (no re-encoding)*;
     - **FLAC / ALAC tracks up to 48 kHz / 16-bit** — *Lossy quality* or *Keep original lossless quality (no re-encoding)*;
     - **FLAC / ALAC tracks above 48 kHz or 16-bit** — *Lossy quality*, *Lossless quality (resample)* or *Keep original Hi-Res quality (no resample)*;
     - **FLAC / ALAC image + CUE** — the same choices, always *and split into tracks*; the *Keep* mode splits with a lossless stream copy (no re-encoding at all);
     - **APE / WavPack image + CUE** — always split and converted; the *Keep original Hi-Res* mode re-encodes to FLAC/ALAC at the original resolution, because APE/WavPack cannot live in the library.
   - **Format** offers MP3 320 kbps / AAC 224 kbps for *Lossy*, FLAC / ALAC for *Lossless quality (resample)*, and is locked to the source format (or to FLAC/ALAC for APE/WavPack) for the *Keep* modes.
   - **Resample to** picks the ceiling (**44.1** or **48 kHz**) for the lossy and lossless-resample modes. Nothing is ever upsampled: a 44.1 kHz source stays 44.1 kHz even with a 48 kHz ceiling. Lossless resampling also reduces to 16-bit.
   - A live **summary** at the top shows the album, artist, year, source resolution, the exact operation that will be performed and the full destination folder.
   - The chosen settings are remembered per source type in `.malka/config.json` (`import_settings`).
   - **Stereo only**: files with more or fewer than 2 channels (mono, surround) are rejected with a clear error before anything is written.
   - All decoding/encoding is done by **FFmpeg** (bundled with the app through `imageio-ffmpeg`, or taken from `codecs/ffmpeg/` or `PATH`).
   - Files are placed directly into the library under the organized directory structure (`<Album Artist>/<Year> - <Album>/...`), verified on disk, and instantly added to the active library view without requiring a slow re-scan of the entire disk.

2. **First-Launch Library Setup**:
   - Prompts for your music library root folder on initial launch.
   - **Multiple library folders** are supported: add as many roots as you like from the toolbar or the Settings dialog. All roots are scanned, searched and played as one library.
   - Saves settings and paths to configuration (`.malka/config.json` next to the application).
   - Easily add or remove library directories at any time via the toolbar or Settings dialog.

3. **Metadata Tag Scanning (MP3, M4A/AAC, M4A/ALAC, FLAC)**:
   - Recursively scans all subfolders for audio files.
   - Extracts metadata tags:
     - `Album`
     - `Album Artist`
     - `Artist`
     - `Title`
     - `Year`
     - `Genre`
     - `Track Number` (formatted with leading zero: `01`, `02`, etc.)
     - `Disc Number` and `Total Discs` (`TPOS` for MP3, `disk` for M4A/AAC).
     - `Compilation` flag (`TCMP` for MP3, `cpil` for M4A/AAC).
     - Embedded Cover Art (APIC for MP3, `covr` for M4A/AAC).
   - Missing fields default to `"No data provided"`.
   - Caches cover thumbnails to disk for fast, smooth browsing.
   - Fast incremental scans: checks file modification time (`mtime`) to skip unchanged tracks.
   - Smart compilation detection: groups multi-artist albums under `"Various Artists"` instead of splitting them.

4. **Album Grid, Table View & Context Menu**:
   - Modern UI with square cover artwork, title, artist, release year, and disc count indicator (e.g. `2 CDs`).
   - **Tiles / Table** switcher next to the Artists / Albums / Genres switcher. The table view is sortable by clicking column headers; the tile view uses the **Sort** menu.
   - Sort options use arrows: **Artist + Year**, **Year ↑ / Year ↓**, **Title ↑ / Title ↓** for albums, and **Name ↑ / Name ↓** for artists and genres.
   - Real-time search filter across albums, artists, and years.
   - **Search tracks** mode searches inside track titles and file names:
     - results are shown as album tiles only;
     - matching track titles are overlaid on the cover;
     - Artists and Genres navigation is disabled while the mode is active;
     - an empty query does not trigger a pointless re-render.
   - Page selectors follow the active sort order: album initials for title sorting, the first three letters of the artist for “artist / year”, and the year range for year sorting.
   - **Right-Click Album Context Menu**:
     - **Edit album tags…**
     - **Fix tags encoding** (only when a problem was detected),
     - **Organize album files** (active only when required tags are valid),
     - **Open folder in file manager**,
     - **Remove album** — asks for confirmation and moves the files to the Windows Recycle Bin, then deletes their database records.
   - **Right-Click Artist Context Menu**: add/change/remove the artist image.
   - **Right-Click Track Context Menu** in the album view: edit tags, open file location, remove track (Recycle Bin + database record).
   - All context menus follow the active light/dark theme, use muted icons, dim disabled actions, and keep consistent spacing.

5. **Dual-Mode Tag Editor with online metadata and artwork**:
   - The editor is split into a **Tags** panel and a **Cover art** panel, matching the visual language of the main window.
   - **Album edit tab**: `Album`, `Album artist`, `Artist`, `Year / Genre`, `Total Discs`, `Compilation`, *Apply this Artist to all tracks in album*.
   - **Single track edit tab**: album track list plus `Title`, `Artist`, `Album`, `Album artist`, `Year / Genre`, `Track / Disc`, `Compilation`, and individual artwork.
   - **Reload** discards unsaved changes and restores the values loaded from the files.
   - **Save Changes** shows a modal progress window with the current file (`Writing tags: 03 - Song.flac (3/12)…`), database update status, and a final **Changes saved** message. Cover-only edits can be saved even when the album is not ready for automatic organization.
   - **Per-field Discogs lookups**: magnifier buttons next to the fields fill exactly one field, following the original CoverArtArchive-API-test rules:
     - Artist — Album + Year;
     - Album — Artist + Year;
     - Year — Artist + Album;
     - Album artist / Genre / Title — Artist + Album + Year;
     - Track / Disc — Artist + Album + Year + Title.
     - Multiple releases open **Choose release**, ambiguous tracks open **Choose track**, and multiple genres open **Choose genre**.
   - **Cover search is separate** from metadata lookup: the **Search for cover art online** button in the cover panel searches Discogs using Album / Artist / Year, shows the artwork gallery, and lets you pick a size (Original, 500, 600, 800, 1000, 1200). The chosen image is cached and embedded on save.
   - Downloadable artwork is cached in `.malka/covers`; the network work runs in background threads with a cancellable progress dialog.
   - **Discogs token** is optional. Add it in **Settings → Appearance** or set `DISCOGS_TOKEN` in the environment. Without a token the app uses the anonymous API rate limit.

6. **Organize Tracks and Folders**:
   - **Automatic layout check**: during every scan each track gets an `is_organized` flag. It is `true` only when the file already sits at
     `<Library>/<Album Artist>/<Year> - <Album>/<template>.<ext>` (with a `CD <n>` folder for multi-disc albums), where the template is the one configured in Settings (default `<track_no>. <title>`).
   - Album tiles containing at least one unorganized file show a **“Files need to be organized”** badge, and only those albums have the **Organize album files** context-menu action enabled.
   - **Organize preview dialog**: shows the target **library folder selector** (defaults to the library that actually holds the files) and, for every track, a `current path → new path` row, so the whole operation is visible before anything is touched. Files that are already in place are marked “already in place”.
   - The two columns are independent panes, each with its own horizontal scrollbar, so long paths can be read to the end on both sides.
   - The **“Show only differences”** checkbox (on by default) hides the shared path prefix and rows that need no change (the hidden prefix is shown above the list); switching it off shows the full paths for every track.
   - **Renaming & Relocation**:
     - For single-disc albums: `<Library>/<Album Artist>/<Year> - <Album>/`
     - For multi-disc albums: `<Library>/<Album Artist>/<Year> - <Album>/CD <disc_no>/`
     - For compilations: `<Library>/Various Artists/<Year> - <Album>/`
     - Renames files using a customizable template (default: `<track_no>. <title>.<ext>`, e.g. `01. Bohemian Rhapsody.mp3`), with support for `<disc_no>`, `<disc_total>`, and `<disc_and_track>` (e.g. `1-01`).
   - **Pre-validation**: all tracks must have `Album Artist`, `Year`, `Album`, `Track Number` and `Title`; otherwise the action is disabled with an explanation.
   - Moves files without collisions (auto-suffixing ` (1)`, ` (2)` …), cleans up empty source folders, updates paths and `is_organized` in SQLite so the badge disappears immediately.

7. **Artist Statistics**:
   - Artist rows use the artist's own image (set via the artist card context menu); artists without a photo show an initials avatar, never an album cover.

8. **Visual polish**:
   - The window/taskbar icon is the same music-note glyph shown in the title bar.
   - The toolbar is icon-only (labels are tooltips); the bundled glyphs are recoloured to match the muted “NOW PLAYING” caption (lighter on dark, darker on light).
   - **About** dialog (version 1.0): large Malka title, About/Author/Project sections, the author photo, contacts (email, Telegram), official site `dps.com.ru/malka`, a green **Support the project** button (Boosty), and the GPLv2 notice.
   - Album/artist/genre grids (and the album page) scroll under a soft fade, so covers melt into the navigation area instead of being cut by a hard edge; the fade only ramps in once the view is scrolled.
   - Artist avatars without a photo are drawn at the screen's physical resolution (crisp initials on HiDPI), and pixmap scaling goes through PIL's Lanczos filter.

9. **Settings Dialog** — three tabs:
   - **Library locations** — add/remove library roots and cached-image cleanup.
   - **Appearance** — light/dark theme, scrollbars, album-card badges, and the optional **Discogs token**.
   - **Naming templates** — renaming pattern with tokens (`<track_no>`, `<title>`, `<artist>`, `<album_artist>`, `<album>`, `<year>`) and a **live filename preview**.
   - Settings are stored in `.malka/config.json`.

10. **How the Discogs integration is built**:
   - `src/malka/discogs_client.py` — Discogs API client, release/master grouping, primary-artwork download, HTTP retries and rate-limit handling.
   - `src/malka/discogs_metadata.py` — release/tracklist lookup, field resolution, filename/title matching, and the release/track choice data.
   - `src/malka/discogs_models.py` — shared `CoverImage`, `CoverSearchResult`, `ReleaseCandidate`, and `TrackInfo` models.
   - `src/malka/discogs_imaging.py` — artwork decoding, centre-cropping, optional resizing, and JPEG/PNG encoding.
   - `src/malka/discogs_config.py` — API endpoint, timeout, rate-limit constants, and token lookup (environment first, then Settings).
   - `src/malka/ui/discogs_workers.py` — background cover/metadata workers.
   - `src/malka/ui/discogs_dialogs.py` — progress dialog, release/track/value chooser, and artwork gallery.
   - The tag editor calls these modules directly; it never blocks the UI thread on network work.

---

## 🛠️ Getting Started

### Prerequisites
- Python 3.14
- FFmpeg (bundled automatically via `imageio-ffmpeg`; a system/codecs copy is used when present)
- [uv](https://docs.astral.sh/uv/) package manager

### Running the Application
```bash
uv run malka
```
or:
```bash
uv run python -m malka.main
```

### Running Automated Tests
```bash
uv run python -m unittest discover -v -s tests
```

### Building the Windows Release

The supported distribution format is **onedir** — a small `Malka.exe` next to an
`_internal` folder with the Qt/Python libraries. It starts faster than a
single-file build because nothing is unpacked to a temporary folder on launch.

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean `
  --distpath dist_onedir --workpath build_onedir malka_onedir.spec
```

The result is `dist_onedir/Malka/`; copy that folder to
`release/Malka-portable/`. The app keeps its portable data in
`<app folder>/.malka/`, so the whole folder can be moved together with the
library configuration and database.

### Discogs token

Online metadata and artwork work anonymously, but the Discogs API rate limit is
low. For regular use, create a personal access token in
**Discogs → Settings → Developers** and either:

- paste it into **Settings → Appearance → Discogs token**, or
- set `$env:DISCOGS_TOKEN` before launching.

The token is stored locally in `.malka/config.json`; it is never sent anywhere
except the Discogs API.

---

## 📁 Project Architecture

```
Malka/
├── pyproject.toml              # uv project definitions and dependencies
├── README.md                   # Project documentation
├── src/
│   └── malka/
│       ├── __init__.py         # Package entrypoint
│       ├── main.py             # Application startup and Qt event loop
│       ├── config.py           # Configuration manager, defaults, import settings
│       ├── formats.py          # Library/import format rules and encoder arguments
│       ├── db.py               # SQLite database access (tracks, albums, cache)
│       ├── tags.py             # Mutagen tag reading/writing, cover embedding
│       ├── scanner.py          # Multithreaded background library scanner
│       ├── organizer.py        # Tag validation, file renaming, and moving
│       ├── discogs_client.py   # Discogs API, release grouping, artwork download
│       ├── discogs_metadata.py # Release/tracklist lookup and track matching
│       ├── discogs_models.py   # Shared online-search data models
│       ├── discogs_imaging.py  # Artwork crop/resize/encode
│       ├── discogs_config.py   # API endpoint, timeouts, token lookup
│       └── ui/
│           ├── __init__.py
│           ├── main_window.py      # Main window, navigation, grid/table, search
│           ├── album_card.py       # Album tile, cover, badges and context menu
│           ├── artist_card.py      # Artist tile and image context menu
│           ├── genre_card.py       # Genre tile
│           ├── flow_layout.py      # Responsive wrapping grid layout
│           ├── edit_dialog.py      # Tags + Cover editor and save progress
│           ├── import_dialog.py    # Import dialog (quality/format/resample)
│           ├── organize_dialog.py  # Organize preview: library choice + rename list
│           ├── settings_dialog.py  # Tabbed settings and Discogs token
│           ├── discogs_workers.py  # Background metadata/artwork requests
│           ├── discogs_dialogs.py  # Busy, choice and artwork-gallery dialogs
│           ├── menu_utils.py       # Shared themed context-menu styles
│           ├── about_dialog.py     # About Malka 1.0
│           └── library_dialogs.py  # Rescan-folder selection
└── tests/
    ├── test_core.py                # Tag reading/writing, validation, file moving
    ├── test_organization.py        # is_organized detection, preview plan, dialog
    ├── test_audio_quality.py       # stream info, Hi-Res badge, stereo validation
    ├── test_discogs.py             # Online-search model/helper tests
    ├── test_ui.py                  # Headless Qt UI tests
    └── test_library_operations.py  # End-to-end integration tests
```
