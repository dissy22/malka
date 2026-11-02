# Malka — Personal Music Library Organizer

A modern desktop music library organizer built with Python (**PyQt6** + **Mutagen** + **SQLite**) and managed with **uv**.

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

2. **Metadata Tag Scanning (MP3, M4A/AAC, M4A/ALAC, FLAC)**:
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

3. **Album Grid & Context Menu**:
   - Modern dark UI displaying album cards with square cover artwork, title, artist, release year, and disc count indicator (e.g. `2 CDs`).
   - Real-time search filter across albums, artists, and years.
   - Page selectors follow the active sort order: album initials for title sorting, the first three letters of the artist for “artist / year”, and the year range for year sorting.
   - **Right-Click Album Context Menu**:
     - **Edit Album & Tracks** (opens dual-mode edit dialog).
     - **Organize tracks and folders names** (active only when required tags are valid).
     - **Open in File Explorer**.

4. **Dual-Mode Tag Editor**:
   - **Album edit tab**:
     - Fields: `Album`, `Album artist`, `Artist`, `Year`, `Genre`, `Total Discs`.
     - Checkbox: *Compilation (Various Artists album)*.
     - Checkbox: *Apply this Artist to all tracks in album*.
     - Square artwork preview with *Add Cover* (file picker) and *Delete Cover* buttons.
   - **Single track edit tab**:
     - List of album tracks showing disc badges for multi-disc releases (e.g. `[CD 1] 01. ...`, `[CD 2] 01. ...`).
     - Per-track editing for `Disc Number`, `Total Discs`, `Track Number`, `Title`, `Artist`, `Album Artist`, `Album`, `Year`, `Genre`, and individual cover artwork.
   - Action buttons: *Save Changes* (writes tags to disk using Mutagen and updates SQLite) and *Cancel*.

5. **Organize Tracks and Folders**:
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

6. **Artist Statistics**:
   - Artist rows use the artist's own image (set via the artist card context menu); artists without a photo show an initials avatar, never an album cover.

7. **Visual polish**:
   - The window/taskbar icon is the same music-note glyph shown in the title bar.
   - The toolbar is icon-only (labels are tooltips); the bundled glyphs are recoloured to match the muted “NOW PLAYING” caption (lighter on dark, darker on light).
   - **About** dialog: description, contacts (Pavel Distrianov, email, Telegram), official site `dps.com.ru/malka`, a “Поддержать проект” button (Boosty) and the GPLv2 license notice.
   - Album/artist/genre grids (and the album page) scroll under a soft fade, so covers melt into the navigation area instead of being cut by a hard edge; the fade only ramps in once the view is scrolled.
   - Artist avatars without a photo are drawn at the screen's physical resolution (crisp initials on HiDPI), and pixmap scaling goes through PIL's Lanczos filter.

8. **Settings Dialog**:
   - Show or hide the album-card badges (“files need to be organized”, “bad tags encoding”) for users who prefer a clean grid.
   - Change music library directory.
   - Customize renaming pattern with template tokens (`<track_no>`, `<title>`, `<artist>`, `<album_artist>`, `<album>`, `<year>`) and **live filename preview**.

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
│       ├── tags.py             # Mutagen tag reading and writing (MP3, M4A)
│       ├── scanner.py          # Multithreaded background library scanner
│       ├── organizer.py        # Tag validation, file renaming, and moving
│       └── ui/
│           ├── __init__.py
│           ├── main_window.py      # Main window (toolbar, search, cards, status)
│           ├── album_card.py       # Album card widget with thumbnail and menu
│           ├── flow_layout.py      # Responsive wrapping grid layout
│           ├── edit_dialog.py      # Dual-mode album and track tag editor
│           ├── import_dialog.py    # Import dialog (quality/format/resample)
│           ├── organize_dialog.py  # Organize preview: library choice + rename list
│           └── settings_dialog.py  # Settings dialog with live template preview
└── tests/
    ├── test_core.py                # Tag reading/writing, validation, and file moving
    ├── test_organization.py        # is_organized detection, preview plan, dialog
    ├── test_audio_quality.py       # stream info, Hi-Res badge, stereo validation
    ├── test_ui.py                  # Headless Qt UI tests
    └── test_library_operations.py  # End-to-end integration tests
```
