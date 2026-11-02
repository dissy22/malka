import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from malka.config import NO_DATA


# Regex to match EP and Single patterns at the end of album titles:
# Matches: " - EP", " - EP 1", " - EP 2", " - Deluxe EP", " - Deluxe EP 1", etc.
EP_PATTERN = re.compile(r"[-–—]\s*(?:deluxe\s+)?ep(?:\s+\d+)?\s*$", re.IGNORECASE)

# Matches: " - Single", " - Single 1", " - Deluxe Single", " - Deluxe Single 2", etc.
SINGLE_PATTERN = re.compile(r"[-–—]\s*(?:deluxe\s+)?single(?:\s+\d+)?\s*$", re.IGNORECASE)


def categorize_album(album_title: str) -> str:
    """
    Categorizes album title into 'album', 'ep', or 'single'.
    """
    if not album_title:
        return "album"
    t = album_title.strip()
    if EP_PATTERN.search(t):
        return "ep"
    if SINGLE_PATTERN.search(t):
        return "single"
    return "album"


def parse_year_int(year_val: Any) -> int:
    """
    Parses year string or integer into an int. Missing or invalid years return 999999.
    """
    if not year_val or year_val == NO_DATA:
        return 999999
    s = str(year_val).strip()
    m = re.search(r"\b(\d{4})\b", s)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)", s)
    if m:
        return int(m.group(1))
    return 999999


def album_sort_key(album: Dict[str, Any]) -> tuple:
    """
    Default sort key for albums: artist ascending, year ascending, title ascending.
    """
    art = str(album.get("display_artist") or album.get("album_artist", "")).strip().lower()
    y = parse_year_int(album.get("year"))
    alb = str(album.get("album", "")).strip().lower()
    return (art, y, alb)


def sort_albums(albums: List[Dict[str, Any]], mode: str = "artist_year") -> List[Dict[str, Any]]:
    """
    Sort albums based on mode:
    - 'artist_year': Artist (case-insensitive) ASC, Year ASC, Title (case-insensitive) ASC (Standard mode).
    - 'year_asc': Year ASC (unknown/missing years last), Artist ASC, Title ASC.
    - 'year_desc': Year DESC (unknown/missing years last), Artist ASC, Title ASC.
    - 'title_asc': Title ASC, Artist ASC, Year ASC.
    - 'title_desc': Title DESC, Artist DESC, Year DESC.
    """
    if mode == "year_asc":
        return sorted(albums, key=lambda a: (
            parse_year_int(a.get("year")),
            str(a.get("display_artist") or a.get("album_artist", "")).strip().lower(),
            str(a.get("album", "")).strip().lower()
        ))
    elif mode == "year_desc":
        return sorted(albums, key=lambda a: (
            1 if parse_year_int(a.get("year")) == 999999 else 0,
            -parse_year_int(a.get("year")) if parse_year_int(a.get("year")) != 999999 else 0,
            str(a.get("display_artist") or a.get("album_artist", "")).strip().lower(),
            str(a.get("album", "")).strip().lower()
        ))
    elif mode == "title_asc":
        return sorted(albums, key=lambda a: (
            str(a.get("album", "")).strip().lower(),
            str(a.get("display_artist") or a.get("album_artist", "")).strip().lower(),
            parse_year_int(a.get("year"))
        ))
    elif mode == "title_desc":
        return sorted(albums, key=lambda a: (
            str(a.get("album", "")).strip().lower(),
            str(a.get("display_artist") or a.get("album_artist", "")).strip().lower(),
            parse_year_int(a.get("year"))
        ), reverse=True)
    else:  # "artist_year" (standard mode)
        return sorted(albums, key=lambda a: (
            str(a.get("display_artist") or a.get("album_artist", "")).strip().lower(),
            parse_year_int(a.get("year")),
            str(a.get("album", "")).strip().lower()
        ))


