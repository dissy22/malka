"""
High-quality, high-performance image utilities for Malka UI.
Features:
- In-memory QPixmap caching for instant (0ms) re-renders
- Persistent disk thumbnail caching (~/.malka/thumbnails)
- Asynchronous background thumbnail generation via QThreadPool (zero UI freezing)
- High-DPI aware (devicePixelRatio) with Lanczos resampling for razor-sharp artwork
"""
import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from PIL import Image
from PyQt6.QtCore import QObject, QRectF, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPixmap

from malka.config import THUMBNAILS_CACHE_DIR, config

# In-memory caches
_MEMORY_PIXMAP_CACHE: Dict[Tuple[str, float, int, int, float], QPixmap] = {}
_PLACEHOLDER_CACHE: Dict[Tuple[int, str, int, float, str, str, bool], QPixmap] = {}
_RESOURCE_PIXMAP_CACHE: Dict[Tuple[str, int, int, float, str], QPixmap] = {}
_RESOURCE_ICON_CACHE: Dict[Tuple[str, int, str], QIcon] = {}

# Source path -> mtime. Once a thumbnail is in RAM we must not hit the disk just
# to stat the source again on every card re-render/navigation.
_SOURCE_MTIME_CACHE: Dict[str, float] = {}
_THUMBNAILS_DIR_READY = False
# Thumbnail decoding is CPU/disk heavy. A small dedicated pool keeps the GUI
# thread responsive instead of competing with dozens of eager conversions.
_THUMBNAIL_POOL: Optional[QThreadPool] = None
ARTIST_IMAGE_SIZE = 340


def _path_key(file_path: Union[str, Path]) -> str:
    """Fast normalized path key that does not touch the filesystem."""
    try:
        return os.path.normcase(os.path.abspath(str(file_path)))
    except Exception:
        return str(file_path)


def _get_source_mtime(file_path: Union[str, Path]) -> Optional[float]:
    key = _path_key(file_path)
    cached = _SOURCE_MTIME_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        mtime = Path(file_path).stat().st_mtime
    except Exception:
        return None
    _SOURCE_MTIME_CACHE[key] = mtime
    return mtime


def invalidate_image_cache(file_path: Optional[Union[str, Path]] = None) -> None:
    """Drops RAM entries for one source path (or everything when path is None)."""
    if file_path is None:
        _MEMORY_PIXMAP_CACHE.clear()
        _SOURCE_MTIME_CACHE.clear()
        return
    key = _path_key(file_path)
    _SOURCE_MTIME_CACHE.pop(key, None)
    for cache_key in list(_MEMORY_PIXMAP_CACHE.keys()):
        if cache_key[0] == key:
            _MEMORY_PIXMAP_CACHE.pop(cache_key, None)


def save_square_artist_image(source_path: Union[str, Path], dest_path: Union[str, Path], size: int = ARTIST_IMAGE_SIZE) -> bool:
    """
    Center-crops and resizes an artist image to a small square file.

    Artist photos are displayed at most ~340 px, so keeping multi-megabyte
    originals on disk and decoding them on every navigation is wasted work.
    """
    try:
        src = Path(source_path)
        dest = Path(dest_path)
        if not src.exists():
            return False
        with Image.open(str(src)) as img:
            img = img.convert("RGBA")
            w, h = img.size
            min_dim = min(w, h)
            if min_dim <= 0:
                return False
            left = (w - min_dim) // 2
            top = (h - min_dim) // 2
            resized = img.crop((left, top, left + min_dim, top + min_dim))
            resized = resized.resize((size, size), Image.Resampling.LANCZOS)

            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".tmp")
            ext = dest.suffix.lower()
            if ext == ".png":
                resized.save(str(tmp), format="PNG", optimize=True)
            elif ext == ".webp":
                resized.save(str(tmp), format="WEBP", quality=90, method=4)
            else:
                alpha = resized.getchannel("A")
                if alpha.getextrema()[0] < 255:
                    bg = Image.new("RGB", (size, size), (18, 22, 28))
                    bg.paste(resized, mask=alpha)
                    bg.save(str(tmp), format="JPEG", quality=92, optimize=True)
                else:
                    resized.convert("RGB").save(str(tmp), format="JPEG", quality=92, optimize=True)
            os.replace(str(tmp), str(dest))
        invalidate_image_cache(dest)
        return True
    except Exception:
        try:
            if 'tmp' in locals() and Path(tmp).exists():
                Path(tmp).unlink()
        except Exception:
            pass
        return False


