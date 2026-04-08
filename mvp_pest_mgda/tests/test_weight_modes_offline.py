from __future__ import annotations

import importlib.util
import csv
import json
import os
import sys
import tempfile
import types
import unittest
import uuid
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SANDBOX = ROOT.parent / "autoresearch_sandbox"
FIXTURE_CASE = ROOT / "tests" / "fixtures" / "mini_case" / "phase1_case"
for path in (SRC, SANDBOX):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import phase1_runner


def load_eval_module():
    sys.modules.setdefault("pyemu", types.ModuleType("pyemu"))
    module_name = f"test_eval_weight_modes_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, SANDBOX / "eval.py")
    if spec is None or spec.loader is None:
        raise ImportError("Unable to load eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def append_tsv_row(path: Path, fieldnames: list[str], row: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writerow(row)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class TestWeightModesOffline(unittest.TestCase):
    def test_normalize_weight_mode_aliases_cover_main_matrix_modes(self) -> None:
        eval_module = load_eval_module()

        self.assertEqual(eval_module.normalize_weight_mode("w0"), "w0_raw_identity")
        self.assertEqual(eval_module.normalize_weight_mode("w1"), "w1_inverse_variance")
        self.assertEqual(eval_module.normalize_weight_mode("w7"), "w7_equal_contribution")
        self.assertEqual(eval_module.normalize_weight_mode("w8"), "w8_dssat_group_max")
        self.assertEqual(eval_module.normalize_weight_mode("w4"), "w_custom_strategy")
        self.assertEqual(eval_module.normalize_weight_mode("w6"), "w_custom_strategy")

    def test_validate_experiment_configuration_rejects_invalid_weight_grouping_pair(self) -> None:
        eval_module = load_eval_module()

        with (
            patch.object(eval_module, "WEIGHT_MODE", "w7_equal_contribution"),
            patch.object(eval_module, "GROUPING_MODE", "g1_flat_all_in_one"),
            patch.object(eval_module, "CALIBRATION_SEQUENCE", "s2_sequential_phase"),
            patch.object(eval_module, "resolve_optimizer_mode", return_value="o1_least_squares"),
        ):
            error = eval_module.validate_experiment_configuration()

        self.assertEqual(error, "w7_equal_contribution requires g3_dssat_extended grouping")

    def test_compute_group_base_weight_supports_w0_and_w8_modes(self) -> None:
        eval_module = load_eval_module()
        metrics = {"hwam": object(), "laix": object()}
        grouped = {"obs_yield": ["hwam"], "obs_canopy": ["laix"]}

        with (
            patch.object(eval_module, "group_metrics_for_selection", return_value=grouped),
            patch.object(eval_module, "normalized_group_weights", side_effect=lambda weights: weights),
        ):
            weights_w0 = eval_module.compute_group_base_weight(metrics, weight_mode="w0_raw_identity", grouping_mode="g3_dssat_extended")

        self.assertEqual(weights_w0, {"obs_yield": 1.0, "obs_canopy": 1.0})

        with (
            patch.object(eval_module, "group_metrics_for_selection", return_value=grouped),
            patch.object(eval_module, "observed_group_max", side_effect=[20.0, 5.0]),
            patch.object(eval_module, "normalized_group_weights", side_effect=lambda weights: weights),
        ):
            weights_w8 = eval_module.compute_group_base_weight(metrics, weight_mode="w8_dssat_group_max", grouping_mode="g3_dssat_extended")

        self.assertEqual(weights_w8, {"obs_yield": 0.05, "obs_canopy": 0.2})

    def test_compute_group_base_weight_supports_w1_and_w7_modes(self) -> None:
        eval_module = load_eval_module()
        metrics = {"hwam": object(), "laix": object()}
        grouped = {"obs_yield": ["hwam"], "obs_canopy": ["laix"]}

        observed_lookup = {
            "hwam": np.array([100.0, 120.0], dtype=float),
            "laix": np.array([2.0, 4.0], dtype=float),
        }

        with (
            patch.object(eval_module, "group_metrics_for_selection", return_value=grouped),
            patch.object(eval_module, "observed_metric_values", side_effect=lambda name, split_name="train": observed_lookup[name]),
            patch.object(eval_module, "normalized_group_weights", side_effect=lambda weights: weights),
        ):
            weights_w1 = eval_module.compute_group_base_weight(metrics, weight_mode="w1_inverse_variance", grouping_mode="g3_dssat_extended")

        self.assertAlmostEqual(weights_w1["obs_yield"], 0.01, places=6)
        self.assertAlmostEqual(weights_w1["obs_canopy"], 1.0, places=6)

        residual_lookup = {
            "hwam": np.array([10.0, -10.0], dtype=float),
            "laix": np.array([1.0, -1.0], dtype=float),
        }

        with (
            patch.object(eval_module, "group_metrics_for_selection", return_value=grouped),
            patch.object(
                eval_module,
                "metric_residual_array",
                side_effect=lambda metric_name, reference_sim_metrics, split_name="train", normalize=False: residual_lookup[metric_name],
            ),
            patch.object(eval_module, "normalized_group_weights", side_effect=lambda weights: weights),
        ):
            weights_w7 = eval_module.compute_group_base_weight(
                metrics,
                weight_mode="w7_equal_contribution",
                grouping_mode="g3_dssat_extended",
                reference_sim_metrics={"hwam": np.array([1.0]), "laix": np.array([1.0])},
            )

        self.assertAlmostEqual(weights_w7["obs_yield"], 0.01, places=6)
        self.assertAlmostEqual(weights_w7["obs_canopy"], 1.0, places=6)

    def test_weight_modes_propagate_into_protocol_artifacts_and_phase1_exports(self) -> None:
        weight_cases = [
            ("W0", "w0_raw_identity", "s1_naive_joint", "g1_flat_all_in_one", "external", False),
            ("W4", "w4_min_max_equal", "s1_naive_joint", "g3_dssat_extended", None, True),
            ("W6", "w6_log_transformation", "s1_naive_joint", "g3_dssat_extended", None, True),
            ("W8", "w8_dssat_group_max", "s2_sequential_phase", "g3_dssat_extended", "external", False),
            ("W1", "w1_inverse_variance", "s2_sequential_phase", "g3_dssat_extended", None, False),
            ("W7", "w7_equal_contribution", "s2_sequential_phase", "g3_dssat_extended", None, False),
        ]

        for weight_code, weight_mode, sequence, grouping, baseline_source, uses_benchmark_strategy in weight_cases:
            with self.subTest(weight_code=weight_code, weight_mode=weight_mode):
                with tempfile.TemporaryDirectory() as tmpdir:
                    session_root = Path(tmpdir) / f"session_{weight_code.lower()}"
                    phase1_runner.initialize_output_tables(session_root)
                    config_path = Path(tmpdir) / f"project_{weight_code.lower()}.json"
                    config_path.write_text(
                        json.dumps({"paths": {"dssat_case_dir": str(FIXTURE_CASE.resolve())}}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    job = {
                        "run_id": f"{weight_code}_run",
                        "combo_key": f"{weight_code}_O1_S2_G3",
                        "crop": "Wheat",
                        "config_path": str(config_path),
                        "weight_code": weight_code,
                        "weight": weight_mode,
                        "engine": "o6_pestpp_glm",
                        "sequence": sequence,
                        "grouping": grouping,
                        "plan": "BatchB",
                        "baseline_source": baseline_source,
                        "budget": "standard",
                        "random_seed": 42,
                        "train_only": True,
                    }

                    def fake_subprocess_run(command, env=None, cwd=None, capture_output=False, text=False):
                        workspace_dir = Path(str(cwd))
                        write_json(
                            workspace_dir / "run_manifest.json",
                            {
                                "run_id": env["AR_RUN_ID"],
                                "requested": {"weight": env["AR_WEIGHTING"], "sequence": env["AR_SEQUENCE"], "grouping": env["AR_GROUPING"]},
                                "resolved": {"weight": env["AR_WEIGHTING"], "engine": env["AR_ENGINE"]},
                            },
                        )
                        write_json(
                            workspace_dir / "contract_report.json",
                            {
                                "run_id": env["AR_RUN_ID"],
                                "requested": {"weight": env["AR_WEIGHTING"], "engine": env["AR_ENGINE"]},
                                "resolved": {"weight": env["AR_WEIGHTING"], "sequence": env["AR_SEQUENCE"], "grouping": env["AR_GROUPING"]},
                                "summary": {
                                    "active_groups": ["obs_yield", "obs_phenology"] if env["AR_GROUPING"] == "g3_dssat_extended" else ["obs_yield"],
                                    "fallback_count": 1 if env["AR_WEIGHTING"] in {"w1_inverse_variance", "w7_equal_contribution"} else 0,
                                    "zero_weight_count": 1 if env["AR_WEIGHTING"] == "w8_dssat_group_max" else 0,
                                },
                            },
                        )
                        append_tsv_row(
                            session_root / "phase1_experiment_summary.tsv",
                            phase1_runner.SUMMARY_FIELDS,
                            {
                                "run_id": env["AR_RUN_ID"],
                                "combo_key": env["AR_COMBO_KEY"],
                                "executed_at": "2026-04-08T12:00:00",
                                "plan": env["AR_PLAN"],
                                "weight": weight_code,
                                "engine": "O1",
                                "budget": env["AR_BUDGET"],
                                "sequence": "S2" if env["AR_SEQUENCE"] == "s2_sequential_phase" else "S1",
                                "grouping": "G3" if env["AR_GROUPING"] == "g3_dssat_extended" else "G1",
                                "status": "success",
                                "score": "0.250000",
                                "delta_vs_b0": "",
                                "delta_vs_b1": "",
                                "delta_vs_negative_ref": "",
                                "better_than_b0": "",
                                "train_mean_nrmse": "0.100000",
                                "valid_mean_nrmse": "0.200000",
                                "all_mean_nrmse": "0.150000",
                                "train_yield_nrmse": "0.100000",
                                "train_yield_bias": "0.020000",
                                "valid_yield_nrmse": "0.200000",
                                "valid_yield_bias": "-0.010000",
                                "duration_sec": "1.000000",
                                "validation_enabled": "true",
                                "train_trts": "1",
                                "valid_trts": "2",
                                "workspace_dir": str(workspace_dir),
                                "eval_call_count": "5",
                                "run_model_invocations": "1",
                                "dssat_treatment_calls": "2",
                                "dssat_wall_sec": "0.500000",
                            },
                        )
                        return CompletedProcess(command, 0, stdout="ok", stderr="")

                    with (
                        patch.object(phase1_runner, "python_executable", return_value="python"),
                        patch.object(phase1_runner.subprocess, "run", side_effect=fake_subprocess_run),
                    ):
                        result = phase1_runner.run_job(job, session_root)

                    workspace_dir = session_root / "workspaces" / job["run_id"]
                    self.assertEqual(result["status"], "success")
                    run_manifest = json.loads((workspace_dir / "run_manifest.json").read_text(encoding="utf-8"))
                    contract_report = json.loads((workspace_dir / "contract_report.json").read_text(encoding="utf-8"))
                    self.assertEqual(run_manifest["requested"]["weight"], weight_mode)
                    self.assertEqual(contract_report["resolved"]["weight"], weight_mode)
                    self.assertEqual(contract_report["resolved"]["sequence"], sequence)
                    self.assertEqual(contract_report["resolved"]["grouping"], grouping)

                    summary_lines = (session_root / "phase1_experiment_summary.tsv").read_text(encoding="utf-8").splitlines()
                    self.assertEqual(len(summary_lines), 2)
                    self.assertIn(f"\t{weight_code}\tO1\tstandard\t", summary_lines[1])

                    strategy_text = (workspace_dir / "strategy.py").read_text(encoding="utf-8")
                    if weight_code == "W4":
                        self.assertIn("max_err_y", strategy_text)
                    elif weight_code == "W6":
                        self.assertIn("log_sim_y", strategy_text)
                    elif uses_benchmark_strategy:
                        self.assertNotEqual(strategy_text, phase1_runner.CURRENT_STRATEGY_SOURCE)
                    else:
                        self.assertEqual(strategy_text, phase1_runner.CURRENT_STRATEGY_SOURCE)


if __name__ == "__main__":
    unittest.main()