def sort_artists(artists: List[Dict[str, Any]], mode: str = "name_asc") -> List[Dict[str, Any]]:
    """
    Sort artists based on mode:
    - 'name_asc': Artist name (case-insensitive) ASC.
    - 'name_desc': Artist name (case-insensitive) DESC.
    """
    if mode == "name_desc":
        return sorted(artists, key=lambda a: str(a.get("name", "")).strip().lower(), reverse=True)
    return sorted(artists, key=lambda a: str(a.get("name", "")).strip().lower())


def sort_genres(genres: List[Dict[str, Any]], mode: str = "name_asc") -> List[Dict[str, Any]]:
    """
    Sort genres based on mode:
    - 'name_asc': Genre name (case-insensitive) ASC.
    - 'name_desc': Genre name (case-insensitive) DESC.
    """
    if mode == "name_desc":
        return sorted(genres, key=lambda g: str(g.get("genre", "")).strip().lower(), reverse=True)
    return sorted(genres, key=lambda g: str(g.get("genre", "")).strip().lower())


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Keep the library database hot in RAM and avoid unnecessary fsyncs during
    # the many small read queries issued while browsing/rendering views.
    try:
        conn.execute("PRAGMA cache_size = -32768")  # ~32 MB page cache
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA mmap_size = 268435456")  # 256 MB
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album_artist TEXT NOT NULL,
                album TEXT NOT NULL,
                year TEXT NOT NULL,
                genre TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                track_no TEXT NOT NULL,
                disc_no TEXT NOT NULL DEFAULT '1',
                disc_total TEXT NOT NULL DEFAULT '1',
                compilation INTEGER NOT NULL DEFAULT 0,
                has_cover INTEGER NOT NULL DEFAULT 0,
                cover_cache_path TEXT,
                mtime REAL NOT NULL DEFAULT 0,
                duration REAL NOT NULL DEFAULT 0.0,
                bad_encoding INTEGER NOT NULL DEFAULT 0,
                is_organized INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_album_artist ON tracks(album, album_artist)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file_path ON tracks(file_path)")

        # Migration: ensure disc_no, disc_total, compilation, duration columns exist in existing tables
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(tracks)")
        cols = {row["name"] for row in cursor.fetchall()}
        if "disc_no" not in cols:
            cursor.execute("ALTER TABLE tracks ADD COLUMN disc_no TEXT NOT NULL DEFAULT '1'")
        if "disc_total" not in cols:
            cursor.execute("ALTER TABLE tracks ADD COLUMN disc_total TEXT NOT NULL DEFAULT '1'")
        if "compilation" not in cols:
            cursor.execute("ALTER TABLE tracks ADD COLUMN compilation INTEGER NOT NULL DEFAULT 0")
        if "duration" not in cols:
            cursor.execute("ALTER TABLE tracks ADD COLUMN duration REAL NOT NULL DEFAULT 0.0")
        if "bad_encoding" not in cols:
            cursor.execute("ALTER TABLE tracks ADD COLUMN bad_encoding INTEGER NOT NULL DEFAULT 0")
        if "comment" not in cols:
            cursor.execute("ALTER TABLE tracks ADD COLUMN comment TEXT NOT NULL DEFAULT ''")
        # These columns belonged to a short-lived experiment; stream info is now
        # read from the file on demand, so clean them up in existing databases.
        for stale_column in ("sample_rate", "bits_per_sample", "channels", "bitrate"):
            if stale_column in cols:
                try:
                    cursor.execute(f"ALTER TABLE tracks DROP COLUMN {stale_column}")
                except Exception:
                    pass
        if "is_organized" not in cols:
            cursor.execute("ALTER TABLE tracks ADD COLUMN is_organized INTEGER NOT NULL DEFAULT 0")

        # Staging table for album imports
        conn.execute("""
            CREATE TABLE IF NOT EXISTS import_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL,
                file_path TEXT,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album_artist TEXT NOT NULL,
                album TEXT NOT NULL,
                year TEXT NOT NULL,
                genre TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                track_no TEXT NOT NULL,
                disc_no TEXT NOT NULL DEFAULT '1',
                disc_total TEXT NOT NULL DEFAULT '1',
                compilation INTEGER NOT NULL DEFAULT 0,
                has_cover INTEGER NOT NULL DEFAULT 0,
                cover_cache_path TEXT,
                source_type TEXT NOT NULL DEFAULT 'files',
                cue_track_index INTEGER,
                cue_file_path TEXT,
                sample_rate INTEGER DEFAULT 44100,
                bits_per_sample INTEGER DEFAULT 16,
                duration REAL DEFAULT 0.0,
                index01 TEXT DEFAULT '',
                index00 TEXT DEFAULT '',
                bad_encoding INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Migration: ensure index01, index00, bad_encoding exist if table already existed
        try:
            conn.execute("ALTER TABLE import_tracks ADD COLUMN index01 TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE import_tracks ADD COLUMN index00 TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE import_tracks ADD COLUMN bad_encoding INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE import_tracks ADD COLUMN comment TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass

        # Table for custom artist images
        conn.execute("""
            CREATE TABLE IF NOT EXISTS artists (
                name TEXT PRIMARY KEY,
                image_path TEXT
            )
        """)

        conn.commit()


def upsert_track(conn: sqlite3.Connection, track: Dict[str, Any]) -> None:
    # Ensure defaults for disc fields if not present
    data = dict(track)
    data.setdefault("disc_no", "1")
    data.setdefault("disc_total", "1")
    data.setdefault("compilation", 0)
    data.setdefault("duration", 0.0)
    data.setdefault("bad_encoding", 0)
    data.setdefault("is_organized", 0)
    data.setdefault("comment", "")

    conn.execute("""
        INSERT INTO tracks (
            file_path, title, artist, album_artist, album, year, genre, comment,
            track_no, disc_no, disc_total, compilation, has_cover, cover_cache_path, mtime, duration,
            bad_encoding, is_organized
        ) VALUES (
            :file_path, :title, :artist, :album_artist, :album, :year, :genre, :comment,
            :track_no, :disc_no, :disc_total, :compilation, :has_cover, :cover_cache_path, :mtime, :duration,
            :bad_encoding, :is_organized
        )
        ON CONFLICT(file_path) DO UPDATE SET
            title = excluded.title,
            artist = excluded.artist,
            album_artist = excluded.album_artist,
            album = excluded.album,
            year = excluded.year,
            genre = excluded.genre,
            comment = excluded.comment,
            track_no = excluded.track_no,
            disc_no = excluded.disc_no,
            disc_total = excluded.disc_total,
            compilation = excluded.compilation,
            has_cover = excluded.has_cover,
            cover_cache_path = excluded.cover_cache_path,
            mtime = excluded.mtime,
            duration = excluded.duration,
            bad_encoding = excluded.bad_encoding,
            is_organized = excluded.is_organized
    """, data)


def update_track_duration(conn: sqlite3.Connection, file_path: str, duration: float) -> None:
    try:
        conn.execute("UPDATE tracks SET duration = ? WHERE file_path = ?", (duration, file_path))
        conn.commit()
    except Exception:
        pass


def get_all_albums(conn: sqlite3.Connection, sort_mode: str = "artist_year") -> List[Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            album,
            album_artist,
            COUNT(*) as track_count,
            (
                SELECT year FROM tracks t2 
                WHERE t2.album = t1.album AND t2.album_artist = t1.album_artist AND t2.year != ?
                LIMIT 1
            ) as valid_year,
            (
                SELECT artist FROM tracks t3
                WHERE t3.album = t1.album AND t3.album_artist = t1.album_artist AND t3.artist != ?
                LIMIT 1
            ) as sample_artist,
            (
                SELECT cover_cache_path FROM tracks t4 
                WHERE t4.album = t1.album AND t4.album_artist = t1.album_artist AND t4.has_cover = 1 
                LIMIT 1
            ) as cover_path,
            MAX(CAST(disc_total AS INTEGER)) as max_disc_total,
            COUNT(DISTINCT disc_no) as disc_count,
            MAX(compilation) as is_compilation,
            MAX(bad_encoding) as has_bad_encoding,
            MIN(is_organized) as all_organized
        FROM tracks t1
        GROUP BY album, album_artist
        ORDER BY 
            album_artist COLLATE NOCASE ASC,
            CASE 
                WHEN valid_year GLOB '[0-9][0-9][0-9][0-9]*' THEN CAST(SUBSTR(valid_year, 1, 4) AS INTEGER)
                WHEN valid_year GLOB '[0-9]*' THEN CAST(valid_year AS INTEGER)
                ELSE 999999
            END ASC,
            album COLLATE NOCASE ASC
    """, (NO_DATA, NO_DATA))

    albums = []
    for row in cursor.fetchall():
        year = row["valid_year"] or NO_DATA
        artist = row["album_artist"]
        if artist == NO_DATA:
            artist = row["sample_artist"] or NO_DATA
        disc_cnt = max(row["disc_count"] or 1, row["max_disc_total"] or 1)
        albums.append({
            "album": row["album"],
            "album_artist": row["album_artist"],
            "display_artist": artist,
            "year": year,
            "track_count": row["track_count"],
            "cover_path": row["cover_path"] or "",
            "disc_count": disc_cnt,
            "is_compilation": bool(row["is_compilation"]),
            "has_bad_encoding": bool(row["has_bad_encoding"]),
            "is_organized": bool(row["all_organized"]),
        })
    return sort_albums(albums, mode=sort_mode)


