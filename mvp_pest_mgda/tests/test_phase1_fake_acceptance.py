from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT.parent / "autoresearch_sandbox"
if str(SANDBOX) not in sys.path:
    sys.path.insert(0, str(SANDBOX))

import phase1_postprocess
import phase1_runner

FIXTURE_CASE = Path(__file__).resolve().parent / "fixtures" / "mini_case" / "phase1_case"
GOLDEN_ROOT = Path(__file__).resolve().parent / "fixtures" / "golden" / "phase1_fake_acceptance"


def append_tsv_row(path: Path, fieldnames: list[str], row: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writerow(row)


def read_tsv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_payload(payload: object, workspace_dir: Path) -> object:
    replacements = {
        str(workspace_dir): "__WORKSPACE__",
        str(workspace_dir / "dssat_case"): "__CASE_DIR__",
        str(workspace_dir / "project_wheat.json"): "__PROJECT_CONFIG__",
    }
    if isinstance(payload, dict):
        normalized: dict[str, object] = {}
        for key, value in payload.items():
            if key == "created_at":
                normalized[key] = "__TIMESTAMP__"
            else:
                normalized[key] = normalize_payload(value, workspace_dir)
        return normalized
    if isinstance(payload, list):
        return [normalize_payload(item, workspace_dir) for item in payload]
    if isinstance(payload, str):
        return replacements.get(payload, payload)
    return payload


def normalize_session_text(text: str, session_root: Path) -> str:
    return text.replace(str(session_root), "__SESSION__")


def build_fake_workspace_artifacts(
    workspace_dir: Path,
    run_id: str,
    *,
    weight_mode: str,
    engine: str,
    sequence: str,
    grouping: str,
    active_groups: list[str],
    fallback_count: int,
    zero_weight_count: int,
) -> None:
    run_manifest_payload = {
        "run_id": run_id,
        "crop": "wheat",
        "requested": {
            "weight": weight_mode,
            "engine": engine,
            "sequence": sequence,
            "grouping": grouping,
        },
        "resolved": {
            "weight": weight_mode,
            "engine": engine,
            "sequence": sequence,
            "grouping": grouping,
        },
        "paths": {
            "runtime_dir": str(workspace_dir),
            "case_dir": str(workspace_dir / "dssat_case"),
            "project_config_path": str(workspace_dir / "project_wheat.json"),
        },
        "scenario": {"filex_name": "SAMPLE.WHX", "trts": [1]},
        "summary": {"active_groups": active_groups, "fallback_count": fallback_count, "zero_weight_count": zero_weight_count},
    }
    contract_report_payload = {
        "run_id": run_id,
        "status": "success",
        "crop": "wheat",
        "requested": {
            "weight": weight_mode,
            "engine": engine,
            "sequence": sequence,
            "grouping": grouping,
        },
        "resolved": {
            "weight": weight_mode,
            "engine": engine,
            "sequence": sequence,
            "grouping": grouping,
        },
        "paths": {
            "runtime_dir": str(workspace_dir),
            "case_dir": str(workspace_dir / "dssat_case"),
        },
        "protocol": {"active_groups": active_groups, "primary_metric": "hwam"},
        "issues": (
            [
                {
                    "code": "weight_fallback",
                    "severity": "warning",
                    "details": {"group": "obs_yield", "reason": "variance_unavailable_used_sigma"},
                }
            ]
            if fallback_count
            else []
        ),
        "weight_fallbacks": (
            [
                {
                    "group": "obs_yield",
                    "reason": "variance_unavailable_used_sigma",
                    "applied_weight": 0.5,
                }
            ]
            if fallback_count
            else []
        ),
        "zero_weight_observations": (
            [
                {
                    "obs_name": "laix_t01",
                    "group": "obs_canopy",
                    "reason": "inactive_metric",
                    "trt": 1,
                }
            ]
            if zero_weight_count
            else []
        ),
        "summary": {"active_groups": active_groups, "fallback_count": fallback_count, "zero_weight_count": zero_weight_count},
    }
    write_json(workspace_dir / "run_manifest.json", run_manifest_payload)
    write_json(workspace_dir / "contract_report.json", contract_report_payload)


def append_fake_phase1_exports(
    session_root: Path,
    workspace_dir: Path,
    run_id: str,
    combo_key: str,
    *,
    plan: str,
    weight_code: str,
    engine_code: str,
    sequence_code: str,
    grouping_code: str,
    score: str,
    train_mean_nrmse: str,
    valid_mean_nrmse: str,
    all_mean_nrmse: str,
) -> None:
    append_tsv_row(
        session_root / "phase1_experiment_summary.tsv",
        phase1_runner.SUMMARY_FIELDS,
        {
            "run_id": run_id,
            "combo_key": combo_key,
            "executed_at": "2026-04-08T12:00:00",
            "plan": plan,
            "weight": weight_code,
            "engine": engine_code,
            "budget": "standard",
            "sequence": sequence_code,
            "grouping": grouping_code,
            "status": "success",
            "score": score,
            "delta_vs_b0": "",
            "delta_vs_b1": "",
            "delta_vs_negative_ref": "",
            "better_than_b0": "",
            "train_mean_nrmse": train_mean_nrmse,
            "valid_mean_nrmse": valid_mean_nrmse,
            "all_mean_nrmse": all_mean_nrmse,
            "train_yield_nrmse": train_mean_nrmse,
            "train_yield_bias": "0.020000",
            "valid_yield_nrmse": valid_mean_nrmse,
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
    append_tsv_row(
        session_root / "phase1_aggregate_metrics.tsv",
        phase1_runner.AGG_FIELDS,
        {
            "run_id": run_id,
            "plan": plan,
            "weight": weight_code,
            "engine": engine_code,
            "budget": "standard",
            "sequence": sequence_code,
            "grouping": grouping_code,
            "status": "success",
            "split": "train",
            "metric": "hwam",
            "count": "1",
            "nrmse": train_mean_nrmse,
            "bias": "0.020000",
        },
    )
    append_tsv_row(
        session_root / "phase1_treatment_metrics.tsv",
        phase1_runner.TRT_FIELDS,
        {
            "run_id": run_id,
            "plan": plan,
            "weight": weight_code,
            "engine": engine_code,
            "budget": "standard",
            "sequence": sequence_code,
            "grouping": grouping_code,
            "status": "success",
            "trt": "1",
            "split": "train",
            "metric": "hwam",
            "observed": "100.000000",
            "simulated": "98.000000",
            "error": "-2.000000",
            "abs_error": "2.000000",
            "relative_error": "-0.020000",
        },
    )
    append_tsv_row(
        session_root / "phase1_parameters.tsv",
        phase1_runner.PARAM_FIELDS,
        {
            "run_id": run_id,
            "crop": "wheat",
            "combo_key": combo_key,
            "param_name": "P1",
            "param_value": "1.000000",
            "lower_bound": "0.000000",
            "upper_bound": "2.000000",
            "is_at_lower_bound": "false",
            "is_at_upper_bound": "false",
            "normalized_distance_to_b0": "0.100000",
        },
    )
    append_tsv_row(
        session_root / "phase1_figure_ready.tsv",
        phase1_runner.FIG_FIELDS,
        {
            "run_id": run_id,
            "score_rank": "1",
            "combo_key": combo_key,
            "plan": plan,
            "weight": weight_code,
            "engine": engine_code,
            "budget": "standard",
            "sequence": sequence_code,
            "grouping": grouping_code,
            "status": "success",
            "score": score,
            "metric": "hwam",
            "split": "train",
            "trt": "1",
            "panel_key": "hwam|train",
            "series_key": combo_key,
            "point_key": f"{run_id}|hwam|t1",
            "x_observed": "100.000000",
            "y_simulated": "98.000000",
            "residual": "-2.000000",
            "abs_residual": "2.000000",
            "relative_error": "-0.020000",
            "panel_count": "1",
            "panel_nrmse": "0.100000",
            "panel_bias": "0.020000",
        },
    )


def protocol_spec(combo_key: str) -> dict[str, object]:
    specs: dict[str, dict[str, object]] = {
        "W0_O1_S1_G1": {
            "plan": "BatchD",
            "weight_code": "W0",
            "weight_mode": "w0_raw_identity",
            "engine_code": "O1",
            "engine": "o6_pestpp_glm",
            "sequence_code": "S1",
            "sequence": "s1_naive_joint",
            "grouping_code": "G1",
            "grouping": "g1_flat_all_in_one",
            "active_groups": ["obs_yield"],
            "fallback_count": 1,
            "zero_weight_count": 1,
            "score": "0.250000",
            "train_mean_nrmse": "0.100000",
            "valid_mean_nrmse": "0.200000",
            "all_mean_nrmse": "0.150000",
        },
        "W8_O1_S2_G3": {
            "plan": "BatchD",
            "weight_code": "W8",
            "weight_mode": "w8_dssat_group_max",
            "engine_code": "O1",
            "engine": "o6_pestpp_glm",
            "sequence_code": "S2",
            "sequence": "s2_sequential_phase",
            "grouping_code": "G3",
            "grouping": "g3_dssat_extended",
            "active_groups": ["obs_yield", "obs_phenology", "obs_canopy"],
            "fallback_count": 2,
            "zero_weight_count": 1,
            "score": "0.180000",
            "train_mean_nrmse": "0.080000",
            "valid_mean_nrmse": "0.120000",
            "all_mean_nrmse": "0.100000",
        },
        "W4_O2_S2_G3": {
            "plan": "BatchD",
            "weight_code": "W4",
            "weight_mode": "w4_min_max_equal",
            "engine_code": "O2",
            "engine": "o2_pestpp_ies",
            "sequence_code": "S2",
            "sequence": "s2_sequential_phase",
            "grouping_code": "G3",
            "grouping": "g3_dssat_extended",
            "active_groups": ["obs_yield", "obs_phenology", "obs_canopy"],
            "fallback_count": 0,
            "zero_weight_count": 0,
            "score": "0.210000",
            "train_mean_nrmse": "0.090000",
            "valid_mean_nrmse": "0.140000",
            "all_mean_nrmse": "0.110000",
        },
        "W6_O1_S2_G3": {
            "plan": "BatchD",
            "weight_code": "W6",
            "weight_mode": "w6_log_transformation",
            "engine_code": "O1",
            "engine": "o6_pestpp_glm",
            "sequence_code": "S2",
            "sequence": "s2_sequential_phase",
            "grouping_code": "G3",
            "grouping": "g3_dssat_extended",
            "active_groups": ["obs_yield", "obs_phenology", "obs_canopy"],
            "fallback_count": 0,
            "zero_weight_count": 0,
            "score": "0.230000",
            "train_mean_nrmse": "0.095000",
            "valid_mean_nrmse": "0.150000",
            "all_mean_nrmse": "0.120000",
        },
        "W1_O1_S2_G3": {
            "plan": "BatchD",
            "weight_code": "W1",
            "weight_mode": "w1_inverse_variance",
            "engine_code": "O1",
            "engine": "o6_pestpp_glm",
            "sequence_code": "S2",
            "sequence": "s2_sequential_phase",
            "grouping_code": "G3",
            "grouping": "g3_dssat_extended",
            "active_groups": ["obs_yield", "obs_phenology", "obs_canopy"],
            "fallback_count": 1,
            "zero_weight_count": 0,
            "score": "0.195000",
            "train_mean_nrmse": "0.085000",
            "valid_mean_nrmse": "0.125000",
            "all_mean_nrmse": "0.105000",
        },
        "W7_O1_S2_G3": {
            "plan": "BatchD",
            "weight_code": "W7",
            "weight_mode": "w7_equal_contribution",
            "engine_code": "O1",
            "engine": "o6_pestpp_glm",
            "sequence_code": "S2",
            "sequence": "s2_sequential_phase",
            "grouping_code": "G3",
            "grouping": "g3_dssat_extended",
            "active_groups": ["obs_yield", "obs_phenology", "obs_canopy"],
            "fallback_count": 2,
            "zero_weight_count": 0,
            "score": "0.205000",
            "train_mean_nrmse": "0.088000",
            "valid_mean_nrmse": "0.130000",
            "all_mean_nrmse": "0.109000",
        },
    }
    return specs[combo_key]


class TestPhase1FakeAcceptance(unittest.TestCase):
    def test_phase1_fake_acceptance_generates_multi_protocol_outputs_and_matches_goldens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_root = root / "phase1_session"
            config_path = root / "project_wheat.json"
            config_path.write_text(
                json.dumps({"paths": {"dssat_case_dir": str(FIXTURE_CASE.resolve())}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            def fake_subprocess_run(command, env=None, cwd=None, capture_output=False, text=False, check=False):
                target = str(command[1]) if len(command) > 1 else ""
                if target.endswith("eval.py"):
                    workspace_dir = Path(cwd)
                    spec = protocol_spec(str(env["AR_COMBO_KEY"]))
                    build_fake_workspace_artifacts(
                        workspace_dir,
                        str(env["AR_RUN_ID"]),
                        weight_mode=str(spec["weight_mode"]),
                        engine=str(spec["engine"]),
                        sequence=str(spec["sequence"]),
                        grouping=str(spec["grouping"]),
                        active_groups=list(spec["active_groups"]),
                        fallback_count=int(spec["fallback_count"]),
                        zero_weight_count=int(spec["zero_weight_count"]),
                    )
                    append_fake_phase1_exports(
                        Path(str(env["AR_PHASE1_OUTPUT_DIR"])),
                        workspace_dir,
                        str(env["AR_RUN_ID"]),
                        str(env["AR_COMBO_KEY"]),
                        plan=str(spec["plan"]),
                        weight_code=str(spec["weight_code"]),
                        engine_code=str(spec["engine_code"]),
                        sequence_code=str(spec["sequence_code"]),
                        grouping_code=str(spec["grouping_code"]),
                        score=str(spec["score"]),
                        train_mean_nrmse=str(spec["train_mean_nrmse"]),
                        valid_mean_nrmse=str(spec["valid_mean_nrmse"]),
                        all_mean_nrmse=str(spec["all_mean_nrmse"]),
                    )
                    return CompletedProcess(command, 0, stdout="fake eval ok", stderr="")
                if target.endswith("phase1_postprocess.py"):
                    with patch.object(sys, "argv", ["phase1_postprocess.py", "--input-dir", str(command[3])]):
                        phase1_postprocess.main()
                    return CompletedProcess(command, 0, stdout="fake postprocess ok", stderr="")
                raise AssertionError(f"Unexpected subprocess command: {command}")

            combo_keys = [
                "W0_O1_S1_G1",
                "W4_O2_S2_G3",
                "W6_O1_S2_G3",
                "W8_O1_S2_G3",
                "W1_O1_S2_G3",
                "W7_O1_S2_G3",
            ]
            fake_jobs = []
            for suffix, combo_key in (
                ("abcdef", "W0_O1_S1_G1"),
                ("w4cell", "W4_O2_S2_G3"),
                ("w6cell", "W6_O1_S2_G3"),
                ("w8cell", "W8_O1_S2_G3"),
                ("w1cell", "W1_O1_S2_G3"),
                ("w7cell", "W7_O1_S2_G3"),
            ):
                spec = protocol_spec(combo_key)
                fake_jobs.append(
                    {
                        "run_id": f"{combo_key}_wheat_rep0_{suffix}",
                        "combo_key": combo_key,
                        "crop": "Wheat",
                        "config_path": str(config_path),
                        "weight_code": spec["weight_code"],
                        "weight": spec["weight_mode"],
                        "engine": spec["engine"],
                        "sequence": spec["sequence"],
                        "grouping": spec["grouping"],
                        "plan": spec["plan"],
                        "baseline_source": "external" if combo_key == "W0_O1_S1_G1" else None,
                        "budget": "standard",
                        "random_seed": 42,
                        "train_only": True,
                    }
                )

            with (
                patch.object(phase1_runner, "create_session_root", return_value=session_root),
                patch.object(phase1_runner, "resolve_crop_configs", return_value={"Wheat": config_path}),
                patch.object(phase1_runner, "build_jobs", return_value=(fake_jobs, {})),
                patch.object(phase1_runner, "python_executable", return_value="python"),
                patch.object(phase1_runner.subprocess, "run", side_effect=fake_subprocess_run),
                patch.object(
                    sys,
                    "argv",
                    [
                        "phase1_runner.py",
                        "--batch",
                        "BatchD",
                        "--repetitions",
                        "1",
                        "--budget",
                        "standard",
                        "--crops",
                        "Wheat",
                        "--combo-keys",
                        ",".join(combo_keys),
                        "--workers",
                        "1",
                    ],
                ),
            ):
                phase1_runner.main()

            summary_rows = read_tsv_rows(session_root / "phase1_experiment_summary.tsv")
            run_ids = {row["combo_key"]: row["run_id"] for row in summary_rows}
            for combo_key, run_id in run_ids.items():
                workspace_dir = session_root / "workspaces" / run_id
                self.assertTrue((workspace_dir / "dssat_case" / "SAMPLE.WHX").exists())
                self.assertTrue((workspace_dir / "dssat_case" / "GENOTYPE" / "SAMPLE.CUL").exists())
                run_manifest = normalize_payload(json.loads((workspace_dir / "run_manifest.json").read_text(encoding="utf-8")), workspace_dir)
                contract_report = normalize_payload(json.loads((workspace_dir / "contract_report.json").read_text(encoding="utf-8")), workspace_dir)
                spec = protocol_spec(combo_key)
                self.assertEqual(run_manifest["requested"]["weight"], spec["weight_mode"])
                self.assertEqual(contract_report["resolved"]["sequence"], spec["sequence"])
                self.assertEqual(contract_report["resolved"]["grouping"], spec["grouping"])
                self.assertEqual(contract_report["summary"]["fallback_count"], spec["fallback_count"])
                self.assertEqual(contract_report["summary"]["zero_weight_count"], spec["zero_weight_count"])

            for table_name in (
                "phase1_experiment_summary.tsv",
                "phase1_aggregate_metrics.tsv",
                "phase1_treatment_metrics.tsv",
                "phase1_parameters.tsv",
                "phase1_figure_ready.tsv",
                "phase1_derived_metrics.tsv",
                "phase1_combo_summary.tsv",
                "phase1_run_manifest.json",
            ):
                self.assertTrue((session_root / table_name).exists(), table_name)

            figure_ready_lines = (session_root / "phase1_figure_ready.tsv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(figure_ready_lines), 7)

            w0_workspace = session_root / "workspaces" / run_ids["W0_O1_S1_G1"]
            actual_run_manifest = normalize_payload(json.loads((w0_workspace / "run_manifest.json").read_text(encoding="utf-8")), w0_workspace)
            actual_contract_report = normalize_payload(json.loads((w0_workspace / "contract_report.json").read_text(encoding="utf-8")), w0_workspace)
            expected_run_manifest = json.loads((GOLDEN_ROOT / "expected_run_manifest.json").read_text(encoding="utf-8"))
            expected_contract_report = json.loads((GOLDEN_ROOT / "expected_contract_report.json").read_text(encoding="utf-8"))
            expected_session_manifest = json.loads((GOLDEN_ROOT / "expected_phase1_run_manifest_success.json").read_text(encoding="utf-8"))
            actual_session_manifest = normalize_payload(json.loads((session_root / "phase1_run_manifest.json").read_text(encoding="utf-8")), w0_workspace)
            actual_derived_text = normalize_session_text((session_root / "phase1_derived_metrics.tsv").read_text(encoding="utf-8"), session_root)
            actual_combo_summary_text = (session_root / "phase1_combo_summary.tsv").read_text(encoding="utf-8")
            expected_derived_text = (GOLDEN_ROOT / "expected_phase1_derived_metrics_success.tsv").read_text(encoding="utf-8")
            expected_combo_summary_text = (GOLDEN_ROOT / "expected_phase1_combo_summary_success.tsv").read_text(encoding="utf-8")

            self.assertEqual(actual_run_manifest, expected_run_manifest)
            self.assertEqual(actual_contract_report, expected_contract_report)
            self.assertEqual(actual_session_manifest, expected_session_manifest)
            self.assertEqual(actual_derived_text, expected_derived_text)
            self.assertEqual(actual_combo_summary_text, expected_combo_summary_text)

    def test_phase1_fake_acceptance_captures_degraded_and_failed_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_root = root / "phase1_session"
            config_path = root / "project_wheat.json"
            config_path.write_text(
                json.dumps({"paths": {"dssat_case_dir": str(FIXTURE_CASE.resolve())}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            def fake_subprocess_run(command, env=None, cwd=None, capture_output=False, text=False, check=False):
                target = str(command[1]) if len(command) > 1 else ""
                if target.endswith("eval.py"):
                    workspace_dir = Path(cwd)
                    combo_key = str(env["AR_COMBO_KEY"])
                    if combo_key == "W4_O2_S2_G3":
                        return CompletedProcess(command, 2, stdout="partial failure", stderr="simulated solver failure")
                    build_fake_workspace_artifacts(
                        workspace_dir,
                        str(env["AR_RUN_ID"]),
                        weight_mode="w8_dssat_group_max",
                        engine="o6_pestpp_glm",
                        sequence="s2_sequential_phase",
                        grouping="g3_dssat_extended",
                        active_groups=["obs_yield", "obs_phenology", "obs_canopy"],
                        fallback_count=3,
                        zero_weight_count=2,
                    )
                    append_fake_phase1_exports(
                        Path(str(env["AR_PHASE1_OUTPUT_DIR"])),
                        workspace_dir,
                        str(env["AR_RUN_ID"]),
                        combo_key,
                        plan="BatchD",
                        weight_code="W8",
                        engine_code="O1",
                        sequence_code="S2",
                        grouping_code="G3",
                        score="0.170000",
                        train_mean_nrmse="0.070000",
                        valid_mean_nrmse="0.110000",
                        all_mean_nrmse="0.090000",
                    )
                    return CompletedProcess(command, 0, stdout="fake eval ok", stderr="")
                if target.endswith("phase1_postprocess.py"):
                    with patch.object(sys, "argv", ["phase1_postprocess.py", "--input-dir", str(command[3])]):
                        phase1_postprocess.main()
                    return CompletedProcess(command, 0, stdout="fake postprocess ok", stderr="")
                raise AssertionError(f"Unexpected subprocess command: {command}")

            with (
                patch.object(phase1_runner, "create_session_root", return_value=session_root),
                patch.object(phase1_runner, "resolve_crop_configs", return_value={"Wheat": config_path}),
                patch.object(phase1_runner, "python_executable", return_value="python"),
                patch.object(phase1_runner.subprocess, "run", side_effect=fake_subprocess_run),
                patch.object(
                    phase1_runner.uuid,
                    "uuid4",
                    side_effect=[
                        SimpleNamespace(hex="w4fail123456"),
                        SimpleNamespace(hex="w8good123456"),
                    ],
                ),
                patch.object(
                    sys,
                    "argv",
                    [
                        "phase1_runner.py",
                        "--batch",
                        "BatchD",
                        "--repetitions",
                        "1",
                        "--budget",
                        "standard",
                        "--crops",
                        "Wheat",
                        "--combo-keys",
                        "W8_O1_S2_G3,W4_O2_S2_G3",
                        "--workers",
                        "1",
                    ],
                ),
            ):
                phase1_runner.main()

            summary_rows = read_tsv_rows(session_root / "phase1_experiment_summary.tsv")
            success_run_id = summary_rows[0]["run_id"]
            failed_run_id = json.loads((session_root / "phase1_run_manifest.json").read_text(encoding="utf-8"))["failures"][0]["run_id"]
            success_workspace = session_root / "workspaces" / success_run_id

            degraded_contract = normalize_payload(json.loads((success_workspace / "contract_report.json").read_text(encoding="utf-8")), success_workspace)
            self.assertEqual(degraded_contract["summary"]["fallback_count"], 3)
            self.assertEqual(degraded_contract["summary"]["zero_weight_count"], 2)
            self.assertEqual((session_root / "logs" / f"{failed_run_id}.stderr.log").read_text(encoding="utf-8"), "simulated solver failure")
            self.assertEqual((session_root / "logs" / f"{failed_run_id}.stdout.log").read_text(encoding="utf-8"), "partial failure")

            actual_session_manifest = normalize_payload(json.loads((session_root / "phase1_run_manifest.json").read_text(encoding="utf-8")), success_workspace)
            expected_session_manifest = json.loads((GOLDEN_ROOT / "expected_phase1_run_manifest_failed.json").read_text(encoding="utf-8"))
            self.assertEqual(actual_session_manifest, expected_session_manifest)

    def test_phase1_fake_acceptance_flags_silent_corruption_from_bad_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_root = root / "phase1_session"
            config_path = root / "project_wheat.json"
            config_path.write_text(
                json.dumps({"paths": {"dssat_case_dir": str(FIXTURE_CASE.resolve())}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            def fake_subprocess_run(command, env=None, cwd=None, capture_output=False, text=False, check=False):
                target = str(command[1]) if len(command) > 1 else ""
                if target.endswith("eval.py"):
                    workspace_dir = Path(cwd)
                    combo_key = str(env["AR_COMBO_KEY"])
                    if combo_key == "B0":
                        build_fake_workspace_artifacts(
                            workspace_dir,
                            str(env["AR_RUN_ID"]),
                            weight_mode="w0_raw_identity",
                            engine="o6_pestpp_glm",
                            sequence="s1_naive_joint",
                            grouping="g1_flat_all_in_one",
                            active_groups=["obs_yield"],
                            fallback_count=0,
                            zero_weight_count=0,
                        )
                        append_fake_phase1_exports(
                            Path(str(env["AR_PHASE1_OUTPUT_DIR"])),
                            workspace_dir,
                            str(env["AR_RUN_ID"]),
                            combo_key,
                            plan="Baselines",
                            weight_code="W0",
                            engine_code="O1",
                            sequence_code="S1",
                            grouping_code="G1",
                            score="0.300000",
                            train_mean_nrmse="0.110000",
                            valid_mean_nrmse="0.210000",
                            all_mean_nrmse="0.160000",
                        )
                    else:
                        build_fake_workspace_artifacts(
                            workspace_dir,
                            str(env["AR_RUN_ID"]),
                            weight_mode="w6_log_transformation",
                            engine="o6_pestpp_glm",
                            sequence="s2_sequential_phase",
                            grouping="g3_dssat_extended",
                            active_groups=["obs_yield", "obs_phenology"],
                            fallback_count=1,
                            zero_weight_count=0,
                        )
                        append_tsv_row(
                            session_root / "phase1_experiment_summary.tsv",
                            phase1_runner.SUMMARY_FIELDS,
                            {
                                "run_id": env["AR_RUN_ID"],
                                "combo_key": combo_key,
                                "executed_at": "2026-04-08T12:00:00",
                                "plan": "BatchD",
                                "weight": "W6",
                                "engine": "O1",
                                "budget": "standard",
                                "sequence": "S2",
                                "grouping": "G3",
                                "status": "success",
                                "score": "not_a_number",
                                "delta_vs_b0": "",
                                "delta_vs_b1": "",
                                "delta_vs_negative_ref": "",
                                "better_than_b0": "",
                                "train_mean_nrmse": "0.095000",
                                "valid_mean_nrmse": "",
                                "all_mean_nrmse": "0.160000",
                                "train_yield_nrmse": "0.095000",
                                "train_yield_bias": "",
                                "valid_yield_nrmse": "",
                                "valid_yield_bias": "",
                                "duration_sec": "",
                                "validation_enabled": "true",
                                "train_trts": "1",
                                "valid_trts": "2",
                                "workspace_dir": str(workspace_dir),
                                "eval_call_count": "bad_calls",
                                "run_model_invocations": "1",
                                "dssat_treatment_calls": "",
                                "dssat_wall_sec": "not_walltime",
                            },
                        )
                        append_tsv_row(
                            session_root / "phase1_aggregate_metrics.tsv",
                            phase1_runner.AGG_FIELDS,
                            {
                                "run_id": env["AR_RUN_ID"],
                                "plan": "BatchD",
                                "weight": "W6",
                                "engine": "O1",
                                "budget": "standard",
                                "sequence": "S2",
                                "grouping": "G3",
                                "status": "success",
                                "split": "train",
                                "metric": "",
                                "count": "1",
                                "nrmse": "bad_nrmse",
                                "bias": "",
                            },
                        )
                        append_tsv_row(
                            session_root / "phase1_parameters.tsv",
                            phase1_runner.PARAM_FIELDS,
                            {
                                "run_id": env["AR_RUN_ID"],
                                "crop": "wheat",
                                "combo_key": combo_key,
                                "param_name": "P1",
                                "param_value": "",
                                "lower_bound": "",
                                "upper_bound": "",
                                "is_at_lower_bound": "",
                                "is_at_upper_bound": "",
                                "normalized_distance_to_b0": "",
                            },
                        )
                        append_tsv_row(
                            session_root / "phase1_figure_ready.tsv",
                            phase1_runner.FIG_FIELDS,
                            {
                                "run_id": env["AR_RUN_ID"],
                                "score_rank": "1",
                                "combo_key": combo_key,
                                "plan": "BatchD",
                                "weight": "W6",
                                "engine": "O1",
                                "budget": "standard",
                                "sequence": "S2",
                                "grouping": "G3",
                                "status": "success",
                                "score": "not_a_number",
                                "metric": "hwam",
                                "split": "train",
                                "trt": "1",
                                "panel_key": "hwam|train",
                                "series_key": combo_key,
                                "point_key": f"{env['AR_RUN_ID']}|hwam|t1",
                                "x_observed": "100.000000",
                                "y_simulated": "",
                                "residual": "",
                                "abs_residual": "",
                                "relative_error": "",
                                "panel_count": "1",
                                "panel_nrmse": "",
                                "panel_bias": "",
                            },
                        )
                    return CompletedProcess(command, 0, stdout="fake eval ok", stderr="")
                if target.endswith("phase1_postprocess.py"):
                    with patch.object(sys, "argv", ["phase1_postprocess.py", "--input-dir", str(command[3])]):
                        phase1_postprocess.main()
                    return CompletedProcess(command, 0, stdout="fake postprocess ok", stderr="")
                raise AssertionError(f"Unexpected subprocess command: {command}")

            corrupt_jobs = [
                {
                    "run_id": "B0_wheat_rep0_base00",
                    "combo_key": "B0",
                    "crop": "Wheat",
                    "config_path": str(config_path),
                    "weight_code": "W0",
                    "weight": "w0_raw_identity",
                    "engine": "o6_pestpp_glm",
                    "sequence": "s1_naive_joint",
                    "grouping": "g1_flat_all_in_one",
                    "plan": "Baselines",
                    "baseline_source": "external",
                    "budget": "standard",
                    "random_seed": 42,
                    "train_only": True,
                },
                {
                    "run_id": "W6_O1_S2_G3_wheat_rep0_corrupt",
                    "combo_key": "W6_O1_S2_G3",
                    "crop": "Wheat",
                    "config_path": str(config_path),
                    "weight_code": "W6",
                    "weight": "w6_log_transformation",
                    "engine": "o6_pestpp_glm",
                    "sequence": "s2_sequential_phase",
                    "grouping": "g3_dssat_extended",
                    "plan": "BatchD",
                    "baseline_source": None,
                    "budget": "standard",
                    "random_seed": 42,
                    "train_only": True,
                },
            ]

            with (
                patch.object(phase1_runner, "create_session_root", return_value=session_root),
                patch.object(phase1_runner, "resolve_crop_configs", return_value={"Wheat": config_path}),
                patch.object(phase1_runner, "build_jobs", return_value=(corrupt_jobs, {})),
                patch.object(phase1_runner, "python_executable", return_value="python"),
                patch.object(phase1_runner.subprocess, "run", side_effect=fake_subprocess_run),
                patch.object(
                    sys,
                    "argv",
                    [
                        "phase1_runner.py",
                        "--batch",
                        "BatchD",
                        "--repetitions",
                        "1",
                        "--budget",
                        "standard",
                        "--crops",
                        "Wheat",
                        "--combo-keys",
                        "B0,W6_O1_S2_G3",
                        "--workers",
                        "1",
                    ],
                ),
            ):
                phase1_runner.main()

            derived_rows = read_tsv_rows(session_root / "phase1_derived_metrics.tsv")
            corrupt_row = next(row for row in derived_rows if row["combo_key"] == "W6_O1_S2_G3")
            self.assertEqual(corrupt_row["score"], "not_a_number")
            self.assertEqual(corrupt_row["delta_vs_b0"], "998.700000")
            self.assertEqual(corrupt_row["generalization_gap"], "0.000000")
            self.assertEqual(corrupt_row["boundary_hit_rate"], "0.000000")
            self.assertEqual(corrupt_row["param_shift_norm"], "0.000000")
            self.assertEqual(corrupt_row["group_balance_index"], "0.000000")
            self.assertEqual(corrupt_row["primary_score"], "0.160000")
            self.assertEqual(corrupt_row["eval_call_count"], "0")
            self.assertEqual(corrupt_row["dssat_treatment_calls"], "0")
            self.assertEqual(corrupt_row["dssat_wall_sec"], "0.000000")

            combo_rows = read_tsv_rows(session_root / "phase1_combo_summary.tsv")
            corrupt_combo = next(row for row in combo_rows if row["combo_key"] == "W6_O1_S2_G3")
            self.assertEqual(corrupt_combo["score_mean"], "")
            self.assertEqual(corrupt_combo["primary_score_mean"], "0.160000")
            self.assertEqual(corrupt_combo["boundary_hit_rate_mean"], "0.000000")
            self.assertEqual(corrupt_combo["group_balance_index_mean"], "0.000000")


if __name__ == "__main__":
    unittest.main()