def get_resource_pixmap(filename: str, width: int = 24, height: int = 24, dpr: Optional[float] = None, theme: Optional[str] = None) -> QPixmap:
    """Finds and loads a scaled QPixmap using PIL Lanczos resampling with high-DPI awareness for razor-sharp rendering."""
    if dpr is None:
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            dpr = app.primaryScreen().devicePixelRatio() if (app and app.primaryScreen()) else 1.0
        except Exception:
            dpr = 1.0

    if theme is None:
        theme = getattr(config, "theme", "dark")

    cache_key = (filename, width, height, dpr, theme)
    if cache_key in _RESOURCE_PIXMAP_CACHE:
        return _RESOURCE_PIXMAP_CACHE[cache_key]

    candidates = [
        Path(sys.executable).parent / "resources" / filename,
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "resources" / filename)
    candidates.extend([
        Path(__file__).resolve().parents[3] / "resources" / filename,
        Path.cwd() / "resources" / filename,
    ])
    for p in candidates:
        if p.exists():
            try:
                with Image.open(str(p.resolve())) as img:
                    img = img.convert("RGBA")
                    target_w = max(1, int(round(width * dpr)))
                    target_h = max(1, int(round(height * dpr)))
                    resized = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                    if theme == "light":
                        _, _, _, a = resized.split()
                        tinted = Image.new("RGBA", resized.size, (36, 41, 47, 255))
                        tinted.putalpha(a)
                        data = tinted.tobytes("raw", "RGBA")
                    else:
                        data = resized.tobytes("raw", "RGBA")
                    qimg = QImage(data, target_w, target_h, QImage.Format.Format_RGBA8888)
                    pix = QPixmap.fromImage(qimg)
                    pix.setDevicePixelRatio(dpr)
                    _RESOURCE_PIXMAP_CACHE[cache_key] = pix
                    return pix
            except Exception:
                pass
    return QPixmap()


def get_resource_icon(filename: str, size: int = 24, theme: Optional[str] = None) -> QIcon:
    """Finds and loads a QIcon containing sharp Lanczos-resampled pixmaps across multiple DPR scales."""
    if theme is None:
        theme = getattr(config, "theme", "dark")

    cache_key = (filename, size, theme)
    if cache_key in _RESOURCE_ICON_CACHE:
        return _RESOURCE_ICON_CACHE[cache_key]

    candidates = [
        Path(sys.executable).parent / "resources" / filename,
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "resources" / filename)
    candidates.extend([
        Path(__file__).resolve().parents[3] / "resources" / filename,
        Path.cwd() / "resources" / filename,
    ])
    for p in candidates:
        if p.exists():
            try:
                icon = QIcon()
                with Image.open(str(p.resolve())) as img:
                    img = img.convert("RGBA")
                    for dpr in (1.0, 1.25, 1.5, 1.75, 2.0):
                        target_px = max(1, int(round(size * dpr)))
                        resized = img.resize((target_px, target_px), Image.Resampling.LANCZOS)
                        if theme == "light":
                            _, _, _, a = resized.split()
                            tinted = Image.new("RGBA", resized.size, (36, 41, 47, 255))
                            tinted.putalpha(a)
                            data = tinted.tobytes("raw", "RGBA")
                        else:
                            data = resized.tobytes("raw", "RGBA")
                        qimg = QImage(data, target_px, target_px, QImage.Format.Format_RGBA8888)
                        pix = QPixmap.fromImage(qimg)
                        pix.setDevicePixelRatio(dpr)
                        icon.addPixmap(pix)
                    _RESOURCE_ICON_CACHE[cache_key] = icon
                    return icon
            except Exception:
                pass
    return QIcon()