def get_album_tracks(conn: sqlite3.Connection, album: str, album_artist: str) -> List[Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM tracks
        WHERE album = ? AND album_artist = ?
        ORDER BY 
            CASE 
                WHEN disc_no GLOB '[0-9]*' THEN CAST(disc_no AS INTEGER)
                ELSE 1 
            END,
            CASE 
                WHEN track_no GLOB '[0-9]*' THEN CAST(track_no AS INTEGER)
                ELSE 999999 
            END,
            track_no ASC,
            title ASC
    """, (album, album_artist))
    return [dict(row) for row in cursor.fetchall()]


def update_track(conn: sqlite3.Connection, track_id: int, data: Dict[str, Any]) -> None:
    set_clause = ", ".join(f"{k} = :{k}" for k in data.keys())
    params = dict(data)
    params["id"] = track_id
    conn.execute(f"UPDATE tracks SET {set_clause} WHERE id = :id", params)


def update_file_path(conn: sqlite3.Connection, track_id: int, new_path: str) -> None:
    conn.execute("UPDATE tracks SET file_path = ? WHERE id = ?", (new_path, track_id))


def set_track_organized(conn: sqlite3.Connection, track_id: int, organized: int) -> None:
    try:
        conn.execute("UPDATE tracks SET is_organized = ? WHERE id = ?", (1 if organized else 0, int(track_id)))
    except Exception:
        pass


def delete_missing_tracks(conn: sqlite3.Connection, existing_paths: set) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT id, file_path FROM tracks")
    rows = cursor.fetchall()
    deleted = 0
    for row in rows:
        if row["file_path"] not in existing_paths:
            cursor.execute("DELETE FROM tracks WHERE id = ?", (row["id"],))
            deleted += 1
    conn.commit()
    return deleted


def get_cached_mtimes(conn: sqlite3.Connection) -> Dict[str, float]:
    cursor = conn.cursor()
    cursor.execute("SELECT file_path, mtime FROM tracks")
    return {row["file_path"]: row["mtime"] for row in cursor.fetchall()}


def clear_import_tracks(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM import_tracks")
    conn.commit()


def insert_import_track(conn: sqlite3.Connection, track: Dict[str, Any]) -> int:
    cur = conn.execute("""
        INSERT INTO import_tracks (
            source_path, file_path, title, artist, album_artist, album,
            year, genre, track_no, disc_no, disc_total, compilation,
            has_cover, cover_cache_path, source_type, cue_track_index,
            cue_file_path, sample_rate, bits_per_sample, duration,
            index01, index00, bad_encoding
        ) VALUES (
            :source_path, :file_path, :title, :artist, :album_artist, :album,
            :year, :genre, :track_no, :disc_no, :disc_total, :compilation,
            :has_cover, :cover_cache_path, :source_type, :cue_track_index,
            :cue_file_path, :sample_rate, :bits_per_sample, :duration,
            :index01, :index00, :bad_encoding
        )
    """, {
        "source_path": track.get("source_path", track.get("file_path", "")),
        "file_path": track.get("file_path", ""),
        "title": track.get("title", NO_DATA),
        "artist": track.get("artist", NO_DATA),
        "album_artist": track.get("album_artist", NO_DATA),
        "album": track.get("album", NO_DATA),
        "year": track.get("year", NO_DATA),
        "genre": track.get("genre", NO_DATA),
        "track_no": track.get("track_no", NO_DATA),
        "disc_no": track.get("disc_no", "1"),
        "disc_total": track.get("disc_total", "1"),
        "compilation": int(track.get("compilation", 0)),
        "has_cover": int(track.get("has_cover", 0)),
        "cover_cache_path": track.get("cover_cache_path", ""),
        "source_type": track.get("source_type", "files"),
        "cue_track_index": track.get("cue_track_index"),
        "cue_file_path": track.get("cue_file_path"),
        "sample_rate": int(track.get("sample_rate", 44100)),
        "bits_per_sample": int(track.get("bits_per_sample", 16)),
        "duration": float(track.get("duration", 0.0)),
        "index01": track.get("index01", ""),
        "index00": track.get("index00", ""),
        "bad_encoding": int(track.get("bad_encoding", 0)),
    })
    conn.commit()
    return cur.lastrowid


def get_import_tracks(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cursor = conn.execute("""
        SELECT * FROM import_tracks
        ORDER BY CAST(disc_no AS INTEGER) ASC, CAST(track_no AS INTEGER) ASC, id ASC
    """)
    return [dict(row) for row in cursor.fetchall()]


def update_import_track(conn: sqlite3.Connection, track_id: int, updates: Dict[str, Any]) -> None:
    set_clauses = []
    values = {"id": track_id}
    for k, v in updates.items():
        set_clauses.append(f"{k} = :{k}")
        values[k] = v
    if set_clauses:
        conn.execute(f"UPDATE import_tracks SET {', '.join(set_clauses)} WHERE id = :id", values)
        conn.commit()


def set_artist_image(conn: sqlite3.Connection, artist_name: str, image_path: Optional[str]) -> None:
    if image_path:
        conn.execute("""
            INSERT INTO artists (name, image_path)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET image_path = excluded.image_path
        """, (artist_name, image_path))
    else:
        conn.execute("DELETE FROM artists WHERE name = ?", (artist_name,))
    conn.commit()


def get_artist_image(conn: sqlite3.Connection, artist_name: str) -> Optional[str]:
    cursor = conn.cursor()
    cursor.execute("SELECT image_path FROM artists WHERE name = ?", (artist_name,))
    row = cursor.fetchone()
    return row["image_path"] if row else None


def get_all_artists(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            a.artist_name,
            a.album_count,
            a.track_count,
            a.sample_cover,
            art.image_path
        FROM (
            SELECT 
                CASE 
                    WHEN album_artist IS NOT NULL AND album_artist != '' AND album_artist != ? THEN album_artist 
                    ELSE artist 
                END as artist_name,
                COUNT(DISTINCT album) as album_count,
                COUNT(*) as track_count,
                (
                    SELECT cover_cache_path FROM tracks t2 
                    WHERE (t2.album_artist = t1.album_artist OR (t1.album_artist = ? AND t2.artist = t1.artist))
                      AND t2.has_cover = 1 
                    LIMIT 1
                ) as sample_cover
            FROM tracks t1
            WHERE (album_artist != '' AND album_artist != ?) 
               OR (artist != '' AND artist != ?)
            GROUP BY artist_name
        ) a
        LEFT JOIN artists art ON art.name = a.artist_name
        ORDER BY a.artist_name COLLATE NOCASE ASC
    """, (NO_DATA, NO_DATA, NO_DATA, NO_DATA))

    result = []
    for row in cursor.fetchall():
        result.append({
            "name": row["artist_name"],
            "album_count": row["album_count"],
            "track_count": row["track_count"],
            "image_path": row["image_path"] or "",
            "sample_cover": row["sample_cover"] or "",
        })
    return result


