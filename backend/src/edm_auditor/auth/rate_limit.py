"""In-memory sliding-window rate limiter for login attempts."""

from collections import deque
from collections.abc import Callable
from threading import Lock
import time

from .errors import LoginRateLimitedError


class LoginRateLimiter:
    """Limits failed login attempts per (client_ip, normalized_username) key."""

    def __init__(
        self,
        *,
        max_attempts: int = 10,
        window_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._clock = clock
        self._lock = Lock()
        self._attempts: dict[tuple[str, str], deque[float]] = {}

    @staticmethod
    def _key(ip_address: str | None, username: str) -> tuple[str, str]:
        return ((ip_address or "unknown").strip(), username.strip().lower())

    def _prune(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self._window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def check(self, ip_address: str | None, username: str) -> None:
        key = self._key(ip_address, username)
        now = self._clock()
        with self._lock:
            bucket = self._attempts.get(key)
            if not bucket:
                return
            self._prune(bucket, now)
            if not bucket:
                self._attempts.pop(key, None)
                return
            if len(bucket) >= self._max_attempts:
                raise LoginRateLimitedError(
                    "Too many failed login attempts. Please try again later."
                )

    def record_failure(self, ip_address: str | None, username: str) -> None:
        key = self._key(ip_address, username)
        now = self._clock()
        with self._lock:
            bucket = self._attempts.setdefault(key, deque())
            self._prune(bucket, now)
            bucket.append(now)

    def reset(self, ip_address: str | None, username: str) -> None:
        key = self._key(ip_address, username)
        with self._lock:
            self._attempts.pop(key, None)
