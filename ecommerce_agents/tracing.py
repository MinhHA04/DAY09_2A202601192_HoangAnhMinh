"""JSONL trace writer for observable agent-to-agent handoffs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TraceWriter:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8", newline="\n")
        self._sequence = 0

    def emit(
        self,
        case_id: str,
        sender: str,
        recipient: str,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        self._sequence += 1
        record = {
            "sequence": self._sequence,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "sender": sender,
            "recipient": recipient,
            "event": event,
            "payload": payload,
        }
        json.dump(record, self._handle, ensure_ascii=False, separators=(",", ":"))
        self._handle.write("\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "TraceWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