def get_all_genres(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            genre,
            COUNT(DISTINCT album) as album_count,
            COUNT(*) as track_count,
            (
                SELECT cover_cache_path FROM tracks t2 
                WHERE t2.genre = t1.genre AND t2.has_cover = 1 
                LIMIT 1
            ) as sample_cover
        FROM tracks t1
        WHERE genre IS NOT NULL AND genre != '' AND genre != ?
        GROUP BY genre
        ORDER BY genre COLLATE NOCASE ASC
    """, (NO_DATA,))

    result = []
    for row in cursor.fetchall():
        result.append({
            "genre": row["genre"],
            "album_count": row["album_count"],
            "track_count": row["track_count"],
            "sample_cover": row["sample_cover"] or "",
        })
    return result


def get_albums_by_artist(conn: sqlite3.Connection, artist_name: str, sort_mode: str = "artist_year") -> List[Dict[str, Any]]:
    all_albums = get_all_albums(conn, sort_mode=sort_mode)
    target = artist_name.strip().lower()
    res = [
        a for a in all_albums
        if a["album_artist"].strip().lower() == target or a["display_artist"].strip().lower() == target
    ]
    return sort_albums(res, mode=sort_mode)


def get_albums_by_genre(conn: sqlite3.Connection, genre_name: str, sort_mode: str = "artist_year") -> List[Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT album, album_artist
        FROM tracks
        WHERE LOWER(genre) = LOWER(?)
    """, (genre_name,))
    matches = {(row["album"].strip().lower(), row["album_artist"].strip().lower()) for row in cursor.fetchall()}
    all_albums = get_all_albums(conn, sort_mode=sort_mode)
    res = [a for a in all_albums if (a["album"].strip().lower(), a["album_artist"].strip().lower()) in matches]
    return sort_albums(res, mode=sort_mode)


