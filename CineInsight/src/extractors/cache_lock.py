"""Cross-process lock coordinator for aspect/sentiment cache operations.

Coordinates between the LLM extractor and CLI cache management tools
to prevent race conditions and ensure safe cache invalidation.
"""
import os
import sys
import time
from pathlib import Path


class CrossProcessLock:
    """Inter-process lock that works across separate terminal and web server processes."""

    def __init__(self, lock_path: Path | str, timeout: float | None = None):
        self.lock_path = Path(lock_path).resolve()
        self.timeout = timeout
        self._filelock_obj = None
        self._fallback_fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def acquire(self, timeout: float | None = None) -> bool:
        """Acquire the lock. Raises TimeoutError if timeout expires."""
        to = self.timeout if timeout is None else timeout
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        # Try filelock package first if available
        try:
            import filelock

            # In filelock, timeout < 0 means infinite wait, 0 means non-blocking
            filelock_to = -1 if to is None else max(0.0, to)
            self._filelock_obj = filelock.FileLock(str(self.lock_path), timeout=filelock_to)
            try:
                self._filelock_obj.acquire()
                return True
            except filelock.Timeout:
                self._filelock_obj = None
                raise TimeoutError(f"Could not acquire cache lock at {self.lock_path} within {to}s")
        except ImportError:
            pass

        # Standard library fallback (Windows msvcrt / POSIX fcntl)
        start_time = time.monotonic()
        fd = open(self.lock_path, "a+b")
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    fd.seek(0)
                    msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fallback_fd = fd
                return True
            except (OSError, IOError):
                if to is not None and (time.monotonic() - start_time) >= to:
                    fd.close()
                    raise TimeoutError(f"Could not acquire cache lock at {self.lock_path} within {to}s")
                time.sleep(0.05)

    def release(self):
        """Release the acquired lock."""
        if self._filelock_obj is not None:
            try:
                self._filelock_obj.release()
            finally:
                self._filelock_obj = None

        if self._fallback_fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fallback_fd.seek(0)
                    msvcrt.locking(self._fallback_fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fallback_fd.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                try:
                    self._fallback_fd.close()
                except OSError:
                    pass
                self._fallback_fd = None

    def is_locked(self) -> bool:
        """Check non-blockingly whether the lock is currently held by any process."""
        if self._filelock_obj is not None or self._fallback_fd is not None:
            return True

        probe = CrossProcessLock(self.lock_path, timeout=0)
        try:
            probe.acquire(timeout=0)
            probe.release()
            return False
        except (TimeoutError, OSError):
            return True


def get_default_lock_path() -> Path:
    """Return default lock file path relative to repository root."""
    root = Path(__file__).resolve().parent.parent.parent
    return root / "data" / "cache" / ".aspect_sentiment.lock"


def get_cache_lock(lock_path: Path | str | None = None, timeout: float | None = None) -> CrossProcessLock:
    """Get a CrossProcessLock instance for the cache lock file."""
    path = Path(lock_path) if lock_path else get_default_lock_path()
    return CrossProcessLock(path, timeout=timeout)