# Async loader state
_PENDING_CALLBACKS: Dict[str, List[Tuple[Callable[[str, QPixmap], None], int, int, float, float]]] = {}
_SIGNALS_INSTANCE: Optional["_LoaderSignals"] = None


class _LoaderSignals(QObject):
    thumbnail_ready = pyqtSignal(str, str, int, int, float, float)  # (source_path, thumb_path, size, radius, dpr, mtime)


def _get_thumbnail_pool() -> QThreadPool:
    global _THUMBNAIL_POOL
    if _THUMBNAIL_POOL is None:
        _THUMBNAIL_POOL = QThreadPool()
        _THUMBNAIL_POOL.setMaxThreadCount(4)
    return _THUMBNAIL_POOL


def clear_thumbnail_queue() -> None:
    """Drops queued thumbnail jobs so application shutdown is not delayed."""
    pool = _THUMBNAIL_POOL
    if pool is not None:
        try:
            pool.clear()
        except Exception:
            pass


def _get_signals() -> _LoaderSignals:
    global _SIGNALS_INSTANCE
    if _SIGNALS_INSTANCE is None:
        _SIGNALS_INSTANCE = _LoaderSignals()
        _SIGNALS_INSTANCE.thumbnail_ready.connect(_on_thumbnail_ready_main_thread)
    return _SIGNALS_INSTANCE


def _get_cache_key(file_path: Union[str, Path], mtime: float, size: int, radius_top: int, dpr: float) -> Tuple[str, float, int, int, float]:
    return (_path_key(file_path), mtime, size, radius_top, dpr)


def _get_disk_thumbnail_path(file_path: Union[str, Path], mtime: float, size: int, dpr: float) -> Path:
    global _THUMBNAILS_DIR_READY
    if not _THUMBNAILS_DIR_READY:
        THUMBNAILS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _THUMBNAILS_DIR_READY = True
    target_px = int(size * dpr)
    # Preserve the historical naming scheme (canonical absolute path) so
    # thumbnails generated by older builds keep working. os.path.abspath avoids
    # an expensive filesystem realpath lookup per card.
    try:
        ident_path = os.path.abspath(str(file_path))
    except Exception:
        ident_path = _path_key(file_path)
    ident = f"{ident_path}_{mtime}_{target_px}"
    h = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:24]
    return THUMBNAILS_CACHE_DIR / f"{h}.png"


def _generate_thumbnail_file(source_path: Path, dest_thumb: Path, target_px: int) -> bool:
    """Runs in background thread: opens image with PIL, center-crops square, resizes with Lanczos, saves PNG."""
    try:
        if not source_path.exists() or not source_path.is_file():
            return False
        with Image.open(str(source_path)) as img:
            img = img.convert("RGBA")
            w, h = img.size
            min_dim = min(w, h)
            if min_dim <= 0:
                return False
            left = (w - min_dim) // 2
            top = (h - min_dim) // 2
            img = img.crop((left, top, left + min_dim, top + min_dim))
            img = img.resize((target_px, target_px), Image.Resampling.LANCZOS)
            dest_thumb.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(dest_thumb), format="PNG", optimize=False)
            return True
    except Exception:
        return False


def _create_rounded_pixmap_from_image(qimg: QImage, target_px: int, radius_top: int, dpr: float) -> QPixmap:
    pixmap = QPixmap(target_px, target_px)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    if radius_top > 0:
        r = radius_top * dpr
        path = QPainterPath()
        path.moveTo(0, target_px)
        path.lineTo(0, r)
        path.arcTo(0, 0, r * 2, r * 2, 180, -90)
        path.lineTo(target_px - r, 0)
        path.arcTo(target_px - r * 2, 0, r * 2, r * 2, 90, -90)
        path.lineTo(target_px, target_px)
        path.closeSubpath()
        painter.setClipPath(path)

    painter.drawImage(QRectF(0, 0, target_px, target_px), qimg)
    painter.end()

    pixmap.setDevicePixelRatio(dpr)
    return pixmap


