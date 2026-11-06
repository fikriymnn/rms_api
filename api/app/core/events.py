import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger("rms.events")
Handler = Callable[[str, dict[str, Any]], None]
_handlers: list[Handler] = []


def on_event(fn: Handler) -> Handler:
    _handlers.append(fn)
    return fn


def emit(event: str, /, **payload: Any) -> None:
    """Kabarkan kejadian ke pelanggan. Nama kejadian posisional saja, jadi kunci 'name' boleh dipakai di payload."""
    for handler in list(_handlers):
        try:
            handler(event, payload)
        except Exception:
            log.exception("handler gagal untuk kejadian %s", event)
