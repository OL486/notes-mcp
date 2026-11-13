"""跨 Tool / Resource 共用的服务层。"""

from __future__ import annotations

from .read_note import ReadOutcome, read_note

__all__ = ["ReadOutcome", "read_note"]
