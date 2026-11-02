# Malka — Personal Music Library Organizer

A modern desktop music library organizer built with Python (**PyQt6** + **Mutagen** + **SQLite**) and managed with **uv**.

---

## 🚀 Key Features

1. **Drag-and-Drop Album Import**:
   - Drag any album folder directly into the application window (or click **📥 Import Album** in the toolbar).
   - Automatically analyzes folder contents and categorizes the import into one of two modes:
     - **Variant 1 (Direct Audio Files)**: Folder containing `.mp3`, `.m4a`, or individual `.flac` files with embedded tags. Reads all tags and folder artwork (`folder.jpg`, `cover.jpg`, etc.), stages them in SQLite (`import_tracks`), and opens the **Import Dialog**.
     - **Variant 2 (FLAC + CUE Image Conversion)**: Folder with a single `*.flac` image file and a `*.cue` sheet (or `*.m3u` / embedded cuesheet). Parses the cuesheet into tracklist metadata, prompts for tag review in the **Import Dialog**, and on confirmation automatically splits and encodes the audio into `.m4a` using **QAAC** (`qaac64.exe -v 224`).
     - **Smart Resampling & Bit Depth**:
       - 44.1 kHz and 48 kHz (16-bit): kept as-is without resampling.
       - Rates above 48 kHz: intelligently resampled to **44.1 kHz** (for 88.2 kHz, 176.4 kHz multiples) or **48 kHz** (for 96 kHz, 192 kHz multiples), quantized to 16-bit with dither.
     - Files are placed directly into the library under the organized directory structure (`<Album Artist>/<Year> - <Album>/...`), verified on disk, and instantly added to the active library view without requiring a slow re-scan of the entire disk.

2. **First-Launch Library Setup**:
   - Prompts for your music library root folder on initial launch.
   - **Multiple library folders** are supported: add as many roots as you like from the toolbar or the Settings dialog. All roots are scanned, searched and played as one library.
   - Saves settings and paths to configuration (`.malka/config.json` next to the application).
   - Easily add or remove library directories at any time via the toolbar or Settings dialog.

2. **Metadata Tag Scanning (MP3, M4A, AAC)**:
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
   - **Pre-validation**: Ensures all tracks in the album have `Album Artist`, `Year`, `Album`, `Track Number`, and `Title` filled (not empty and not `"No data provided"`). If any tag is missing, the organize action is disabled.
   - **Renaming & Relocation**:
     - For single-disc albums: `<Library>/<Album Artist>/<Year> - <Album>/`
     - For multi-disc albums: `<Library>/<Album Artist>/<Year> - <Album>/CD <disc_no>/`
     - For compilations: `<Library>/Various Artists/<Year> - <Album>/`
     - Renames files using a customizable template (default: `<track_no>. <title>.<ext>`, e.g. `01. Bohemian Rhapsody.mp3`), with support for `<disc_no>`, `<disc_total>`, and `<disc_and_track>` (e.g. `1-01`).
     - Moves files into the organized structure without collisions.
     - Safely cleans up empty source directories.
     - Updates file paths in the SQLite database.
     - Renames files using a customizable template (default: `<track_no>. <title>.<ext>`, e.g. `01. Bohemian Rhapsody.mp3`).
     - Moves files into the organized structure.
     - Safely cleans up empty source directories.
     - Updates file paths in the SQLite database.

6. **Settings Dialog**:
   - Change music library directory.
   - Customize renaming pattern with template tokens (`<track_no>`, `<title>`, `<artist>`, `<album_artist>`, `<album>`, `<year>`) and **live filename preview**.

---

## 🛠️ Getting Started

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
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
│       ├── config.py           # Configuration manager and defaults
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
│           └── settings_dialog.py  # Settings dialog with live template preview
└── tests/
    ├── test_core.py                # Tag reading/writing, validation, and file moving
    ├── test_ui.py                  # Headless Qt UI tests
    └── test_library_operations.py  # End-to-end integration tests
```
