"""Small atomic writes with bounded retries for transient Windows file locks."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def atomic_text(path: Path, text: str, *, attempts: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        for attempt in range(attempts):
            try:
                temp.replace(path)
                return
            except PermissionError:
                if attempt + 1 == attempts:
                    raise
                time.sleep(min(.05 * 2 ** attempt, .8))
    finally:
        temp.unlink(missing_ok=True)
