"""
services/rate_limiter.py
-------------------------
In-memory sliding window rate limiter for CineInsight.
Thread-safe and requires no external Redis/database dependency.
"""

import time
import threading
from collections import defaultdict
from typing import Tuple


class SlidingWindowRateLimiter:
    """
    Thread-safe in-memory sliding window rate limiter.
    Keeps track of request timestamps per (key, action).
    """

    def __init__(self):
        self._lock = threading.Lock()
        # key: (key, action) -> list of float timestamps
        self._history = defaultdict(list)

    def is_allowed(
        self, key: str, action: str, max_requests: int, window_seconds: int
    ) -> Tuple[bool, int]:
        """
        Check whether the action is allowed within the sliding window.
        Returns:
            (allowed: bool, retry_after: int)
        """
        now = time.time()
        bucket_key = f"{action}:{key}"

        with self._lock:
            timestamps = self._history[bucket_key]
            # Prune timestamps outside the current window
            cutoff = now - window_seconds
            valid_timestamps = [t for t in timestamps if t > cutoff]
            self._history[bucket_key] = valid_timestamps

            if len(valid_timestamps) >= max_requests:
                earliest_active = valid_timestamps[0]
                retry_after = max(1, int(earliest_active + window_seconds - now))
                return False, retry_after

            return True, 0

    def record(self, key: str, action: str) -> None:
        """Record an attempt for the given key and action."""
        now = time.time()
        bucket_key = f"{action}:{key}"
        with self._lock:
            self._history[bucket_key].append(now)

    def check_and_record(
        self, key: str, action: str, max_requests: int, window_seconds: int
    ) -> Tuple[bool, int]:
        """
        Atomically check if request is allowed, and if so, record it.
        Returns (allowed: bool, retry_after: int).
        """
        now = time.time()
        bucket_key = f"{action}:{key}"

        with self._lock:
            timestamps = self._history[bucket_key]
            cutoff = now - window_seconds
            valid_timestamps = [t for t in timestamps if t > cutoff]
            self._history[bucket_key] = valid_timestamps

            if len(valid_timestamps) >= max_requests:
                earliest_active = valid_timestamps[0]
                retry_after = max(1, int(earliest_active + window_seconds - now))
                return False, retry_after

            valid_timestamps.append(now)
            return True, 0

    def reset(self) -> None:
        """Clear all stored rate limit history (useful for testing)."""
        with self._lock:
            self._history.clear()


# Global singleton instance
rate_limiter = SlidingWindowRateLimiter()
