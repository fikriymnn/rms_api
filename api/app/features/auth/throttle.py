import time
from threading import Lock

MAX_FAILS = 5
WINDOW_SECONDS = 300

_fails: dict[str, list[float]] = {}
_lock = Lock()


def _recent(key: str, now: float) -> list[float]:
    return [t for t in _fails.get(key, []) if now - t < WINDOW_SECONDS]


def is_blocked(key: str) -> bool:
    with _lock:
        return len(_recent(key, time.time())) >= MAX_FAILS


def fail(key: str) -> None:
    with _lock:
        now = time.time()
        _fails[key] = _recent(key, now) + [now]


def reset(key: str) -> None:
    with _lock:
        _fails.pop(key, None)


def clear() -> None:
    with _lock:
        _fails.clear()
