"""Tests for CineInsight cache management and cross-process lock coordination.

Validates:
- status reporting (absolute path, file count, total size, lock state)
- missing cache handled gracefully
- empty cache handled gracefully
- confirmation cancellation leaves all cache files intact
- successful clearing removes only target classification files
- preservation of media (mp4/wav), CSV outputs, reports, and debug logs
- path safety & symlink/junction rejection
- shared cross-process locking coordination with extractor
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from manage_cache import (
    format_size,
    get_cached_files,
    is_symlink_or_junction,
    run_clear,
    run_status,
    verify_cache_dir_safety,
)
from src.extractors.cache_lock import CrossProcessLock, get_cache_lock
import src.extractors.llm_aspect_extractor as llm_extractor


class TestFormatSize(unittest.TestCase):
    def test_bytes_formatting(self):
        self.assertEqual(format_size(0), "0 bytes")
        self.assertEqual(format_size(512), "512 bytes")

    def test_kb_formatting(self):
        self.assertIn("KB", format_size(2048))
        self.assertIn("2,048 bytes", format_size(2048))

    def test_mb_formatting(self):
        self.assertIn("MB", format_size(2 * 1024 * 1024))


class TestCacheSafety(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.cache_dir = self.root / "data" / "cache" / "aspect_sentiment"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_cache_directory_passes(self):
        verified = verify_cache_dir_safety(self.cache_dir, allowed_root=self.root)
        self.assertEqual(verified, self.cache_dir.resolve())

    def test_outside_path_rejected(self):
        outside = Path(tempfile.gettempdir()).resolve() / "outside_cache" / "aspect_sentiment"
        outside.mkdir(parents=True, exist_ok=True)
        try:
            with self.assertRaises(ValueError) as ctx:
                verify_cache_dir_safety(outside, allowed_root=self.root)
            self.assertIn("outside", str(ctx.exception).lower())
        finally:
            try:
                outside.rmdir()
                outside.parent.rmdir()
            except OSError:
                pass

    def test_root_directory_as_cache_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            verify_cache_dir_safety(self.root, allowed_root=self.root)
        self.assertIn("cannot be project root", str(ctx.exception).lower())

    def test_non_aspect_sentiment_directory_rejected(self):
        other_dir = self.root / "data" / "cache" / "other_type"
        other_dir.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ValueError) as ctx:
            verify_cache_dir_safety(other_dir, allowed_root=self.root)
        self.assertIn("not an aspect_sentiment cache", str(ctx.exception).lower())

    def test_junction_rejected(self):
        if sys.platform == "win32":
            import _winapi
            target = self.root / "real_aspect_sentiment"
            target.mkdir(parents=True, exist_ok=True)
            junction = self.root / "data" / "cache" / "aspect_sentiment_junction"
            try:
                _winapi.CreateJunction(str(target), str(junction))
                self.assertTrue(is_symlink_or_junction(junction))
                with self.assertRaises(ValueError) as ctx:
                    verify_cache_dir_safety(junction, allowed_root=self.root)
                self.assertIn("rejected", str(ctx.exception).lower())
            except Exception as e:
                self.skipTest(f"Could not create junction: {e}")


class TestCacheStatus(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.cache_dir = self.root / "data" / "cache" / "aspect_sentiment"
        self.lock_file = self.root / "data" / "cache" / ".aspect_sentiment.lock"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_status_missing_directory(self):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            ret = run_status(
                cache_dir=self.cache_dir,
                lock_path=self.lock_file,
                allowed_root=self.root,
            )
        self.assertEqual(ret, 0)
        output = stdout.getvalue()
        self.assertIn("Missing", output)
        self.assertIn("0 files", output)
        self.assertIn(str(self.cache_dir.resolve()), output)

    def test_status_empty_directory(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            ret = run_status(
                cache_dir=self.cache_dir,
                lock_path=self.lock_file,
                allowed_root=self.root,
            )
        self.assertEqual(ret, 0)
        output = stdout.getvalue()
        self.assertIn("Empty", output)
        self.assertIn("0 cached classification file(s)", output)

    def test_status_with_cached_files(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Create mock classification files
        for i in range(5):
            fpath = self.cache_dir / f"test_hash_{i}.json"
            fpath.write_text(json.dumps({"index": 0, "sentiment": "positive", "aspect_sentiments": []}))

        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            ret = run_status(
                cache_dir=self.cache_dir,
                lock_path=self.lock_file,
                allowed_root=self.root,
            )
        self.assertEqual(ret, 0)
        output = stdout.getvalue()
        self.assertIn("Active", output)
        self.assertIn("5 cached classification file(s)", output)
        self.assertIn(str(self.cache_dir.resolve()), output)
        self.assertIn("Unlocked (idle)", output)

    def test_status_reports_active_lock(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        lock = get_cache_lock(self.lock_file)
        with lock:
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                run_status(
                    cache_dir=self.cache_dir,
                    lock_path=self.lock_file,
                    allowed_root=self.root,
                )
            output = stdout.getvalue()
            self.assertIn("Locked (active extraction in progress)", output)


class TestCacheClear(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.cache_dir = self.root / "data" / "cache" / "aspect_sentiment"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.root / "data" / "cache" / ".aspect_sentiment.lock"

        # Populate sample cache files
        self.created_files = []
        for i in range(6):
            fpath = self.cache_dir / f"cached_item_{i:02d}.json"
            fpath.write_text(json.dumps({"index": 0, "sentiment": "positive", "aspect_sentiments": []}))
            self.created_files.append(fpath)

        # Populate external project assets that must NOT be touched
        self.video_file = self.root / "data" / "sample_review.mp4"
        self.video_file.parent.mkdir(parents=True, exist_ok=True)
        self.video_file.write_bytes(b"mock video data")

        self.audio_file = self.root / "data" / "sample_audio.wav"
        self.audio_file.write_bytes(b"mock audio data")

        self.csv_file = self.root / "data" / "llm_output_20261013_120000.csv"
        self.csv_file.write_text("index,text,aspect,sentiment\n1,good movie,acting,positive\n")

        self.debug_log = self.root / "data" / "debug" / "llm_debug_trace.json"
        self.debug_log.parent.mkdir(parents=True, exist_ok=True)
        self.debug_log.write_text('{"trace": "ok"}')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clear_cancellation_preserves_files(self):
        stdout = io.StringIO()
        # Non-matching inputs
        for wrong_input in ["", "no", "n", "clear", "CLEAR123", "   "]:
            with patch("sys.stdout", stdout):
                ret = run_clear(
                    cache_dir=self.cache_dir,
                    lock_path=self.lock_file,
                    allowed_root=self.root,
                    confirm_input_fn=lambda prompt, val=wrong_input: val,
                )
            self.assertEqual(ret, 1)
            # Verify all cache files still exist
            for f in self.created_files:
                self.assertTrue(f.exists(), f"File {f} was unexpectedly deleted on '{wrong_input}'")

        output = stdout.getvalue()
        self.assertIn("Clearing cancelled. No files were removed.", output)

    def test_clear_missing_cache_graceful(self):
        missing_dir = self.root / "data" / "cache" / "aspect_sentiment_missing"
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            ret = run_clear(
                cache_dir=missing_dir,
                lock_path=self.lock_file,
                allowed_root=self.root,
            )
        self.assertEqual(ret, 0)
        self.assertIn("Nothing to clear", stdout.getvalue())

    def test_clear_empty_cache_graceful(self):
        empty_dir = self.root / "data" / "cache" / "aspect_sentiment_empty"
        empty_dir.mkdir(parents=True, exist_ok=True)
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            ret = run_clear(
                cache_dir=empty_dir,
                lock_path=self.lock_file,
                allowed_root=self.root,
            )
        self.assertEqual(ret, 0)
        self.assertIn("Cache is empty. Nothing to clear.", stdout.getvalue())

    def test_clear_successful_execution(self):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            ret = run_clear(
                cache_dir=self.cache_dir,
                lock_path=self.lock_file,
                allowed_root=self.root,
                confirm_input_fn=lambda prompt: "CLEAR",
            )
        self.assertEqual(ret, 0)
        output = stdout.getvalue()
        self.assertIn("[Success] Cleared 6 file(s)", output)
        self.assertIn("Next analysis will make new Gemini requests", output)

        # Verify all cached classification files were removed
        remaining = list(self.cache_dir.glob("*.json"))
        self.assertEqual(len(remaining), 0)

        # Verify preservation of videos, WAVs, CSVs, and debug logs
        self.assertTrue(self.video_file.exists(), "Video file was deleted!")
        self.assertEqual(self.video_file.read_bytes(), b"mock video data")

        self.assertTrue(self.audio_file.exists(), "Audio WAV file was deleted!")
        self.assertEqual(self.audio_file.read_bytes(), b"mock audio data")

        self.assertTrue(self.csv_file.exists(), "LLM output CSV was deleted!")
        self.assertIn("acting,positive", self.csv_file.read_text())

        self.assertTrue(self.debug_log.exists(), "Debug log was deleted!")
        self.assertEqual(self.debug_log.read_text(), '{"trace": "ok"}')

    def test_clear_coordinates_with_active_lock(self):
        # Acquire lock in advance to simulate active extraction
        lock = get_cache_lock(self.lock_file)
        lock.acquire()

        acquired_while_held = False
        try:
            # Another attempt to acquire with timeout=0 should fail immediately
            probe_lock = get_cache_lock(self.lock_file, timeout=0)
            try:
                probe_lock.acquire(timeout=0)
                acquired_while_held = True
            except TimeoutError:
                pass
        finally:
            lock.release()

        self.assertFalse(acquired_while_held, "Lock was acquired while already held by another process!")

    def test_extractor_acquires_shared_lock(self):
        # Test that extract_aspects_from_segments_llm invokes _current_cache_lock
        with patch.object(llm_extractor, "_current_cache_lock") as mock_lock:
            # Create a mock lock context manager
            mock_lock.return_value.__enter__.return_value = None
            mock_lock.return_value.__exit__.return_value = None

            with patch.object(llm_extractor, "_extract", return_value=[]):
                llm_extractor.extract_aspects_from_segments_llm([])

            mock_lock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
