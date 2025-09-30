from __future__ import annotations

_writer = None


def set_writer(writer) -> None:
    global _writer
    _writer = writer


async def flush_if_present() -> bool:
    if _writer is None:
        return False
    try:
        _ = await _writer.flush()
        return True
    except Exception:
        return False


__all__ = ["set_writer", "flush_if_present"]
