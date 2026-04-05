from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def ensure_parent_dir(path: Path) -> Path:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> Path:
    resolved = ensure_parent_dir(path)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding=encoding,
        delete=False,
        dir=str(resolved.parent),
        prefix=f"{resolved.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    os.replace(temp_path, resolved)
    return resolved


def atomic_write_json(path: Path, payload: Mapping[str, Any] | list[Any]) -> Path:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    return atomic_write_text(path, text)