def get_artist_statistics(conn: sqlite3.Connection, sort_by: str = "tracks") -> List[Dict[str, Any]]:
    """
    Returns artists ranked by track_count or album_count descending.
    Includes artist_name, track_count, album_count, and artist image_path from artists table.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            CASE 
                WHEN album_artist IS NOT NULL AND album_artist != '' AND album_artist != ? THEN album_artist 
                ELSE artist 
            END as artist_name,
            COUNT(*) as track_count,
            COUNT(DISTINCT album) as album_count,
            (
                SELECT cover_cache_path FROM tracks t2 
                WHERE (t2.album_artist = t1.album_artist OR t2.artist = t1.artist) AND t2.has_cover = 1 
                LIMIT 1
            ) as sample_cover
        FROM tracks t1
        WHERE (album_artist != ? AND album_artist != '') OR (artist != ? AND artist != '')
        GROUP BY artist_name
    """, (NO_DATA, NO_DATA, NO_DATA))

    rows = cursor.fetchall()
    cursor.execute("SELECT name, image_path FROM artists WHERE image_path IS NOT NULL AND image_path != ''")
    img_map = {r["name"]: r["image_path"] for r in cursor.fetchall()}

    result = []
    from malka.tags import detect_and_fix_encoding
    for r in rows:
        name = r["artist_name"]
        _, clean_name = detect_and_fix_encoding(name)
        img = img_map.get(name) or img_map.get(clean_name)
        result.append({
            "artist_name": clean_name,
            "raw_artist_name": name,
            "track_count": int(r["track_count"]),
            "album_count": int(r["album_count"]),
            "image_path": img,
            "sample_cover": r["sample_cover"] or "",
        })

    if sort_by == "albums":
        result.sort(key=lambda x: (-x["album_count"], -x["track_count"], x["artist_name"].lower()))
    else:
        result.sort(key=lambda x: (-x["track_count"], -x["album_count"], x["artist_name"].lower()))

    return result


