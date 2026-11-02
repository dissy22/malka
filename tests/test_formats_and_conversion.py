import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg

from malka import config as config_module
from malka.config import Config
from malka.db import get_connection, init_db
from malka.formats import (
    LIBRARY_EXTS,
    MODE_COPY,
    MODE_HIRES,
    MODE_LOSSLESS_RESAMPLE,
    MODE_LOSSY,
    PLAYABLE_EXTS,
    SOURCE_KIND_FLAC_ALAC,
    SOURCE_KIND_IMAGE_APE_WV,
    SOURCE_KIND_IMAGE_FLAC_ALAC,
    SOURCE_KIND_MP3_M4A,
    available_formats,
    available_modes,
    encoder_args,
    is_hires,
    is_lossless_source,
    mode_label,
    normalize_settings,
    plan_for,
)
from malka.importer import analyze_import_folder, execute_import
from malka.pcm_engine import _DecodeWorker, _PcmBuffer
from malka.tags import get_audio_stream_info, read_tags


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def make_audio(path: Path, *, fmt: str, sample_rate: int = 44100, bits: int = 16, seconds: float = 1.5):
    """Creates a real audio file with the bundled FFmpeg."""
    cmd = [
        ffmpeg(), "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=660:duration={seconds}",
        "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]", "-map", "[a]",
    ]
    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
    elif fmt == "aac":
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    elif fmt == "alac":
        cmd += ["-c:a", "alac"]
    elif fmt == "wv":
        cmd += ["-c:a", "wavpack"]
    else:
        cmd += ["-c:a", "flac"]
    cmd += ["-ar", str(sample_rate)]
    if bits > 16 and fmt in ("flac", "wv"):
        # ALAC only accepts s16p in FFmpeg; FLAC and WavPack take 24/32-bit input.
        cmd += ["-sample_fmt", "s32p" if fmt == "wv" else "s32"]
    cmd += ["-metadata", "title=Test", "-metadata", "album=Test Album",
            "-metadata", "artist=Test Artist", "-metadata", "album_artist=Test Artist",
            "-metadata", "date=2024", "-metadata", "genre=Rock", "-metadata", "track=1"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


def _cue_time(seconds: float) -> str:
    total = int(round(seconds * 75))
    mm, rest = divmod(total, 75 * 60)
    ss, ff = divmod(rest, 75)
    return f"{mm:02d}:{ss:02d}:{ff:02d}"


def make_cue(folder: Path, image_name: str, titles, *, album="Test Album", artist="Test Artist",
             year="2024", genre="Rock", step_seconds=1.0):
    lines = [
        f'TITLE "{album}"',
        f'PERFORMER "{artist}"',
        f"REM DATE {year}",
        f'REM GENRE "{genre}"',
        f'FILE "{image_name}" WAVE',
    ]
    for i, title in enumerate(titles):
        lines += [
            f"  TRACK {i + 1:02d} AUDIO",
            f'    TITLE "{title}"',
            "    INDEX 01 " + _cue_time(i * step_seconds),
        ]
    (folder / f"{Path(image_name).stem}.cue").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


class TestFormatRules(unittest.TestCase):
    def test_library_formats_are_mp3_m4a_flac_only(self):
        self.assertEqual(LIBRARY_EXTS, {".mp3", ".m4a", ".flac"})
        self.assertEqual(PLAYABLE_EXTS, frozenset({".mp3", ".m4a", ".flac"}))

    def test_hirez_detection(self):
        self.assertFalse(is_hires(44100, 16))
        self.assertFalse(is_hires(48000, 16))
        self.assertTrue(is_hires(96000, 16))
        self.assertTrue(is_hires(44100, 24))
        self.assertTrue(is_hires(192000, 24))

    def test_available_modes_per_source(self):
        self.assertEqual(available_modes(SOURCE_KIND_MP3_M4A, False), [MODE_COPY])

        # Lossless tracks below the limit: lossy or keep.
        self.assertEqual(available_modes(SOURCE_KIND_FLAC_ALAC, False), [MODE_LOSSY, MODE_COPY])
        # Above the limit: lossy, lossless resample, or keep Hi-Res.
        self.assertEqual(
            available_modes(SOURCE_KIND_FLAC_ALAC, True),
            [MODE_LOSSY, MODE_LOSSLESS_RESAMPLE, MODE_COPY],
        )
        self.assertEqual(
            available_modes(SOURCE_KIND_IMAGE_FLAC_ALAC, True),
            [MODE_LOSSY, MODE_LOSSLESS_RESAMPLE, MODE_COPY],
        )
        # APE/WavPack cannot be kept as-is: the "keep" mode re-encodes.
        self.assertEqual(
            available_modes(SOURCE_KIND_IMAGE_APE_WV, True),
            [MODE_LOSSY, MODE_LOSSLESS_RESAMPLE, MODE_HIRES],
        )

    def test_mode_labels(self):
        self.assertIn("split into tracks", mode_label(MODE_LOSSY, SOURCE_KIND_IMAGE_FLAC_ALAC, True))
        self.assertNotIn("split", mode_label(MODE_LOSSY, SOURCE_KIND_FLAC_ALAC, True))
        self.assertIn("Hi-Res", mode_label(MODE_COPY, SOURCE_KIND_FLAC_ALAC, True))
        self.assertIn("no re-encoding", mode_label(MODE_COPY, SOURCE_KIND_MP3_M4A, False))
        self.assertIn("re-encode to FLAC/ALAC", mode_label(MODE_HIRES, SOURCE_KIND_IMAGE_APE_WV, True))
        self.assertIn("Hi-Res", mode_label(MODE_HIRES, SOURCE_KIND_IMAGE_APE_WV, True))
        # A CD-quality APE/WavPack image is not "Hi-Res", but still gets re-encoded.
        self.assertNotIn("Hi-Res", mode_label(MODE_HIRES, SOURCE_KIND_IMAGE_APE_WV, False))
        self.assertIn("re-encode to FLAC/ALAC", mode_label(MODE_HIRES, SOURCE_KIND_IMAGE_APE_WV, False))

    def test_available_formats(self):
        self.assertEqual(available_formats(MODE_LOSSY), ["mp3", "m4a"])
        self.assertEqual(available_formats(MODE_LOSSLESS_RESAMPLE), ["flac", "alac"])
        self.assertEqual(available_formats(MODE_HIRES), ["flac", "alac"])
        self.assertEqual(available_formats(MODE_COPY), [])

    def test_normalize_settings_falls_back_for_invalid_combinations(self):
        # "copy" is not offered for APE/WavPack images → falls back to Hi-Res.
        settings = normalize_settings(
            SOURCE_KIND_IMAGE_APE_WV, True, {"mode": MODE_COPY, "format": "mp3", "rate": 44100}
        )
        self.assertEqual(settings["mode"], MODE_HIRES)
        self.assertIn(settings["format"], ("flac", "alac"))
        self.assertEqual(settings["rate"], 44100)

        # lossless_resample is not offered below the limit.
        settings = normalize_settings(
            SOURCE_KIND_FLAC_ALAC, False, {"mode": MODE_LOSSLESS_RESAMPLE, "format": "flac", "rate": 44100}
        )
        self.assertEqual(settings["mode"], MODE_COPY)

    def test_plan_for_copy_keeps_stream(self):
        plan = plan_for(SOURCE_KIND_FLAC_ALAC, True, {"mode": MODE_COPY}, "flac", 96000, 24)
        self.assertTrue(plan["copy_stream"])
        self.assertIsNone(plan["target_rate"])
        self.assertFalse(plan["split"])

        plan = plan_for(SOURCE_KIND_IMAGE_FLAC_ALAC, True, {"mode": MODE_COPY}, "flac", 96000, 24)
        self.assertTrue(plan["copy_stream"])
        self.assertTrue(plan["split"])

    def test_plan_for_lossy_never_upsamples(self):
        plan = plan_for(
            SOURCE_KIND_FLAC_ALAC, True, {"mode": MODE_LOSSY, "format": "mp3", "rate": 44100},
            "flac", 96000, 24,
        )
        self.assertEqual(plan["output_format"], "mp3")
        self.assertEqual(plan["target_rate"], 44100)
        self.assertFalse(plan["copy_stream"])

        # 44.1 kHz source with a 48 kHz ceiling: keep 44.1 (no upsampling).
        plan = plan_for(
            SOURCE_KIND_FLAC_ALAC, False, {"mode": MODE_LOSSY, "format": "m4a", "rate": 48000},
            "flac", 44100, 16,
        )
        self.assertIsNone(plan["target_rate"])

    def test_plan_for_lossless_resample_reduces_bits(self):
        plan = plan_for(
            SOURCE_KIND_FLAC_ALAC, True, {"mode": MODE_LOSSLESS_RESAMPLE, "format": "alac", "rate": 48000},
            "flac", 192000, 24,
        )
        self.assertEqual(plan["output_format"], "alac")
        self.assertEqual(plan["target_rate"], 48000)
        self.assertTrue(plan["reduce_bits"])

    def test_plan_for_hires_keeps_resolution(self):
        plan = plan_for(
            SOURCE_KIND_IMAGE_APE_WV, True, {"mode": MODE_HIRES, "format": "flac", "rate": 44100},
            "wv", 96000, 24,
        )
        self.assertEqual(plan["output_format"], "flac")
        self.assertIsNone(plan["target_rate"])
        self.assertFalse(plan["reduce_bits"])
        self.assertTrue(plan["split"])

    def test_encoder_args(self):
        self.assertEqual(
            encoder_args("flac", 48000, True),
            ["-c:a", "flac", "-ar", "48000", "-sample_fmt", "s16"],
        )
        self.assertEqual(
            encoder_args("alac", 44100, True),
            ["-c:a", "alac", "-ar", "44100", "-sample_fmt", "s16p"],
        )
        self.assertEqual(encoder_args("mp3", None, False), ["-c:a", "libmp3lame", "-b:a", "320k"])
        self.assertEqual(encoder_args("m4a", 48000, False), ["-c:a", "aac", "-b:a", "224k", "-ar", "48000"])

    def test_lossless_detection(self):
        tmp = Path(tempfile.mkdtemp(prefix="malka_fmt_"))
        try:
            flac = make_audio(tmp / "a.flac", fmt="flac")
            alac = make_audio(tmp / "a.m4a", fmt="alac")
            aac = make_audio(tmp / "b.m4a", fmt="aac")
            mp3 = make_audio(tmp / "a.mp3", fmt="mp3")

            self.assertTrue(is_lossless_source(str(flac)))
            self.assertTrue(is_lossless_source(str(alac)))
            self.assertFalse(is_lossless_source(str(aac)))
            self.assertFalse(is_lossless_source(str(mp3)))
            self.assertTrue(is_lossless_source(str(tmp / "x.ape")))
            self.assertTrue(is_lossless_source(str(tmp / "x.wv")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestImportSettingsPersistence(unittest.TestCase):
    def test_settings_are_remembered_per_source_kind(self):
        tmp = Path(tempfile.mkdtemp(prefix="malka_cfg_"))
        try:
            with patch.multiple(
                config_module,
                APP_DIR=tmp,
                CONFIG_FILE=tmp / "config.json",
                CACHE_DIR=tmp / "covers",
                ARTISTS_CACHE_DIR=tmp / "artists",
                THUMBNAILS_CACHE_DIR=tmp / "thumbnails",
                DEFAULT_DB_PATH=tmp / "library.db",
            ):
                cfg = Config()
                self.assertEqual(cfg.get_import_settings(SOURCE_KIND_FLAC_ALAC), {})

                cfg.set_import_settings(
                    SOURCE_KIND_FLAC_ALAC, {"mode": MODE_LOSSY, "format": "mp3", "rate": 44100}
                )
                cfg.set_import_settings(
                    SOURCE_KIND_IMAGE_APE_WV, {"mode": MODE_HIRES, "format": "alac", "rate": 48000}
                )
                cfg.save()

                reloaded = Config()
                self.assertEqual(
                    reloaded.get_import_settings(SOURCE_KIND_FLAC_ALAC),
                    {"mode": MODE_LOSSY, "format": "mp3", "rate": 44100},
                )
                self.assertEqual(
                    reloaded.get_import_settings(SOURCE_KIND_IMAGE_APE_WV),
                    {"mode": MODE_HIRES, "format": "alac", "rate": 48000},
                )
                self.assertEqual(reloaded.get_import_settings(SOURCE_KIND_MP3_M4A), {})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestPlaybackDecode(unittest.TestCase):
    """FLAC and ALAC must be decodable by the engine's FFmpeg pipeline."""

    def _decode(self, path: Path) -> _PcmBuffer:
        buffer = _PcmBuffer()
        worker = _DecodeWorker([str(path)], 0, 0, buffer)
        worker.start()
        deadline = time.time() + 20
        while time.time() < deadline and not buffer.ended and not buffer.error:
            time.sleep(0.02)
        worker.stop()
        worker.join(timeout=5)
        return buffer

    def test_flac_and_alac_decode_to_pcm(self):
        tmp = Path(tempfile.mkdtemp(prefix="malka_play_"))
        try:
            for fmt, name in (("flac", "track.flac"), ("alac", "track.m4a")):
                with self.subTest(fmt=fmt):
                    path = make_audio(tmp / name, fmt=fmt, seconds=1.0)
                    buffer = self._decode(path)
                    self.assertEqual(buffer.error, "")
                    self.assertGreater(buffer.available(), 44100 * 2 * 2 // 4)
                    self.assertEqual(buffer.boundaries[0]["index"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_alac_is_recognised_by_the_tag_reader(self):
        tmp = Path(tempfile.mkdtemp(prefix="malka_play_"))
        try:
            path = make_audio(tmp / "track.m4a", fmt="alac")
            info = get_audio_stream_info(str(path))
            self.assertEqual(info["sample_rate"], 44100)
            tags = read_tags(str(path))
            self.assertEqual(tags["title"], "Test")
            self.assertEqual(tags["album"], "Test Album")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ImportTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="malka_conv_"))
        self.lib = self.tmp / "lib"
        self.lib.mkdir()
        self.db = self.tmp / "db.sqlite"
        init_db(str(self.db))
        self.conn = get_connection(str(self.db))

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _album(self, mode, fmt="flac", rate=48000, **extra):
        data = {
            "album": "Test Album",
            "album_artist": "Test Artist",
            "year": "2024",
            "genre": "Rock",
            "compilation": 0,
            "cover_cache_path": "",
            "remove_cover": False,
            "import_mode": mode,
            "import_format": fmt,
            "import_rate": rate,
        }
        data.update(extra)
        return data

    def _import(self, analysis, mode, fmt="flac", rate=48000):
        ok, msg, imported = execute_import(
            analysis=analysis,
            edited_album=self._album(mode, fmt, rate),
            edited_tracks=analysis.tracks,
            library_path=str(self.lib),
            naming_format="<track_no>. <title>",
            db_conn=self.conn,
        )
        self.assertTrue(ok, msg)
        return [Path(p) for p in imported]


class TestTrackConversionMatrix(ImportTestBase):
    def _analyze(self, fmt="flac", sample_rate=96000, bits=24):
        src = self.tmp / f"src_{fmt}_{sample_rate}"
        src.mkdir()
        name = "01. Track.flac" if fmt == "flac" else "01. Track.m4a"
        make_audio(src / name, fmt=fmt, sample_rate=sample_rate, bits=bits)
        analysis = analyze_import_folder(str(src), self.conn)
        self.assertEqual(analysis.variant, 3)
        return analysis

    def test_hirez_keep_original(self):
        analysis = self._analyze()
        self.assertTrue(analysis.is_hires)
        out = self._import(analysis, MODE_COPY)[0]
        self.assertEqual(out.suffix, ".flac")
        info = get_audio_stream_info(str(out))
        self.assertEqual(info["sample_rate"], 96000)
        self.assertEqual(info["bits_per_sample"], 24)

    def test_hirez_lossy_mp3_at_44k(self):
        analysis = self._analyze()
        out = self._import(analysis, MODE_LOSSY, fmt="mp3", rate=44100)[0]
        self.assertEqual(out.suffix, ".mp3")
        self.assertEqual(get_audio_stream_info(str(out))["sample_rate"], 44100)

    def test_hirez_lossy_m4a_at_48k(self):
        analysis = self._analyze()
        out = self._import(analysis, MODE_LOSSY, fmt="m4a", rate=48000)[0]
        self.assertEqual(out.suffix, ".m4a")
        self.assertFalse(is_lossless_source(str(out)))
        self.assertEqual(get_audio_stream_info(str(out))["sample_rate"], 48000)

    def test_hirez_lossless_resample_flac(self):
        analysis = self._analyze()
        out = self._import(analysis, MODE_LOSSLESS_RESAMPLE, fmt="flac", rate=48000)[0]
        self.assertEqual(out.suffix, ".flac")
        info = get_audio_stream_info(str(out))
        self.assertEqual(info["sample_rate"], 48000)
        self.assertEqual(info["bits_per_sample"], 16)

    def test_hirez_lossless_resample_alac_at_44k(self):
        analysis = self._analyze()
        out = self._import(analysis, MODE_LOSSLESS_RESAMPLE, fmt="alac", rate=44100)[0]
        self.assertEqual(out.suffix, ".m4a")
        self.assertTrue(is_lossless_source(str(out)))
        info = get_audio_stream_info(str(out))
        self.assertEqual(info["sample_rate"], 44100)
        self.assertEqual(info["bits_per_sample"], 16)

    def test_cd_quality_is_not_resampled(self):
        analysis = self._analyze(sample_rate=44100, bits=16)
        self.assertFalse(analysis.is_hires)
        out = self._import(analysis, MODE_LOSSLESS_RESAMPLE, fmt="flac", rate=48000)[0]
        info = get_audio_stream_info(str(out))
        self.assertEqual(info["sample_rate"], 44100)
        self.assertEqual(info["bits_per_sample"], 16)

    def test_alac_tracks_are_supported(self):
        analysis = self._analyze(fmt="alac", sample_rate=96000, bits=16)
        out = self._import(analysis, MODE_LOSSLESS_RESAMPLE, fmt="flac", rate=48000)[0]
        self.assertEqual(out.suffix, ".flac")
        self.assertEqual(get_audio_stream_info(str(out))["sample_rate"], 48000)

    def test_copy_does_not_reencode_mp3_tracks(self):
        src = self.tmp / "mp3src"
        src.mkdir()
        make_audio(src / "01. Song.mp3", fmt="mp3")
        analysis = analyze_import_folder(str(src), self.conn)
        self.assertEqual(analysis.source_kind, SOURCE_KIND_MP3_M4A)
        with patch("malka.importer.write_tags"):
            out = self._import(analysis, MODE_COPY)[0]
        self.assertEqual(out.suffix, ".mp3")
        # Tags are rewritten on import, but the MP3 audio stream is untouched.
        self.assertEqual(out.read_bytes(), (src / "01. Song.mp3").read_bytes())


class TestImageSplitting(ImportTestBase):
    def _image_album(self, fmt: str, sample_rate=96000, bits=24):
        src = self.tmp / f"img_{fmt}"
        src.mkdir()
        ext = {"flac": ".flac", "alac": ".m4a", "wv": ".wv"}[fmt]
        image = make_audio(src / f"album{ext}", fmt=fmt, sample_rate=sample_rate, bits=bits, seconds=3)
        make_cue(src, image.name, ["First", "Second"])
        return analyze_import_folder(str(src), self.conn)

    def test_flac_image_split_without_reencoding(self):
        analysis = self._image_album("flac")
        self.assertEqual(analysis.source_kind, SOURCE_KIND_IMAGE_FLAC_ALAC)
        out = self._import(analysis, MODE_COPY)
        self.assertEqual(len(out), 2)
        for path in out:
            self.assertEqual(path.suffix, ".flac")
            info = get_audio_stream_info(str(path))
            self.assertEqual(info["sample_rate"], 96000)
            self.assertEqual(info["bits_per_sample"], 24)

    def test_alac_image_split_without_reencoding(self):
        analysis = self._image_album("alac")
        out = self._import(analysis, MODE_COPY)
        self.assertEqual(len(out), 2)
        for path in out:
            self.assertEqual(path.suffix, ".m4a")
            self.assertTrue(is_lossless_source(str(path)))
            self.assertEqual(get_audio_stream_info(str(path))["sample_rate"], 96000)

    def test_wavpack_image_hirez_to_flac(self):
        analysis = self._image_album("wv")
        self.assertEqual(analysis.source_kind, SOURCE_KIND_IMAGE_APE_WV)
        out = self._import(analysis, MODE_HIRES, fmt="flac")
        self.assertEqual(len(out), 2)
        for path in out:
            self.assertEqual(path.suffix, ".flac")
            info = get_audio_stream_info(str(path))
            self.assertEqual(info["sample_rate"], 96000)
            self.assertEqual(info["bits_per_sample"], 24)

    def test_image_lossy_split(self):
        analysis = self._image_album("flac")
        out = self._import(analysis, MODE_LOSSY, fmt="mp3", rate=48000)
        self.assertEqual(len(out), 2)
        for path in out:
            self.assertEqual(path.suffix, ".mp3")
            self.assertEqual(get_audio_stream_info(str(path))["sample_rate"], 48000)

    def test_image_lossless_resample_split(self):
        analysis = self._image_album("flac")
        out = self._import(analysis, MODE_LOSSLESS_RESAMPLE, fmt="alac", rate=48000)
        self.assertEqual(len(out), 2)
        for path in out:
            self.assertEqual(path.suffix, ".m4a")
            info = get_audio_stream_info(str(path))
            self.assertEqual(info["sample_rate"], 48000)
            self.assertEqual(info["bits_per_sample"], 16)


class TestImportWorkerUI(ImportTestBase):
    """The background worker used by the import progress dialog."""

    def test_worker_splits_image_to_alac(self):
        from malka.ui.import_progress_dialog import ImportWorker

        src = self.tmp / "worker"
        src.mkdir()
        image = make_audio(src / "album.flac", fmt="flac", sample_rate=96000, bits=24, seconds=3)
        make_cue(src, image.name, ["One", "Two"])
        analysis = analyze_import_folder(str(src), self.conn)

        results = []
        worker = ImportWorker(
            analysis=analysis,
            edited_album=self._album(MODE_LOSSLESS_RESAMPLE, "alac", 48000),
            edited_tracks=analysis.tracks,
            library_path=str(self.lib),
            naming_format="<track_no>. <title>",
            db_path=str(self.db),
        )
        worker.finished_import.connect(lambda ok, msg, paths: results.append((ok, msg, paths)))
        worker.run()

        self.assertTrue(results, "worker did not finish")
        ok, msg, paths = results[0]
        self.assertTrue(ok, msg)
        self.assertEqual(len(paths), 2)
        for path in paths:
            self.assertTrue(path.endswith(".m4a"))
            self.assertTrue(Path(path).exists())
            self.assertEqual(get_audio_stream_info(path)["sample_rate"], 48000)


class TestScannerFormats(unittest.TestCase):
    def test_scanner_only_accepts_library_formats(self):
        from malka.scanner import SUPPORTED_EXTS

        self.assertEqual(SUPPORTED_EXTS, {".mp3", ".m4a", ".flac"})
        for ext in (".ape", ".wv", ".aac", ".mp4", ".wav"):
            self.assertNotIn(ext, SUPPORTED_EXTS)


if __name__ == "__main__":
    unittest.main()