class _ThumbnailRunnable(QRunnable):
    def __init__(self, source_path: Path, thumb_path: Path, target_px: int, size: int, radius_top: int, dpr: float, mtime: float, callback_key: str):
        super().__init__()
        self.source_path = source_path
        self.thumb_path = thumb_path
        self.target_px = target_px
        self.size = size
        self.radius_top = radius_top
        self.dpr = dpr
        self.mtime = mtime
        self.callback_key = callback_key

    def run(self):
        if not self.thumb_path.exists():
            _generate_thumbnail_file(self.source_path, self.thumb_path, self.target_px)

        try:
            signals = _get_signals()
            signals.thumbnail_ready.emit(
                self.callback_key,
                str(self.thumb_path),
                self.size,
                self.radius_top,
                self.dpr,
                self.mtime,
            )
        except RuntimeError:
            # Application is shutting down and the signal object was deleted.
            pass


def _on_thumbnail_ready_main_thread(source_path_str: str, thumb_path_str: str, size: int, radius_top: int, dpr: float, mtime: float):
    thumb_path = Path(thumb_path_str)
    pixmap: Optional[QPixmap] = None

    if thumb_path.exists():
        qimg = QImage(str(thumb_path))
        if not qimg.isNull():
            target_px = int(size * dpr)
            pixmap = _create_rounded_pixmap_from_image(qimg, target_px, radius_top, dpr)
            key = _get_cache_key(source_path_str, mtime, size, radius_top, dpr)
            _MEMORY_PIXMAP_CACHE[key] = pixmap

    callbacks = _PENDING_CALLBACKS.pop(source_path_str, [])
    if pixmap and not pixmap.isNull():
        for cb, _, _, _, _ in callbacks:
            try:
                cb(source_path_str, pixmap)
            except Exception:
                pass


def get_cached_square_pixmap(
    image_source: Union[str, Path],
    size: int = 170,
    radius_top: int = 8,
    dpr: float = 2.0,
) -> Optional[QPixmap]:
    """
    Checks memory cache and disk cache. If already available, returns QPixmap instantly.
    Does NOT block or run expensive Lanczos resizing.
    """
    if not image_source:
        return None
    p = Path(image_source)
    mtime = _get_source_mtime(p)
    if mtime is None:
        return None

    key = _get_cache_key(p, mtime, size, radius_top, dpr)
    # Fast path: no filesystem access at all once the thumbnail is in RAM.
    if key in _MEMORY_PIXMAP_CACHE:
        return _MEMORY_PIXMAP_CACHE[key]

    thumb_path = _get_disk_thumbnail_path(p, mtime, size, dpr)
    if thumb_path.exists():
        qimg = QImage(str(thumb_path))
        if not qimg.isNull():
            target_px = int(size * dpr)
            pixmap = _create_rounded_pixmap_from_image(qimg, target_px, radius_top, dpr)
            _MEMORY_PIXMAP_CACHE[key] = pixmap
            return pixmap

    return None


def request_async_square_pixmap(
    image_source: Union[str, Path],
    size: int = 170,
    radius_top: int = 8,
    dpr: float = 2.0,
    callback: Optional[Callable[[str, QPixmap], None]] = None,
) -> None:
    """
    Queues thumbnail generation in background QThreadPool.
    When ready, invokes callback(image_source, pixmap) on the GUI thread.
    """
    if not image_source or not callback:
        return
    p = Path(image_source)
    mtime = _get_source_mtime(p)
    if mtime is None:
        return

    key = _get_cache_key(p, mtime, size, radius_top, dpr)
    if key in _MEMORY_PIXMAP_CACHE:
        callback(str(p), _MEMORY_PIXMAP_CACHE[key])
        return

    target_px = int(size * dpr)
    thumb_path = _get_disk_thumbnail_path(p, mtime, size, dpr)

    source_key = _path_key(p)
    if source_key in _PENDING_CALLBACKS:
        _PENDING_CALLBACKS[source_key].append((callback, size, radius_top, dpr, mtime))
        return

    _PENDING_CALLBACKS[source_key] = [(callback, size, radius_top, dpr, mtime)]
    _get_signals()  # ensure signals initialized
    runnable = _ThumbnailRunnable(p, thumb_path, target_px, size, radius_top, dpr, mtime, source_key)
    _get_thumbnail_pool().start(runnable)