def get_album_statistics(conn: sqlite3.Connection, sort_by: str = "tracks") -> List[Dict[str, Any]]:
    """
    Returns albums ranked by track_count descending.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            album,
            album_artist,
            COUNT(*) as track_count,
            (
                SELECT year FROM tracks t2 
                WHERE t2.album = t1.album AND t2.album_artist = t1.album_artist AND t2.year != ?
                LIMIT 1
            ) as year,
            (
                SELECT cover_cache_path FROM tracks t3 
                WHERE t3.album = t1.album AND t3.album_artist = t1.album_artist AND t3.has_cover = 1 
                LIMIT 1
            ) as cover_path
        FROM tracks t1
        WHERE album != ? AND album != ''
        GROUP BY album, album_artist
        ORDER BY track_count DESC, album COLLATE NOCASE ASC
    """, (NO_DATA, NO_DATA))

    result = []
    from malka.tags import detect_and_fix_encoding
    for r in cursor.fetchall():
        _, clean_album = detect_and_fix_encoding(r["album"])
        _, clean_artist = detect_and_fix_encoding(r["album_artist"])
        result.append({
            "album": clean_album,
            "raw_album": r["album"],
            "album_artist": clean_artist,
            "raw_album_artist": r["album_artist"],
            "track_count": int(r["track_count"]),
            "year": r["year"] or "",
            "cover_path": r["cover_path"] or "",
        })
    return result


