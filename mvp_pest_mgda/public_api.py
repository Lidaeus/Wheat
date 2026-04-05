from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


def _resolve_src_dir() -> Path:
    return (Path(__file__).resolve().parent / "src").resolve()


def _ensure_src_dir() -> Path:
    src_dir = _resolve_src_dir()
    src_dir_text = str(src_dir)
    if src_dir_text not in sys.path:
        sys.path.insert(0, src_dir_text)
    return src_dir


def load_public_module(module_name: str):
    _ensure_src_dir()
    return importlib.import_module(str(module_name).strip())


def load_public_api() -> SimpleNamespace:
    return SimpleNamespace(
        pest_builder=load_public_module("pest_builder"),
        pest_runner=load_public_module("pest_runner"),
        result_schema=load_public_module("result_schema"),
        dssat_io=load_public_module("dssat_io"),
        crop_registry=load_public_module("crop_registry"),
    )