def load_high_quality_square_pixmap(
    image_source: Union[str, Path, bytes],
    size: int = 170,
    radius_top: int = 8,
    dpr: float = 2.0,
) -> Optional[QPixmap]:
    """
    Loads an image from path or bytes, crops it to a center square,
    and resizes it using PIL's high-quality Lanczos filter at 2x resolution (or dpr).
    Checks and populates memory and disk caches.
    """
    if isinstance(image_source, (str, Path)):
        p = Path(image_source)
        mtime = _get_source_mtime(p)
        if mtime is None:
            return None

        key = _get_cache_key(p, mtime, size, radius_top, dpr)
        if key in _MEMORY_PIXMAP_CACHE:
            return _MEMORY_PIXMAP_CACHE[key]

        target_px = int(size * dpr)
        thumb_path = _get_disk_thumbnail_path(p, mtime, size, dpr)
        if not thumb_path.exists():
            _generate_thumbnail_file(p, thumb_path, target_px)

        if thumb_path.exists():
            qimg = QImage(str(thumb_path))
            if not qimg.isNull():
                pixmap = _create_rounded_pixmap_from_image(qimg, target_px, radius_top, dpr)
                _MEMORY_PIXMAP_CACHE[key] = pixmap
                return pixmap

    # Fallback for bytes or direct generation
    try:
        if isinstance(image_source, bytes):
            import io
            img = Image.open(io.BytesIO(image_source)).convert("RGBA")
        elif isinstance(image_source, (str, Path)):
            img = Image.open(str(image_source)).convert("RGBA")
        else:
            return None

        w, h = img.size
        min_dim = min(w, h)
        if min_dim <= 0:
            return None

        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))
        target_px = int(size * dpr)
        img = img.resize((target_px, target_px), Image.Resampling.LANCZOS)

        raw_bytes = img.tobytes("raw", "RGBA")
        qimg = QImage(raw_bytes, target_px, target_px, QImage.Format.Format_RGBA8888)
        pixmap = _create_rounded_pixmap_from_image(qimg, target_px, radius_top, dpr)
        return pixmap
    except Exception:
        return None


def create_square_placeholder(
    size: int = 170,
    text_or_icon: str = "🎵",
    radius_top: int = 8,
    dpr: float = 2.0,
    bg_color: str = "#20252c",
    fg_color: str = "#7d8590",
    is_initials: bool = False,
) -> QPixmap:
    """
    Creates a square placeholder with top-rounded corners, styled initials or icon,
    rendered at high resolution with devicePixelRatio set.
    Cached in memory for instant reuse.
    """
    cache_key = (size, text_or_icon, radius_top, dpr, bg_color, fg_color, is_initials)
    if cache_key in _PLACEHOLDER_CACHE:
        return _PLACEHOLDER_CACHE[cache_key]

    target_px = int(size * dpr)
    pixmap = QPixmap(target_px, target_px)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    r = radius_top * dpr
    path = QPainterPath()
    path.moveTo(0, target_px)
    path.lineTo(0, r)
    path.arcTo(0, 0, r * 2, r * 2, 180, -90)
    path.lineTo(target_px - r, 0)
    path.arcTo(target_px - r * 2, 0, r * 2, r * 2, 90, -90)
    path.lineTo(target_px, target_px)
    path.closeSubpath()

    painter.fillPath(path, QColor(bg_color))

    font_size = int(size * (0.24 if is_initials else 0.32) * dpr)
    font = QFont("Segoe UI", font_size, QFont.Weight.Bold if is_initials else QFont.Weight.Normal)
    painter.setFont(font)
    painter.setPen(QColor(fg_color))
    painter.drawText(
        QRectF(0, 0, target_px, target_px),
        Qt.AlignmentFlag.AlignCenter,
        text_or_icon,
    )
    painter.end()

    pixmap.setDevicePixelRatio(dpr)
    _PLACEHOLDER_CACHE[cache_key] = pixmap
    return pixmap
