from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from calibration_core.fixed_width import (
    apply_fixed_block_updates,
    format_like_field,
    parse_fixed_header_spans,
    rewrite_initial_sh2o,
    rewrite_sol_layers,
    rewrite_wth_daily,
)


def _build_fixed_row(header: str, values: dict[str, str]) -> str:
    spans = parse_fixed_header_spans(header.rstrip("\n"))
    width = max(end for _, end in spans.values())
    row = [" "] * width
    for key, value in values.items():
        start, end = spans[key]
        text = str(value).rjust(end - start)
        if len(text) != end - start:
            raise ValueError(f"value for {key} does not fit width")
        row[start:end] = list(text)
    return "".join(row) + "\n"


class TestFixedWidthCharacterization(unittest.TestCase):
    def test_format_like_field_preserves_dot_decimal_style(self) -> None:
        self.assertEqual(format_like_field(".250", 4, 0.375), ".375")
        self.assertEqual(format_like_field("-.25", 4, -0.5), "-.50")

    def test_apply_fixed_block_updates_preserves_row_length(self) -> None:
        header = "@C   ICBL  SH2O  SNH4\n"
        row = _build_fixed_row(header, {"ICBL": "15", "SH2O": ".250", "SNH4": "2.50"})
        raw = ["*INITIAL CONDITIONS\n", header, row]

        out = apply_fixed_block_updates(
            raw,
            "@C",
            ["ICBL"],
            [{"ICBL": 15, "SH2O": 0.375, "SNH4": 4.25}],
            required_cols={"ICBL", "SH2O"},
        )

        self.assertEqual(len(out[2].rstrip("\n")), len(row.rstrip("\n")))
        self.assertIn(".375", out[2])
        self.assertIn("4.25", out[2])

    def test_rewrite_initial_sh2o_from_template_updates_only_target_rows(self) -> None:
        header = "@C   ICBL  SH2O  SNH4\n"
        row_1 = _build_fixed_row(header, {"ICBL": "15", "SH2O": ".250", "SNH4": "2.50"})
        row_2 = _build_fixed_row(header, {"ICBL": "30", "SH2O": ".310", "SNH4": "3.75"})
        template = "*INITIAL CONDITIONS\n" + header + row_1 + row_2

        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.X"
            output_path = Path(tmp) / "output.X"
            template_path.write_text(template, encoding="utf-8")

            rewrite_initial_sh2o(template_path, output_path, {15: 0.401})

            lines = output_path.read_text(encoding="utf-8").splitlines()
            self.assertIn(".401", lines[2])
            self.assertIn(".310", lines[3])
            self.assertEqual(len(lines[2]), len(row_1.rstrip("\n")))
            self.assertEqual(len(lines[3]), len(row_2.rstrip("\n")))

    def test_rewrite_wth_daily_preserves_date_key_and_line_width(self) -> None:
        header = "@DATE  SRAD  TMAX  TMIN  RAIN\n"
        row_1 = _build_fixed_row(header, {"DATE": "24001", "SRAD": "18.5", "TMAX": "30.1", "TMIN": "18.2", "RAIN": "0.0"})
        row_2 = _build_fixed_row(header, {"DATE": "24002", "SRAD": "19.0", "TMAX": "31.1", "TMIN": "19.2", "RAIN": "1.0"})

        with tempfile.TemporaryDirectory() as tmp:
            wth_path = Path(tmp) / "TEST.WTH"
            wth_path.write_text("*WEATHER DATA\n" + header + row_1 + row_2, encoding="utf-8")

            rewrite_wth_daily(wth_path, [{"DATE": 24002, "RAIN": 12.5, "SRAD": 22.0}])

            lines = wth_path.read_text(encoding="utf-8").splitlines()
            self.assertIn("24002", lines[3])
            self.assertIn("12.5", lines[3])
            self.assertIn("22.0", lines[3])
            self.assertEqual(len(lines[3]), len(row_2.rstrip("\n")))

    def test_rewrite_sol_layers_preserves_layer_width(self) -> None:
        header = "@SLB  SLLL  SDUL  SSAT\n"
        row_1 = _build_fixed_row(header, {"SLB": "15", "SLLL": ".120", "SDUL": ".260", "SSAT": ".410"})
        row_2 = _build_fixed_row(header, {"SLB": "30", "SLLL": ".140", "SDUL": ".280", "SSAT": ".430"})

        with tempfile.TemporaryDirectory() as tmp:
            sol_path = Path(tmp) / "TEST.SOL"
            sol_path.write_text("*SOIL PROFILE\n" + header + row_1 + row_2, encoding="utf-8")

            rewrite_sol_layers(sol_path, [{"SLB": 30, "SDUL": 0.305, "SSAT": 0.455}])

            lines = sol_path.read_text(encoding="utf-8").splitlines()
            self.assertIn(".305", lines[3])
            self.assertIn(".455", lines[3])
            self.assertEqual(len(lines[3]), len(row_2.rstrip("\n")))


if __name__ == "__main__":
    unittest.main()
