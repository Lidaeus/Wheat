from __future__ import annotations

from pathlib import Path


def parse_fixed_header_spans(header: str) -> dict[str, tuple[int, int]]:
    import re

    matches = list(re.finditer(r"\S+", header))
    cols = [m.group(0).lstrip("@").strip() for m in matches]
    return {c: (matches[i].start(), matches[i].end()) for i, c in enumerate(cols)}


def format_like_field(existing: str, width: int, value: float) -> str:
    s = existing.strip()
    if not s:
        out = f"{value:>{width}.2f}"
    elif "." in s:
        decimals = len(s.split(".", 1)[1])
        out = f"{value:>{width}.{decimals}f}"
        stripped = out.strip()
        if s.startswith(".") or s.startswith("-."):
            if stripped.startswith("-0."):
                stripped = "-." + stripped[3:]
            elif stripped.startswith("0."):
                stripped = "." + stripped[2:]
            out = stripped.rjust(width)
    else:
        out = f"{int(round(value)):>{width}d}"
    if len(out) > width:
        raise RuntimeError(f"Value {value} does not fit width {width}")
    return out


def apply_fixed_block_updates(
    raw: list[str],
    header_prefix: str,
    key_cols: list[str],
    updates: list[dict[str, float]],
    required_cols: set[str] | None = None,
) -> list[str]:
    out: list[str] = []
    in_block = False
    spans: dict[str, tuple[int, int]] = {}
    key_index = {tuple(str(u[k]).strip() for k in key_cols): u for u in updates}
    for line in raw:
        row = line.rstrip("\r\n")
        ending = line[len(row) :]
        if row.startswith(header_prefix):
            spans = parse_fixed_header_spans(row)
            if required_cols and not required_cols.issubset(set(spans.keys())):
                out.append(line)
                in_block = False
                continue
            in_block = True
            out.append(line)
            continue
        if in_block:
            if row.startswith("*") or row.startswith("@") or not row.strip() or row.lstrip().startswith("!"):
                in_block = False
                out.append(line)
                continue
            if not spans:
                out.append(line)
                continue
            key = tuple(row[spans[c][0] : spans[c][1]].strip() for c in key_cols)
            upd = key_index.get(key)
            if upd is None:
                out.append(line)
                continue
            row_chars = list(row)
            orig_len = len(row)
            for c, v in upd.items():
                if c in key_cols:
                    continue
                if c not in spans:
                    continue
                a, b = spans[c]
                existing = row[a:b]
                width = b - a
                repl = format_like_field(existing, width, float(v))
                row_chars[a:b] = list(repl)
            new_row = "".join(row_chars)
            if len(new_row) != orig_len:
                raise RuntimeError(f"Row length mismatch in fixed block: {len(new_row)} != {orig_len}")
            for c, v in upd.items():
                if c in key_cols or c not in spans:
                    continue
                a, b = spans[c]
                got = new_row[a:b].strip()
                want = format_like_field(row[a:b], b - a, float(v)).strip()
                if got != want:
                    raise RuntimeError(f"Round-trip mismatch for {c} in fixed block: {got} != {want}")
            out.append(new_row + ending)
            continue
        out.append(line)
    return out


def rewrite_fixed_block(
    path: Path,
    header_prefix: str,
    key_cols: list[str],
    updates: list[dict[str, float]],
    required_cols: set[str] | None = None,
) -> None:
    raw = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    out = apply_fixed_block_updates(raw, header_prefix, key_cols, updates, required_cols)
    path.write_text("".join(out), encoding="utf-8")


def rewrite_fixed_block_from_template(
    template_path: Path,
    output_path: Path,
    header_prefix: str,
    key_cols: list[str],
    updates: list[dict[str, float]],
    required_cols: set[str] | None = None,
) -> None:
    raw = template_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    out = apply_fixed_block_updates(raw, header_prefix, key_cols, updates, required_cols)
    output_path.write_text("".join(out), encoding="utf-8")


def rewrite_initial_sh2o(filex_in: Path, filex_out: Path, sh2o_by_icbl: dict[int, float]) -> None:
    updates = [{"ICBL": int(k), "SH2O": float(v)} for k, v in sh2o_by_icbl.items()]
    rewrite_fixed_block_from_template(
        filex_in,
        filex_out,
        "@C",
        ["ICBL"],
        updates,
        required_cols={"ICBL", "SH2O"},
    )


def rewrite_wth_daily(wth_path: Path, updates_by_date: list[dict[str, float]]) -> None:
    rewrite_fixed_block(wth_path, "@DATE", ["DATE"], updates_by_date)


def rewrite_sol_layers(sol_path: Path, updates_by_slb: list[dict[str, float]]) -> None:
    rewrite_fixed_block(sol_path, "@SLB", ["SLB"], updates_by_slb)
