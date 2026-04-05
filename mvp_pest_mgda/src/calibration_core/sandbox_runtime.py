from __future__ import annotations

import shutil
from pathlib import Path


def reset_directory(path: Path) -> Path:
    resolved = Path(path).resolve()
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def archive_tree(source: Path, destination: Path) -> Path:
    resolved_source = Path(source).resolve()
    resolved_destination = Path(destination).resolve()
    if resolved_destination.exists():
        shutil.rmtree(resolved_destination)
    if resolved_source.exists():
        shutil.copytree(resolved_source, resolved_destination)
    else:
        resolved_destination.mkdir(parents=True, exist_ok=True)
    return resolved_destination