def get_album_decade_statistics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Groups albums by decade starting from 1900 (10-year intervals: 1900s, 1910s, ..., 2020s, Other).
    Returns list of decade stats with album counts, percentages, and album items.
    """
    albums = get_album_statistics(conn)
    total_albums = len(albums)
    if total_albums == 0:
        return {"total_albums": 0, "decades": []}

    decade_buckets: Dict[str, List[Dict[str, Any]]] = {}

    for a in albums:
        y_str = str(a.get("year", "")).strip()
        y_match = re.search(r"\b(\d{4})\b", y_str)
        if y_match:
            year = int(y_match.group(1))
            if year >= 1900:
                dec = (year // 10) * 10
                key = f"{dec}s"
            else:
                key = "Pre-1900"
        else:
            key = "Unknown"

        if key not in decade_buckets:
            decade_buckets[key] = []
        decade_buckets[key].append(a)

    def _decade_sort_key(k: str) -> int:
        if k.endswith("s") and k[:-1].isdigit():
            return int(k[:-1])
        if k == "Pre-1900":
            return 1800
        return 9999

    sorted_keys = sorted(decade_buckets.keys(), key=_decade_sort_key)
    decades = []
    for k in sorted_keys:
        albs = decade_buckets[k]
        cnt = len(albs)
        pct = (cnt / total_albums) * 100.0 if total_albums > 0 else 0.0
        decades.append({
            "decade": k,
            "album_count": cnt,
            "percentage": pct,
            "albums": albs,
        })

    return {
        "total_albums": total_albums,
        "decades": decades,
    }


def get_genre_statistics(conn: sqlite3.Connection, sort_by: str = "tracks") -> List[Dict[str, Any]]:
    """
    Returns genres ranked by track_count or album_count descending.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            genre,
            COUNT(*) as track_count,
            COUNT(DISTINCT album) as album_count,
            (
                SELECT cover_cache_path FROM tracks t2 
                WHERE t2.genre = t1.genre AND t2.has_cover = 1 
                LIMIT 1
            ) as sample_cover
        FROM tracks t1
        WHERE genre IS NOT NULL AND genre != '' AND genre != ?
        GROUP BY genre
    """, (NO_DATA,))

    result = []
    from malka.tags import detect_and_fix_encoding
    for r in cursor.fetchall():
        _, clean_genre = detect_and_fix_encoding(r["genre"])
        result.append({
            "genre": clean_genre,
            "raw_genre": r["genre"],
            "track_count": int(r["track_count"]),
            "album_count": int(r["album_count"]),
            "sample_cover": r["sample_cover"] or "",
        })

    if sort_by == "albums":
        result.sort(key=lambda x: (-x["album_count"], -x["track_count"], x["genre"].lower()))
    else:
        result.sort(key=lambda x: (-x["track_count"], -x["album_count"], x["genre"].lower()))

    return result

