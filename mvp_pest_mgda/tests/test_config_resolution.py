from __future__ import annotations

import csv
import io
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from calibration_core import pest_builder as core_pest_builder
from calibration_core import pest_runner as core_pest_runner
import compare_three
import compare_eval
import build_pest_setup
import case_runtime
import crop_registry
from case_runtime import (
    CaseInputPlan,
    CaseRuntime,
    ObservationRuntime,
    OutputContract,
    RuntimeFileState,
    build_pest_output_text,
    dedupe_codes,
    infer_cul_path_from_inp,
    parse_var_codes,
    parse_inp_cultivar_reference,
    read_wht_dates_by_trt,
    resolve_allow_missing_dates,
    resolve_case_dir,
    resolve_case_runtime,
    resolve_case_runtime_config,
    resolve_cul_updates,
    resolve_input_plan,
    resolve_metrics_cfg,
    resolve_obs_a_path,
    resolve_observation_contracts,
    resolve_observation_runtime,
    resolve_output_contract,
    resolve_primary_metric_codes,
    resolve_runtime_file_state,
    resolve_sh2o_updates,
    resolve_summary_var_codes,
    resolve_cultivar_path,
    resolve_runtime_root,
    resolve_t_vars,
    resolve_wht_path,
    resolve_adapter_paths,
    rewrite_cultivar_path_row,
)
from dssat_io import load_project_config
import dssat_io
import mgda_update
import observations
import pest_builder
import pest_runner
import result_schema
import run_model


def load_module_from_path(module_name: str, file_path: Path, extra_sys_path: list[Path] | None = None):
    added_paths: list[str] = []
    if extra_sys_path:
        for path in extra_sys_path:
            path_text = str(path)
            if path_text in sys.path:
                continue
            sys.path.insert(0, path_text)
            added_paths.append(path_text)
    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load module from {file_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for path_text in reversed(added_paths):
            if path_text in sys.path:
                sys.path.remove(path_text)


class TestConfigResolution(unittest.TestCase):
    def test_calibration_core_pest_runner_exports_shared_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            project_root = work_dir / "project"
            project_root.mkdir()

            resolved = core_pest_runner.resolve_compare_param_files("standard", work_dir, project_root)

            self.assertEqual(resolved["baseline"], work_dir / "params_baseline.dat")
            self.assertEqual(resolved["pest"], work_dir / "ksas_mvp_est.par")
            self.assertEqual(resolved["mgda"], work_dir / "params_mgda.dat")

    def test_public_api_loads_stable_modules_from_mvp_root(self) -> None:
        module = load_module_from_path("test_public_api_runtime", ROOT / "public_api.py")

        public_api = module.load_public_api()

        self.assertTrue(hasattr(public_api.pest_builder, "run_build_pest_setup_cli"))
        self.assertTrue(hasattr(public_api.pest_runner, "run_compare_model"))
        self.assertTrue(hasattr(public_api.result_schema, "build_evaluation_result"))
        self.assertTrue(hasattr(public_api.dssat_io, "resolve_parameter_names"))

    def test_sandbox_scripts_resolve_public_api_without_src_path_injection(self) -> None:
        sandbox_root = ROOT.parent / "autoresearch_sandbox"
        eval_module = load_module_from_path(
            "test_autoresearch_eval_runtime",
            sandbox_root / "eval.py",
            extra_sys_path=[sandbox_root],
        )
        auto_evolve_module = load_module_from_path(
            "test_autoresearch_auto_evolve_runtime",
            sandbox_root / "auto_evolve.py",
            extra_sys_path=[sandbox_root],
        )

        self.assertEqual(eval_module.PUBLIC_API_PATH, ROOT / "public_api.py")
        self.assertEqual(auto_evolve_module.PUBLIC_API_PATH, ROOT / "public_api.py")
        self.assertEqual(eval_module.SRC_DIR, ROOT / "src")
        self.assertFalse(hasattr(auto_evolve_module, "MVP_SRC_DIR"))
        self.assertTrue(hasattr(eval_module._PUBLIC_API.pest_runner, "run_pestpp_cli"))
        self.assertTrue(hasattr(auto_evolve_module._PUBLIC_API.result_schema, "build_combo_key"))

    def test_sandbox_project_config_resolution_delegates_to_shared_dssat_io(self) -> None:
        sandbox_root = ROOT.parent / "autoresearch_sandbox"
        eval_module = load_module_from_path(
            "test_autoresearch_eval_config_runtime",
            sandbox_root / "eval.py",
            extra_sys_path=[sandbox_root],
        )
        auto_evolve_module = load_module_from_path(
            "test_autoresearch_auto_evolve_config_runtime",
            sandbox_root / "auto_evolve.py",
            extra_sys_path=[sandbox_root],
        )
        calls: list[tuple[Path, str, tuple[str, ...]]] = []

        def fake_resolve_project_config_path(
            project_root: Path,
            *,
            env_var: str = "PROJECT_CONFIG",
            candidate_relatives: tuple[str, ...] = ("config/project.json",),
        ) -> Path | None:
            calls.append((project_root, env_var, candidate_relatives))
            return project_root / "project_wheat.json"

        fake_public_api = SimpleNamespace(
            dssat_io=SimpleNamespace(resolve_project_config_path=fake_resolve_project_config_path)
        )

        with patch.object(eval_module, "load_mvp_public_api", return_value=fake_public_api), patch.object(
            auto_evolve_module, "load_mvp_public_api", return_value=fake_public_api
        ):
            eval_path = eval_module.resolve_sandbox_project_config_path(Path(r"d:\tmp\sandbox"), ROOT / "public_api.py")
            auto_path = auto_evolve_module.resolve_sandbox_project_config_path(Path(r"d:\tmp\sandbox"), ROOT / "public_api.py")

        self.assertEqual(eval_path, ROOT / "project_wheat.json")
        self.assertEqual(auto_path, ROOT / "project_wheat.json")
        self.assertEqual(
            calls,
            [
                (ROOT, "AR_PROJECT_CONFIG", ("config/project.json",)),
                (ROOT, "AR_PROJECT_CONFIG", ("config/project.json",)),
            ],
        )

    def test_sandbox_project_config_resolution_prefers_repo_multicrop_config_for_selected_crop(self) -> None:
        sandbox_root = ROOT.parent / "autoresearch_sandbox"
        eval_module = load_module_from_path(
            "test_autoresearch_eval_multicrop_config_runtime",
            sandbox_root / "eval.py",
            extra_sys_path=[sandbox_root],
        )
        auto_evolve_module = load_module_from_path(
            "test_autoresearch_auto_evolve_multicrop_config_runtime",
            sandbox_root / "auto_evolve.py",
            extra_sys_path=[sandbox_root],
        )
        calls: list[tuple[Path, str, tuple[str, ...], str]] = []

        def fake_resolve_project_config_path(
            project_root: Path,
            *,
            env_var: str = "PROJECT_CONFIG",
            candidate_relatives: tuple[str, ...] = ("config/project.json",),
            crop: object | None = None,
        ) -> Path | None:
            calls.append((project_root, env_var, candidate_relatives, str(crop or "")))
            if project_root == ROOT:
                return project_root / "config" / "multi" / "project_wheat.json"
            return project_root / "project_wheat.json"

        fake_public_api = SimpleNamespace(
            dssat_io=SimpleNamespace(resolve_project_config_path=fake_resolve_project_config_path)
        )

        with patch.dict(os.environ, {"PROJECT_CROP": "wheat"}, clear=False), patch.object(
            eval_module, "load_mvp_public_api", return_value=fake_public_api
        ), patch.object(auto_evolve_module, "load_mvp_public_api", return_value=fake_public_api):
            eval_path = eval_module.resolve_sandbox_project_config_path(Path(r"d:\tmp\sandbox"), ROOT / "public_api.py")
            auto_path = auto_evolve_module.resolve_sandbox_project_config_path(Path(r"d:\tmp\sandbox"), ROOT / "public_api.py")

        self.assertEqual(eval_path, ROOT / "config" / "multi" / "project_wheat.json")
        self.assertEqual(auto_path, ROOT / "config" / "multi" / "project_wheat.json")
        self.assertEqual(
            calls,
            [
                (ROOT, "AR_PROJECT_CONFIG", ("config/project.json",), "wheat"),
                (ROOT, "AR_PROJECT_CONFIG", ("config/project.json",), "wheat"),
            ],
        )

    def test_sandbox_path_builders_keep_project_wheat_fallback_compatibility(self) -> None:
        sandbox_root = ROOT.parent / "autoresearch_sandbox"
        eval_module = load_module_from_path(
            "test_autoresearch_eval_build_paths_runtime",
            sandbox_root / "eval.py",
            extra_sys_path=[sandbox_root],
        )
        auto_evolve_module = load_module_from_path(
            "test_autoresearch_auto_evolve_build_paths_runtime",
            sandbox_root / "auto_evolve.py",
            extra_sys_path=[sandbox_root],
        )

        with tempfile.TemporaryDirectory() as tmp:
            sandbox_dir = Path(tmp)
            legacy_path = sandbox_dir / "project_wheat.json"
            legacy_path.write_text(json.dumps({"crop_family": "wheat"}), encoding="utf-8")

            eval_paths = eval_module.build_eval_paths(sandbox_dir=sandbox_dir, mvp_root=ROOT)
            auto_paths = auto_evolve_module.build_sandbox_paths(sandbox_dir=sandbox_dir, mvp_root=ROOT)

        self.assertEqual(eval_paths.project_config_path, (ROOT / "config" / "multi" / "project_wheat.json").resolve())
        self.assertEqual(auto_paths.project_config_path, (ROOT / "config" / "multi" / "project_wheat.json").resolve())

    def test_resolve_project_config_path_prefers_crop_specific_multi_config(self) -> None:
        resolved = dssat_io.resolve_project_config_path(ROOT, crop="maize")

        self.assertEqual(resolved, (ROOT / "config" / "multi" / "project_maize.json").resolve())

    def test_resolve_project_config_path_supports_five_crops(self) -> None:
        crops = ("wheat", "maize", "rice", "cabbage", "cassava")
        for crop in crops:
            with self.subTest(crop=crop):
                resolved = dssat_io.resolve_project_config_path(ROOT, crop=crop)
            self.assertEqual(resolved, (ROOT / "config" / "multi" / f"project_{crop}.json").resolve())

    def test_sandbox_path_builders_route_runtime_outputs_into_standard_runs_and_artifacts(self) -> None:
        sandbox_root = ROOT.parent / "autoresearch_sandbox"
        eval_module = load_module_from_path(
            "test_autoresearch_eval_paths_runtime_layout",
            sandbox_root / "eval.py",
            extra_sys_path=[sandbox_root],
        )
        sandbox_root = ROOT.parent / "autoresearch_sandbox"
        auto_evolve_module = load_module_from_path(
            "test_autoresearch_auto_evolve_paths_runtime",
            sandbox_root / "auto_evolve.py",
            extra_sys_path=[sandbox_root],
        )

        with tempfile.TemporaryDirectory() as tmp:
            sandbox_dir = Path(tmp)
            (sandbox_dir / "project.json").write_text(json.dumps({"crop_family": "wheat"}), encoding="utf-8")
            eval_paths = eval_module.build_eval_paths(sandbox_dir=sandbox_dir, mvp_root=ROOT)
            paths = auto_evolve_module.build_sandbox_paths(sandbox_dir=sandbox_dir, mvp_root=ROOT)

        self.assertEqual(eval_paths.runs_dir, sandbox_dir / "runs")
        self.assertEqual(eval_paths.runtime_dir, sandbox_dir / "runs" / "runtime")
        self.assertEqual(eval_paths.params_path, sandbox_dir / "runs" / "runtime" / "params.dat")
        self.assertEqual(eval_paths.pest_out_path, sandbox_dir / "runs" / "runtime" / "pest_out.dat")
        self.assertEqual(paths.runs_dir, sandbox_dir / "runs")
        self.assertEqual(paths.runtime_dir, sandbox_dir / "runs" / "runtime")
        self.assertEqual(paths.runtime_params_path, sandbox_dir / "runs" / "runtime" / "params.dat")
        self.assertEqual(paths.runtime_pest_out_path, sandbox_dir / "runs" / "runtime" / "pest_out.dat")
        self.assertEqual(paths.artifacts_dir, sandbox_dir / "artifacts")
        self.assertEqual(paths.parallel_workers_dir, sandbox_dir / "runs" / "parallel_workers")
        self.assertEqual(paths.matrix_log_path, sandbox_dir / "artifacts" / "matrix_experiments.md")
        self.assertEqual(paths.matrix_tsv_path, sandbox_dir / "artifacts" / "matrix_results.tsv")
        self.assertEqual(paths.experiment_summary_tsv_path, sandbox_dir / "artifacts" / "experiment_summary.tsv")
        self.assertEqual(paths.main_matrix_report_md_path, sandbox_dir / "artifacts" / "main_matrix_report.md")

    def test_eval_runtime_migrates_legacy_root_params_and_output_into_runs_runtime(self) -> None:
        sandbox_root = ROOT.parent / "autoresearch_sandbox"
        eval_module = load_module_from_path(
            "test_autoresearch_eval_runtime_migration",
            sandbox_root / "eval.py",
            extra_sys_path=[sandbox_root],
        )

        with tempfile.TemporaryDirectory() as tmp:
            sandbox_dir = Path(tmp)
            runtime_dir = sandbox_dir / "runs" / "runtime"
            legacy_params_path = sandbox_dir / "params.dat"
            legacy_pest_out_path = sandbox_dir / "pest_out.dat"
            params_path = runtime_dir / "params.dat"
            pest_out_path = runtime_dir / "pest_out.dat"
            legacy_params_path.write_text("p1v 12.0\n", encoding="utf-8")
            legacy_pest_out_path.write_text("HWAM 321.0\n", encoding="utf-8")

            with patch.object(eval_module, "SANDBOX_DIR", sandbox_dir), patch.object(
                eval_module, "RUNTIME_DIR", runtime_dir
            ), patch.object(eval_module, "PARAMS_PATH", params_path), patch.object(
                eval_module, "PEST_OUT_PATH", pest_out_path
            ):
                migrated = eval_module.migrate_legacy_runtime_files()

            self.assertEqual(
                migrated,
                {
                    legacy_params_path.resolve(): params_path.resolve(),
                    legacy_pest_out_path.resolve(): pest_out_path.resolve(),
                },
            )
            self.assertFalse(legacy_params_path.exists())
            self.assertFalse(legacy_pest_out_path.exists())
            self.assertEqual(params_path.read_text(encoding="utf-8"), "p1v 12.0\n")
            self.assertEqual(pest_out_path.read_text(encoding="utf-8"), "HWAM 321.0\n")

    def test_public_api_helper_contract_keeps_single_src_entry_and_trims_module_name(self) -> None:
        module = load_module_from_path("test_public_api_helper_runtime", ROOT / "public_api.py")
        src_dir = (ROOT / "src").resolve()

        with patch.object(sys, "path", [str(ROOT)]):
            first = module._ensure_src_dir()
            second = module._ensure_src_dir()
            loaded = module.load_public_module(" pest_runner ")
            src_count = sys.path.count(str(src_dir))

        self.assertEqual(first, src_dir)
        self.assertEqual(second, src_dir)
        self.assertEqual(src_count, 1)
        self.assertEqual(loaded.__name__, "pest_runner")

    def test_prepare_matrix_workspace_copies_eval_script_for_isolated_worker_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_prepare_runtime",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            root = Path(tmp)
            parallel_workers_dir = root / "runs" / "parallel_workers"
            project_config_path = root / "project.json"
            dssat_trts_path = root / "dssat_trts.txt"
            eval_path = root / "eval.py"
            case_src = root / "template_case"
            project_config_path.write_text("{}", encoding="utf-8")
            dssat_trts_path.write_text("1\n2\n", encoding="utf-8")
            eval_path.write_text("print('sandbox eval')\n", encoding="utf-8")
            (case_src / "GENOTYPE").mkdir(parents=True)
            (case_src / "GENOTYPE" / "WHCER048.CUL").write_text("CUL", encoding="utf-8")

            with patch.object(auto_evolve_module, "PARALLEL_WORKERS_DIR", parallel_workers_dir), patch.object(
                auto_evolve_module, "EVAL_PATH", eval_path
            ), patch.object(auto_evolve_module, "PROJECT_CONFIG_PATH", project_config_path), patch.object(
                auto_evolve_module, "DSSAT_TRTS_PATH", dssat_trts_path
            ), patch.object(
                auto_evolve_module, "preferred_case_dir", return_value=case_src
            ), patch.object(auto_evolve_module, "ensure_case_dir_complete", side_effect=lambda path: path):
                workspace = auto_evolve_module.prepare_matrix_workspace(
                    7,
                    "import numpy as np\n\ndef calculate_loss(obs, sim, meta):\n    return 0.0\n",
                )
                self.assertTrue((workspace / "eval.py").exists())
                self.assertTrue((workspace / "project.json").exists())
                self.assertTrue((workspace / "dssat_trts.txt").exists())
                self.assertTrue((workspace / "runs" / "runtime").is_dir())
                self.assertTrue((workspace / "strategy.py").exists())
                self.assertTrue((workspace / "dssat_case" / "GENOTYPE" / "WHCER048.CUL").exists())

    def test_eval_pestpp_helpers_route_setup_and_cleanup_into_runtime_dir(self) -> None:
        sandbox_root = ROOT.parent / "autoresearch_sandbox"
        eval_module = load_module_from_path(
            "test_autoresearch_eval_runtime_workdir",
            sandbox_root / "eval.py",
            extra_sys_path=[sandbox_root],
        )

        with tempfile.TemporaryDirectory() as tmp:
            sandbox_dir = Path(tmp)
            runtime_dir = sandbox_dir / "runs" / "runtime"
            env = {"AR_TEST": "1"}

            with patch.object(eval_module, "RUNTIME_DIR", runtime_dir), patch.object(
                eval_module, "PESTPP_ROOT", sandbox_dir / "pestpp"
            ), patch.object(eval_module, "PARAM_NAMES", ["P1V"]), patch.object(
                eval_module, "clip_params", side_effect=lambda values: values
            ), patch.object(eval_module, "run_pestpp_cli", return_value=object()) as run_pestpp_cli_mock, patch.object(
                eval_module, "runner_cleanup_pestpp_outputs"
            ) as cleanup_mock, patch.object(
                eval_module, "runner_parse_best_glm_result", return_value=(np.array([1.0], dtype=float), 2.0)
            ) as parse_glm_mock, patch.object(
                eval_module, "runner_parse_best_ies_result", return_value=(np.array([1.0], dtype=float), 3.0)
            ) as parse_ies_mock:
                eval_module.run_pestpp_executable("pestpp-ies.exe", env, failure_label="x")
                eval_module.cleanup_pestpp_outputs()
                eval_module.parse_best_glm_result(np.array([0.0], dtype=float))
                eval_module.parse_best_ies_result(np.array([0.0], dtype=float))

            self.assertTrue(runtime_dir.is_dir())
            self.assertEqual(run_pestpp_cli_mock.call_args.kwargs["work_dir"], runtime_dir)
            cleanup_mock.assert_called_once_with(runtime_dir, stem="ksas_mvp")
            self.assertEqual(parse_glm_mock.call_args.args[0], runtime_dir)
            self.assertEqual(parse_ies_mock.call_args.args[0], runtime_dir)

    def test_execute_matrix_job_parallel_uses_root_eval_and_workspace_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_execute_runtime",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            workspace = Path(tmp) / "job_001"
            (workspace / "dssat_case").mkdir(parents=True)
            call_args: dict[str, object] = {}
            weight = auto_evolve_module.WeightCandidate(
                "W_TEST",
                "test",
                "w_test_mode",
                "import numpy as np\n\ndef calculate_loss(obs, sim, meta):\n    return 0.0\n",
            )
            job = auto_evolve_module.MatrixJob(
                index=1,
                weight=weight,
                engine="pest_glm",
                budget="quick",
                sequence="s_test",
                grouping="g_test",
            )

            def fake_run_eval_in_workspace(eval_path: Path, actual_workspace: Path, env_overrides=None):
                call_args["eval_path"] = eval_path
                call_args["workspace"] = actual_workspace
                call_args["env_overrides"] = dict(env_overrides or {})
                return "TRAIN_MEAN_NRMSE=0.1", 0.25

            def fake_build_matrix_result(**kwargs):
                return auto_evolve_module.MatrixResult(
                    run_id=str(kwargs["run_id"]),
                    weight_name=kwargs["weight"].name,
                    engine=str(kwargs["engine"]),
                    budget=str(kwargs["budget"]),
                    sequence=str(kwargs["sequence"]),
                    grouping=str(kwargs["grouping"]),
                    score=float(kwargs["score"]),
                    status=str(kwargs["status"]),
                    weight_mode=kwargs["weight"].weight_mode,
                    stdout=str(kwargs["stdout"]),
                    negative_ref_profile=str(kwargs["negative_ref_profile"]),
                    negative_ref_score=float(kwargs["negative_ref_score"]),
                    train_mean_nrmse=0.1,
                    valid_mean_nrmse=0.2,
                    all_mean_nrmse=0.15,
                    yield_metric=str(kwargs["yield_metric"]),
                    train_yield_nrmse=0.3,
                    train_yield_bias=0.0,
                    valid_yield_nrmse=0.4,
                    valid_yield_bias=0.0,
                )

            with patch.object(auto_evolve_module, "validate_matrix_combination", return_value=None), patch.object(
                auto_evolve_module, "validate_strategy_source", return_value=None
            ), patch.object(auto_evolve_module, "prepare_matrix_workspace", return_value=workspace), patch.object(
                auto_evolve_module, "run_eval_in_workspace", side_effect=fake_run_eval_in_workspace
            ), patch.object(auto_evolve_module, "build_matrix_result", side_effect=fake_build_matrix_result), patch.object(
                auto_evolve_module, "project_observation_bundle", return_value=([1], {1: "train"}, None)
            ), patch.object(auto_evolve_module, "parse_final_parameters", return_value={}), patch.object(
                auto_evolve_module, "build_treatment_metric_rows", return_value=[]
            ), patch.object(auto_evolve_module, "build_aggregate_metric_rows", return_value=[]), patch.object(
                auto_evolve_module, "sha1_of_file", return_value="hash"
            ):
                result = auto_evolve_module.execute_matrix_job(
                    job=job,
                    plan="phase-test",
                    negative_ref_profile="baseline",
                    negative_ref_score=0.5,
                    yield_metric="hwam",
                    original_strategy=weight.source or "",
                    max_workers=2,
                )

        env_overrides = call_args["env_overrides"]
        self.assertEqual(call_args["eval_path"], auto_evolve_module.EVAL_PATH)
        self.assertEqual(call_args["workspace"], workspace)
        self.assertEqual(env_overrides["AR_SANDBOX_DIR"], str(workspace.resolve()))
        self.assertEqual(env_overrides["DSSAT_CASE_DIR"], str((workspace / "dssat_case").resolve()))
        self.assertEqual(result.workspace_dir, str(workspace.resolve()))
        self.assertEqual(result.eval_hash, "hash")

    def test_rebuild_experiment_protocol_artifacts_index_collects_runtime_protocol_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_protocol_index_runtime",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            root = Path(tmp)
            workspace = root / "sandbox"
            runtime_dir = workspace / "runs" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir = root / "artifacts"
            experiment_runs_path = artifacts_dir / "experiment_runs.tsv"
            protocol_index_path = artifacts_dir / "experiment_protocol_artifacts.tsv"
            (runtime_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-001",
                        "crop": "wheat",
                        "scenario": {"filex_name": "SWSW7501.WHX", "trts": [1, 2]},
                        "protocol": {
                            "weight": "W8_DSSAT_PEST_Group_Max",
                            "engine": "o1_least_squares",
                            "budget": "quick",
                            "sequence": "s2_sequential_phase",
                            "grouping": "g3_dssat_extended",
                            "weight_mode": "w8_dssat_group_max",
                        },
                        "observations": {
                            "requested_summary_metrics": ["HWAM", "LAIX"],
                            "requested_t_vars": ["LAID", "SWAD"],
                        },
                        "resolved_output": {
                            "summary_metrics": ["HWAM"],
                            "t_vars": ["LAID"],
                            "active_groups": ["obs_yield"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (runtime_dir / "contract_report.json").write_text(
                json.dumps(
                    {
                        "status": "degraded",
                        "resolved": {
                            "active_groups": ["obs_yield"],
                            "summary_metrics": ["HWAM"],
                            "t_vars": ["LAID"],
                        },
                        "requested": {
                            "summary_metrics": ["HWAM", "LAIX"],
                            "t_vars": ["LAID", "SWAD"],
                        },
                        "summary": {
                            "active_metric_count": 1,
                            "active_observation_count": 12,
                            "dropped_group_count": 1,
                            "weight_fallback_count": 1,
                            "zero_weight_observation_count": 2,
                            "fallback_metrics": ["LAIX"],
                        },
                        "dropped_groups": [{"group": "obs_canopy", "reason": "no_train_observations"}],
                        "weight_fallbacks": [
                            {"group": "obs_yield", "reason": "variance_unavailable_used_sigma"}
                        ],
                        "zero_weight_observations": [
                            {"obs_name": "laix_t02", "reason": "validation_split"},
                            {"obs_name": "swad_t02", "reason": "inactive_metric"},
                        ],
                        "issues": [
                            {"severity": "warning", "code": "missing_summary_metrics"},
                            {"severity": "error", "code": "missing_required_file"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.multiple(
                auto_evolve_module,
                EXPERIMENT_RUNS_TSV_PATH=experiment_runs_path,
                EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH=protocol_index_path,
            ):
                auto_evolve_module.append_experiment_runs_tsv(
                    auto_evolve_module.MatrixResult(
                        run_id="run-001",
                        weight_name="W8_DSSAT_PEST_Group_Max",
                        engine="o1_least_squares",
                        budget="quick",
                        sequence="s2_sequential_phase",
                        grouping="g3_dssat_extended",
                        score=0.25,
                        status="ok",
                        weight_mode="w8_dssat_group_max",
                        stdout="",
                        negative_ref_profile="baseline",
                        negative_ref_score=0.4,
                        train_mean_nrmse=0.2,
                        valid_mean_nrmse=0.3,
                        all_mean_nrmse=0.25,
                        yield_metric="HWAM",
                        train_yield_nrmse=0.22,
                        train_yield_bias=0.01,
                        valid_yield_nrmse=0.33,
                        valid_yield_bias=0.02,
                        plan="phasePaper",
                        executed_at="2026-04-01T10:00:00",
                        workspace_dir=str(workspace),
                    )
                )
                auto_evolve_module.rebuild_experiment_protocol_artifacts_index()

            rows = auto_evolve_module.read_tsv_rows(protocol_index_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], "run-001")
        self.assertEqual(rows[0]["crop"], "wheat")
        self.assertEqual(rows[0]["filex_name"], "SWSW7501.WHX")
        self.assertEqual(rows[0]["trts"], "1,2")
        self.assertEqual(rows[0]["contract_status"], "degraded")
        self.assertEqual(rows[0]["issue_count"], "2")
        self.assertEqual(rows[0]["warning_count"], "1")
        self.assertEqual(rows[0]["error_count"], "1")
        self.assertEqual(rows[0]["issue_codes"], "missing_summary_metrics,missing_required_file")
        self.assertEqual(rows[0]["fallback_metrics"], "LAIX")
        self.assertEqual(rows[0]["dropped_groups"], "obs_canopy:no_train_observations")
        self.assertEqual(rows[0]["weight_fallbacks"], "obs_yield:variance_unavailable_used_sigma")
        self.assertEqual(
            rows[0]["zero_weight_observations"],
            "laix_t02:validation_split,swad_t02:inactive_metric",
        )
        self.assertEqual(rows[0]["requested_summary_metrics"], "HWAM,LAIX")
        self.assertEqual(rows[0]["resolved_t_vars"], "LAID")
        self.assertEqual(rows[0]["dropped_group_count"], "1")
        self.assertEqual(rows[0]["weight_fallback_count"], "1")
        self.assertEqual(rows[0]["zero_weight_observation_count"], "2")
        self.assertTrue(rows[0]["run_manifest_path"].endswith("run_manifest.json"))

    def test_build_main_matrix_report_generates_filtered_leaderboard_and_dimension_rollups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_report_runtime",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            root = Path(tmp)
            artifacts_dir = root / "artifacts"
            summary_path = artifacts_dir / "experiment_summary.tsv"
            leaderboard_path = artifacts_dir / "main_matrix_leaderboard.tsv"
            dimension_path = artifacts_dir / "main_matrix_dimension_summary.tsv"
            baseline_summary_path = artifacts_dir / "main_matrix_baseline_summary.tsv"
            baseline_detail_path = artifacts_dir / "main_matrix_baseline_detail.tsv"
            key_indicator_table_path = artifacts_dir / "main_matrix_key_indicator_table.tsv"
            baseline_winners_path = artifacts_dir / "main_matrix_baseline_winners.tsv"
            metric_snapshot_path = artifacts_dir / "main_matrix_metric_snapshot.tsv"
            paper_summary_path = artifacts_dir / "main_matrix_paper_summary.tsv"
            protocol_source_path = artifacts_dir / "experiment_protocol_artifacts.tsv"
            protocol_overview_path = artifacts_dir / "main_matrix_protocol_overview.tsv"
            protocol_dimension_summary_path = artifacts_dir / "main_matrix_protocol_dimension_summary.tsv"
            protocol_nested_dimension_summary_path = (
                artifacts_dir / "main_matrix_protocol_nested_dimension_summary.tsv"
            )
            protocol_hotspot_summary_path = artifacts_dir / "main_matrix_protocol_hotspot_summary.tsv"
            protocol_reason_summary_path = artifacts_dir / "main_matrix_protocol_reason_summary.tsv"
            appendix_index_path = artifacts_dir / "main_matrix_appendix_index.tsv"
            protocol_paper_table_path = artifacts_dir / "main_matrix_protocol_paper_table.tsv"
            paper_main_table_path = artifacts_dir / "main_matrix_paper_main_table.tsv"
            paper_appendix_table_path = artifacts_dir / "main_matrix_paper_appendix_table.tsv"
            paper_table_path = artifacts_dir / "main_matrix_paper_table.tsv"
            topk_overall_path = artifacts_dir / "main_matrix_topk_overall.tsv"
            topk_by_engine_path = artifacts_dir / "main_matrix_topk_by_engine.tsv"
            topk_by_weight_path = artifacts_dir / "main_matrix_topk_by_weight.tsv"
            topk_by_sequence_path = artifacts_dir / "main_matrix_topk_by_sequence.tsv"
            topk_by_grouping_path = artifacts_dir / "main_matrix_topk_by_grouping.tsv"
            topk_validation_only_path = artifacts_dir / "main_matrix_topk_validation_only.tsv"
            topk_by_budget_path = artifacts_dir / "main_matrix_topk_by_budget.tsv"
            topk_by_validation_budget_path = artifacts_dir / "main_matrix_topk_by_validation_budget.tsv"
            topk_improvement_path = artifacts_dir / "main_matrix_topk_improvement.tsv"
            quality_gate_path = artifacts_dir / "main_matrix_quality_gate.tsv"
            report_path = artifacts_dir / "main_matrix_report.md"

            def summary_row(**overrides: str) -> dict[str, str]:
                row = {field: "" for field in auto_evolve_module.SUMMARY_EXPORT_FIELDNAMES}
                row.update(
                    {
                        "combo_key": "W0|o1|quick|s1|g1",
                        "run_id": "run_default",
                        "score_rank": "99",
                        "executed_at": "2026-03-28T10:00:00",
                        "plan": "phaseA",
                        "weight": "W0",
                        "engine": "o1",
                        "budget": "quick",
                        "sequence": "s1",
                        "grouping": "g1",
                        "status": "ok",
                        "validation_enabled": "false",
                        "score": "0.300000",
                        "delta_vs_b0": "-0.020000",
                        "delta_vs_b1": "-0.010000",
                        "delta_vs_negative_ref": "-0.030000",
                        "better_than_b0": "true",
                        "better_than_b1": "true",
                        "better_than_negative_ref": "true",
                        "yield_metric": "HWAM",
                        "train_mean_nrmse": "0.300000",
                        "valid_mean_nrmse": "0.310000",
                        "all_mean_nrmse": "0.305000",
                        "train_yield_nrmse": "0.180000",
                        "valid_yield_nrmse": "0.190000",
                        "duration_sec": "12.500000",
                        "workspace_dir": str(root / "job_default"),
                    }
                )
                row.update(overrides)
                return row

            auto_evolve_module.write_tsv_dict_rows(
                summary_path,
                auto_evolve_module.SUMMARY_EXPORT_FIELDNAMES,
                [
                    summary_row(
                        combo_key="W0|o1|quick|s1|g1",
                        run_id="run_a",
                        score_rank="2",
                        weight="W0",
                        engine="o1",
                        sequence="s1",
                        grouping="g1",
                        score="0.310000",
                        validation_enabled="false",
                    ),
                    summary_row(
                        combo_key="W1|o2|quick|s2|g2",
                        run_id="run_b",
                        score_rank="1",
                        weight="W1",
                        engine="o2",
                        sequence="s2",
                        grouping="g2",
                        score="0.250000",
                        executed_at="2026-03-28T10:05:00",
                        train_mean_nrmse="0.250000",
                        valid_mean_nrmse="0.260000",
                        validation_enabled="true",
                        workspace_dir=str(root / "job_b"),
                    ),
                    summary_row(
                        combo_key="W2|o1|quick|s2|g3",
                        run_id="run_d",
                        score_rank="4",
                        weight="W2",
                        engine="o1",
                        sequence="s2",
                        grouping="g3",
                        score="0.290000",
                        delta_vs_b0="-0.015000",
                        executed_at="2026-03-28T10:08:00",
                        train_mean_nrmse="0.280000",
                        valid_mean_nrmse="0.295000",
                        validation_enabled="true",
                        workspace_dir=str(root / "job_d"),
                    ),
                    summary_row(
                        combo_key="W9|o3|quick|s3|g3",
                        run_id="run_c",
                        score_rank="3",
                        plan="phaseB",
                        weight="W9",
                        engine="o3",
                        sequence="s3",
                        grouping="g3",
                        status="failed",
                        score="0.800000",
                        better_than_b0="false",
                        better_than_b1="false",
                        better_than_negative_ref="false",
                    ),
                ],
            )
            auto_evolve_module.write_tsv_dict_rows(
                protocol_source_path,
                auto_evolve_module.EXPERIMENT_PROTOCOL_ARTIFACTS_FIELDNAMES,
                [
                    {
                        field: value
                        for field, value in {
                            "run_id": "run_b",
                            "contract_status": "ok",
                            "issue_count": "0",
                            "warning_count": "0",
                            "error_count": "0",
                            "active_metric_count": "2",
                            "active_observation_count": "14",
                            "dropped_group_count": "1",
                            "weight_fallback_count": "2",
                            "zero_weight_observation_count": "3",
                            "dropped_groups": "obs_biomass:no_train_observations",
                            "weight_fallbacks": "obs_yield:variance_unavailable_used_sigma,obs_lai:variance_unavailable_used_sigma",
                            "zero_weight_observations": "HWAM_TRNO_1:filtered,LAIX_TRNO_2:inactive,SWAD_TRNO_3:split_excluded",
                            "requested_summary_metrics": "HWAM,LAIX",
                            "resolved_summary_metrics": "HWAM,LAIX",
                            "requested_t_vars": "LAID,SWAD",
                            "resolved_t_vars": "LAID,SWAD",
                            "protocol_weight": "W1",
                            "protocol_engine": "o2",
                            "protocol_budget": "quick",
                            "protocol_sequence": "s2",
                            "protocol_grouping": "g2",
                            "filex_name": "SWSW7501.WHX",
                            "crop": "wheat",
                            "run_manifest_path": str((root / "job_b" / "runs" / "runtime" / "run_manifest.json").resolve()),
                            "contract_report_path": str((root / "job_b" / "runs" / "runtime" / "contract_report.json").resolve()),
                        }.items()
                    },
                    {
                        field: value
                        for field, value in {
                            "run_id": "run_d",
                            "contract_status": "degraded",
                            "issue_count": "2",
                            "warning_count": "1",
                            "error_count": "1",
                            "active_metric_count": "1",
                            "active_observation_count": "10",
                            "dropped_group_count": "2",
                            "weight_fallback_count": "1",
                            "zero_weight_observation_count": "4",
                            "dropped_groups": "obs_laid:no_observations,obs_stage:inactive",
                            "weight_fallbacks": "obs_hwam:max_zero_used_sigma",
                            "zero_weight_observations": "LAID_TRNO_1:inactive,SWAD_TRNO_2:inactive,HWAM_TRNO_2:split_excluded,CWAD_TRNO_2:split_excluded",
                            "requested_summary_metrics": "HWAM,LAIX",
                            "resolved_summary_metrics": "HWAM",
                            "requested_t_vars": "LAID,SWAD",
                            "resolved_t_vars": "LAID",
                            "protocol_weight": "W2",
                            "protocol_engine": "o1",
                            "protocol_budget": "quick",
                            "protocol_sequence": "s2",
                            "protocol_grouping": "g3",
                            "filex_name": "SWSW7501.WHX",
                            "crop": "wheat",
                            "run_manifest_path": str((root / "job_d" / "runs" / "runtime" / "run_manifest.json").resolve()),
                            "contract_report_path": str((root / "job_d" / "runs" / "runtime" / "contract_report.json").resolve()),
                        }.items()
                    },
                ],
            )

            with patch.multiple(
                auto_evolve_module,
                EXPERIMENT_SUMMARY_TSV_PATH=summary_path,
                EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH=protocol_source_path,
                MAIN_MATRIX_LEADERBOARD_TSV_PATH=leaderboard_path,
                MAIN_MATRIX_DIMENSION_SUMMARY_TSV_PATH=dimension_path,
                MAIN_MATRIX_BASELINE_SUMMARY_TSV_PATH=baseline_summary_path,
                MAIN_MATRIX_BASELINE_DETAIL_TSV_PATH=baseline_detail_path,
                MAIN_MATRIX_KEY_INDICATOR_TABLE_TSV_PATH=key_indicator_table_path,
                MAIN_MATRIX_BASELINE_WINNERS_TSV_PATH=baseline_winners_path,
                MAIN_MATRIX_METRIC_SNAPSHOT_TSV_PATH=metric_snapshot_path,
                MAIN_MATRIX_PAPER_SUMMARY_TSV_PATH=paper_summary_path,
                MAIN_MATRIX_PROTOCOL_OVERVIEW_TSV_PATH=protocol_overview_path,
                MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_TSV_PATH=protocol_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_TSV_PATH=protocol_nested_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_TSV_PATH=protocol_hotspot_summary_path,
                MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH=protocol_reason_summary_path,
                MAIN_MATRIX_QUALITY_GATE_TSV_PATH=quality_gate_path,
                MAIN_MATRIX_APPENDIX_INDEX_TSV_PATH=appendix_index_path,
                MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH=protocol_paper_table_path,
                MAIN_MATRIX_PAPER_MAIN_TABLE_TSV_PATH=paper_main_table_path,
                MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH=paper_appendix_table_path,
                MAIN_MATRIX_PAPER_TABLE_TSV_PATH=paper_table_path,
                MAIN_MATRIX_TOPK_OVERALL_TSV_PATH=topk_overall_path,
                MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH=topk_by_engine_path,
                MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH=topk_by_weight_path,
                MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH=topk_by_sequence_path,
                MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH=topk_by_grouping_path,
                MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH=topk_validation_only_path,
                MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH=topk_by_budget_path,
                MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH=topk_by_validation_budget_path,
                MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH=topk_improvement_path,
                MAIN_MATRIX_REPORT_MD_PATH=report_path,
            ):
                outputs = auto_evolve_module.build_main_matrix_report(
                    report_plan="phaseA",
                    top_n=2,
                    paper_require_better_than="b0",
                    paper_max_rows=2,
                    top_k_per_panel=1,
                )

            leaderboard_rows = auto_evolve_module.read_tsv_rows(leaderboard_path)
            dimension_rows = auto_evolve_module.read_tsv_rows(dimension_path)
            baseline_summary_rows = auto_evolve_module.read_tsv_rows(baseline_summary_path)
            baseline_detail_rows = auto_evolve_module.read_tsv_rows(baseline_detail_path)
            key_indicator_rows = auto_evolve_module.read_tsv_rows(key_indicator_table_path)
            baseline_winner_rows = auto_evolve_module.read_tsv_rows(baseline_winners_path)
            metric_snapshot_rows = auto_evolve_module.read_tsv_rows(metric_snapshot_path)
            paper_summary_rows = auto_evolve_module.read_tsv_rows(paper_summary_path)
            protocol_overview_rows = auto_evolve_module.read_tsv_rows(protocol_overview_path)
            protocol_dimension_rows = auto_evolve_module.read_tsv_rows(protocol_dimension_summary_path)
            protocol_nested_dimension_rows = auto_evolve_module.read_tsv_rows(protocol_nested_dimension_summary_path)
            protocol_hotspot_rows = auto_evolve_module.read_tsv_rows(protocol_hotspot_summary_path)
            protocol_reason_rows = auto_evolve_module.read_tsv_rows(protocol_reason_summary_path)
            quality_gate_rows = auto_evolve_module.read_tsv_rows(quality_gate_path)
            appendix_index_rows = auto_evolve_module.read_tsv_rows(appendix_index_path)
            protocol_panel_rows = auto_evolve_module.read_tsv_rows(protocol_paper_table_path)
            paper_main_rows = auto_evolve_module.read_tsv_rows(paper_main_table_path)
            paper_appendix_rows = auto_evolve_module.read_tsv_rows(paper_appendix_table_path)
            paper_rows = auto_evolve_module.read_tsv_rows(paper_table_path)
            topk_overall_rows = auto_evolve_module.read_tsv_rows(topk_overall_path)
            topk_by_engine_rows = auto_evolve_module.read_tsv_rows(topk_by_engine_path)
            topk_by_weight_rows = auto_evolve_module.read_tsv_rows(topk_by_weight_path)
            topk_by_sequence_rows = auto_evolve_module.read_tsv_rows(topk_by_sequence_path)
            topk_by_grouping_rows = auto_evolve_module.read_tsv_rows(topk_by_grouping_path)
            topk_validation_only_rows = auto_evolve_module.read_tsv_rows(topk_validation_only_path)
            topk_by_budget_rows = auto_evolve_module.read_tsv_rows(topk_by_budget_path)
            topk_by_validation_budget_rows = auto_evolve_module.read_tsv_rows(topk_by_validation_budget_path)
            topk_improvement_rows = auto_evolve_module.read_tsv_rows(topk_improvement_path)
            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual(outputs["leaderboard"], leaderboard_path)
        self.assertEqual(outputs["baseline_summary"], baseline_summary_path)
        self.assertEqual(outputs["baseline_detail"], baseline_detail_path)
        self.assertEqual(outputs["key_indicator_table"], key_indicator_table_path)
        self.assertEqual(outputs["baseline_winners"], baseline_winners_path)
        self.assertEqual(outputs["metric_snapshot"], metric_snapshot_path)
        self.assertEqual(outputs["paper_summary"], paper_summary_path)
        self.assertEqual(outputs["protocol_overview"], protocol_overview_path)
        self.assertEqual(outputs["protocol_dimension_summary"], protocol_dimension_summary_path)
        self.assertEqual(outputs["protocol_nested_dimension_summary"], protocol_nested_dimension_summary_path)
        self.assertEqual(outputs["protocol_hotspot_summary"], protocol_hotspot_summary_path)
        self.assertEqual(outputs["protocol_reason_summary"], protocol_reason_summary_path)
        self.assertEqual(outputs["quality_gate"], quality_gate_path)
        self.assertEqual(outputs["appendix_index"], appendix_index_path)
        self.assertEqual(outputs["protocol_paper_table"], protocol_paper_table_path)
        self.assertEqual(outputs["paper_main_table"], paper_main_table_path)
        self.assertEqual(outputs["paper_appendix_table"], paper_appendix_table_path)
        self.assertEqual(outputs["paper_table"], paper_table_path)
        self.assertEqual(outputs["topk_by_validation_budget"], topk_by_validation_budget_path)
        self.assertEqual(
            tuple(outputs),
            auto_evolve_module.MAIN_MATRIX_REPORT_OUTPUT_KEYS,
        )
        self.assertEqual([row["run_id"] for row in leaderboard_rows], ["run_b", "run_d", "run_a"])
        self.assertEqual({row["plan"] for row in leaderboard_rows}, {"phaseA"})
        self.assertTrue(any(row["dimension"] == "weight" and row["value"] == "W1" for row in dimension_rows))
        self.assertTrue(any(row["reason_kind"] == "dropped_group" for row in protocol_reason_rows))
        self.assertEqual([row["comparison_target"] for row in baseline_summary_rows], ["b0", "b1", "negative_ref"])
        self.assertEqual(baseline_summary_rows[0]["better_count"], "3")
        self.assertEqual(baseline_summary_rows[0]["best_run_id"], "run_b")
        self.assertEqual(
            [row["comparison_target"] for row in baseline_detail_rows[:3]],
            ["b0", "b0", "b0"],
        )
        self.assertEqual(baseline_detail_rows[0]["comparison_rank"], "1")
        self.assertEqual(baseline_detail_rows[0]["run_id"], "run_b")
        self.assertEqual(baseline_detail_rows[0]["comparison_delta"], "-0.020000")
        self.assertEqual(baseline_detail_rows[0]["comparison_passed"], "true")
        self.assertEqual(
            [row["indicator_key"] for row in key_indicator_rows],
            ["score", "valid_mean_nrmse", "comparison_delta", "train_mean_nrmse", "all_mean_nrmse"],
        )
        self.assertEqual(key_indicator_rows[0]["best_run_id"], "run_b")
        self.assertEqual(key_indicator_rows[2]["best_value"], "-0.020000")
        self.assertEqual([row["comparison_target"] for row in baseline_winner_rows], ["b0", "b1", "negative_ref"])
        self.assertEqual([row["winner_run_id"] for row in baseline_winner_rows], ["run_b", "run_b", "run_b"])
        self.assertTrue(
            any(
                row["scope"] == "paper_selected"
                and row["metric_key"] == "valid_mean_nrmse"
                and row["best_run_id"] == "run_b"
                for row in metric_snapshot_rows
            )
        )
        self.assertTrue(
            any(
                row["scope"] == "leaderboard_all"
                and row["metric_key"] == "delta_vs_negative_ref"
                and row["best_value"] == "-0.030000"
                for row in metric_snapshot_rows
            )
        )
        self.assertEqual([row["selection_scope"] for row in paper_summary_rows], ["paper_selected"])
        self.assertEqual(paper_summary_rows[0]["comparison_target"], "b0")
        self.assertEqual(paper_summary_rows[0]["best_combo_key"], "W1|o2|quick|s2|g2")
        self.assertEqual(paper_summary_rows[0]["better_than_target_rate"], "1.000000")
        self.assertEqual([row["selection_scope"] for row in protocol_overview_rows], ["leaderboard_all", "paper_selected"])
        self.assertEqual(protocol_overview_rows[0]["degraded_contract_runs"], "1")
        self.assertEqual(protocol_overview_rows[0]["ok_contract_runs"], "1")
        self.assertEqual(protocol_overview_rows[0]["missing_contract_runs"], "1")
        self.assertEqual(protocol_overview_rows[0]["rows_with_dropped_groups"], "2")
        self.assertEqual(protocol_overview_rows[0]["rows_with_weight_fallbacks"], "2")
        self.assertEqual(protocol_overview_rows[0]["rows_with_zero_weight_observations"], "2")
        self.assertEqual(protocol_overview_rows[0]["total_dropped_group_count"], "3")
        self.assertEqual(protocol_overview_rows[0]["total_weight_fallback_count"], "3")
        self.assertEqual(protocol_overview_rows[0]["total_zero_weight_observation_count"], "7")
        self.assertEqual(protocol_overview_rows[0]["dropped_group_run_rate"], "0.666667")
        self.assertEqual(protocol_overview_rows[1]["ok_contract_runs"], "1")
        self.assertEqual(protocol_overview_rows[1]["degraded_contract_runs"], "0")
        self.assertEqual(protocol_overview_rows[1]["missing_contract_runs"], "0")
        self.assertEqual(protocol_overview_rows[1]["rows_with_dropped_groups"], "1")
        self.assertEqual(protocol_overview_rows[1]["rows_with_weight_fallbacks"], "1")
        self.assertEqual(protocol_overview_rows[1]["rows_with_zero_weight_observations"], "1")
        self.assertEqual(protocol_overview_rows[1]["total_dropped_group_count"], "1")
        self.assertEqual(protocol_overview_rows[1]["total_weight_fallback_count"], "2")
        self.assertEqual(protocol_overview_rows[1]["total_zero_weight_observation_count"], "3")
        self.assertEqual(protocol_overview_rows[1]["dropped_group_run_rate"], "1.000000")
        self.assertEqual(protocol_overview_rows[1]["mean_active_metric_count"], "2.000000")
        self.assertTrue(
            any(
                row["selection_scope"] == "leaderboard_all"
                and row["dimension"] == "weight"
                and row["value"] == "W1"
                and row["ok_contract_runs"] == "1"
                and row["total_weight_fallback_count"] == "2"
                for row in protocol_dimension_rows
            )
        )
        self.assertTrue(
            any(
                row["selection_scope"] == "leaderboard_all"
                and row["dimension"] == "grouping"
                and row["value"] == "g3"
                and row["degraded_contract_runs"] == "1"
                and row["total_zero_weight_observation_count"] == "4"
                for row in protocol_dimension_rows
            )
        )
        self.assertTrue(
            any(
                row["selection_scope"] == "paper_selected"
                and row["dimension"] == "sequence"
                and row["value"] == "s2"
                and row["total_dropped_group_count"] == "1"
                for row in protocol_dimension_rows
            )
        )
        self.assertTrue(
            any(
                row["selection_scope"] == "leaderboard_all"
                and row["dimensions"] == "weight|engine"
                and row["values"] == "W1|o2"
                and row["ok_contract_runs"] == "1"
                and row["total_weight_fallback_count"] == "2"
                for row in protocol_nested_dimension_rows
            )
        )
        self.assertTrue(
            any(
                row["selection_scope"] == "leaderboard_all"
                and row["dimensions"] == "weight|engine|sequence|grouping"
                and row["values"] == "W2|o1|s2|g3"
                and row["degraded_contract_runs"] == "1"
                and row["total_zero_weight_observation_count"] == "4"
                for row in protocol_nested_dimension_rows
            )
        )
        self.assertTrue(
            any(
                row["selection_scope"] == "paper_selected"
                and row["dimensions"] == "weight|sequence"
                and row["values"] == "W1|s2"
                and row["total_dropped_group_count"] == "1"
                for row in protocol_nested_dimension_rows
            )
        )
        self.assertEqual(len(protocol_hotspot_rows), 8)
        self.assertEqual(protocol_hotspot_rows[0]["source"], "dimension")
        self.assertEqual(protocol_hotspot_rows[0]["slice_label"], "engine=o1")
        self.assertEqual(protocol_hotspot_rows[0]["missing_contract_runs"], "1")
        self.assertEqual(protocol_hotspot_rows[0]["degraded_contract_runs"], "1")
        self.assertEqual(protocol_hotspot_rows[0]["total_zero_weight_observation_count"], "4")
        self.assertTrue(
            any(
                row["source"] == "nested_d2"
                and row["slice_label"] == "weight|engine=W0|o1"
                and row["missing_contract_runs"] == "1"
                for row in protocol_hotspot_rows
            )
        )
        self.assertEqual(
            [row["gate_key"] for row in quality_gate_rows],
            [
                "paper_main_table_schema",
                "paper_appendix_table_schema",
                "protocol_paper_table_schema",
                "report_output_contract",
                "appendix_panel_contract",
                "leaderboard_rows_present",
                "paper_rows_present",
                "paper_protocol_contract",
                "leaderboard_protocol_coverage",
            ],
        )
        self.assertEqual(quality_gate_rows[0]["status"], "pass")
        self.assertEqual(quality_gate_rows[7]["status"], "pass")
        self.assertEqual(quality_gate_rows[8]["status"], "fail")
        self.assertEqual(len(appendix_index_rows), 11)
        self.assertEqual([row["run_id"] for row in protocol_panel_rows], ["run_b"])
        self.assertEqual([row["contract_status"] for row in protocol_panel_rows], ["ok"])
        self.assertEqual(protocol_panel_rows[0]["dropped_group_count"], "1")
        self.assertEqual(protocol_panel_rows[0]["weight_fallback_count"], "2")
        self.assertEqual(protocol_panel_rows[0]["zero_weight_observation_count"], "3")
        self.assertEqual(
            tuple(auto_evolve_module.MAIN_MATRIX_PAPER_MAIN_TABLE_FIELDNAMES),
            auto_evolve_module.MAIN_MATRIX_FROZEN_PAPER_MAIN_TABLE_FIELDNAMES,
        )
        self.assertEqual(
            tuple(auto_evolve_module.MAIN_MATRIX_PAPER_TABLE_FIELDNAMES),
            auto_evolve_module.MAIN_MATRIX_FROZEN_PAPER_TABLE_FIELDNAMES,
        )
        self.assertEqual(
            tuple(auto_evolve_module.MAIN_MATRIX_PROTOCOL_PANEL_FIELDNAMES),
            auto_evolve_module.MAIN_MATRIX_FROZEN_PROTOCOL_PAPER_TABLE_FIELDNAMES,
        )
        self.assertEqual(
            [row["combo_key"] for row in paper_main_rows],
            ["W1|o2|quick|s2|g2"],
        )
        self.assertEqual(
            set(paper_main_rows[0]),
            set(auto_evolve_module.MAIN_MATRIX_PAPER_MAIN_TABLE_FIELDNAMES),
        )
        self.assertEqual([row["run_id"] for row in paper_appendix_rows], ["run_b"])
        self.assertTrue(
            any(
                row["panel_key"] == "topk_by_sequence"
                and row["grouping_field"] == "sequence"
                and row["panel_values"] == "s2"
                for row in appendix_index_rows
            )
        )
        self.assertTrue(
            any(
                row["panel_key"] == "topk_validation_only"
                and row["selection_scope"] == "validation_selected"
                and row["panel_values"] == "all"
                for row in appendix_index_rows
            )
        )
        self.assertTrue(
            any(
                row["panel_key"] == "paper_appendix_table"
                and row["grouping_field"] == "paper_rank"
                and row["row_count"] == "1"
                for row in appendix_index_rows
            )
        )
        self.assertTrue(
            any(
                row["panel_key"] == "protocol_paper_table"
                and row["grouping_field"] == "contract_status"
                and row["panel_values"] == "ok"
                for row in appendix_index_rows
            )
        )
        self.assertEqual(
            [row["panel_key"] for row in appendix_index_rows],
            [spec[0] for spec in auto_evolve_module.MAIN_MATRIX_APPENDIX_PANEL_SPECS],
        )
        self.assertEqual([row["run_id"] for row in paper_rows], ["run_b"])
        self.assertEqual([row["comparison_target"] for row in paper_rows], ["b0"])
        self.assertEqual([row["run_id"] for row in topk_overall_rows], ["run_b"])
        self.assertEqual({row["panel_value"] for row in topk_by_engine_rows}, {"o2"})
        self.assertEqual({row["panel_value"] for row in topk_by_weight_rows}, {"W1"})
        self.assertEqual({row["panel_value"] for row in topk_by_sequence_rows}, {"s2"})
        self.assertEqual({row["panel_value"] for row in topk_by_grouping_rows}, {"g2"})
        self.assertEqual([row["run_id"] for row in topk_validation_only_rows], ["run_b"])
        self.assertEqual({row["panel_value"] for row in topk_by_budget_rows}, {"quick"})
        self.assertEqual({row["panel_value"] for row in topk_by_validation_budget_rows}, {"validated|quick"})
        self.assertEqual([row["run_id"] for row in topk_improvement_rows], ["run_b"])
        self.assertIn("## Report Metadata", report_text)
        self.assertIn("## Baseline Comparison Summary", report_text)
        self.assertIn("## Baseline Detail Preview", report_text)
        self.assertIn("## Paper Key Indicator Table", report_text)
        self.assertIn("## Baseline Winners", report_text)
        self.assertIn("## Key Metric Snapshot", report_text)
        self.assertIn("## Paper-Facing Summary", report_text)
        self.assertIn("## Protocol Quality Overview", report_text)
        self.assertIn("## Protocol Quality By Dimension", report_text)
        self.assertIn("## Protocol Quality Nested Slices", report_text)
        self.assertIn("## Protocol Risk Hotspots", report_text)
        self.assertIn("## Research Quality Gates", report_text)
        self.assertIn("## Appendix Index", report_text)
        self.assertIn("## Appendix: Protocol Coverage Preview", report_text)
        self.assertIn("Drop Rows", report_text)
        self.assertIn("Zero Obs", report_text)
        self.assertIn("## W Summary", report_text)
        self.assertIn("## Paper Main Table", report_text)
        self.assertIn("## Appendix: Paper Full Table Preview", report_text)
        self.assertIn("## Top-K By Engine", report_text)
        self.assertIn("## Appendix: Top-K By Sequence", report_text)
        self.assertIn("## Appendix: Validation-Only Top-K", report_text)
        self.assertIn("## Appendix: Validation × Budget Top-K", report_text)
        self.assertIn(f"summary_source: {summary_path.resolve()}", report_text)
        self.assertIn(f"protocol_source: {protocol_source_path.resolve()}", report_text)
        self.assertIn("quality_gate_overall: warn", report_text)
        self.assertIn("paper_protocol_status: auto", report_text)
        self.assertIn("paper_comparison_target: b0", report_text)
        self.assertIn("W1\\|o2\\|quick\\|s2\\|g2", report_text)

    def test_build_main_matrix_report_paper_view_falls_back_to_non_validation_rows_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_report_paper_fallback_runtime",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            root = Path(tmp)
            summary_path = root / "artifacts" / "experiment_summary.tsv"
            leaderboard_path = root / "artifacts" / "main_matrix_leaderboard.tsv"
            dimension_path = root / "artifacts" / "main_matrix_dimension_summary.tsv"
            baseline_summary_path = root / "artifacts" / "main_matrix_baseline_summary.tsv"
            baseline_detail_path = root / "artifacts" / "main_matrix_baseline_detail.tsv"
            key_indicator_table_path = root / "artifacts" / "main_matrix_key_indicator_table.tsv"
            baseline_winners_path = root / "artifacts" / "main_matrix_baseline_winners.tsv"
            metric_snapshot_path = root / "artifacts" / "main_matrix_metric_snapshot.tsv"
            paper_summary_path = root / "artifacts" / "main_matrix_paper_summary.tsv"
            protocol_source_path = root / "artifacts" / "experiment_protocol_artifacts.tsv"
            protocol_overview_path = root / "artifacts" / "main_matrix_protocol_overview.tsv"
            protocol_dimension_summary_path = root / "artifacts" / "main_matrix_protocol_dimension_summary.tsv"
            protocol_nested_dimension_summary_path = (
                root / "artifacts" / "main_matrix_protocol_nested_dimension_summary.tsv"
            )
            protocol_hotspot_summary_path = root / "artifacts" / "main_matrix_protocol_hotspot_summary.tsv"
            protocol_reason_summary_path = root / "artifacts" / "main_matrix_protocol_reason_summary.tsv"
            quality_gate_path = root / "artifacts" / "main_matrix_quality_gate.tsv"
            appendix_index_path = root / "artifacts" / "main_matrix_appendix_index.tsv"
            protocol_paper_table_path = root / "artifacts" / "main_matrix_protocol_paper_table.tsv"
            paper_main_table_path = root / "artifacts" / "main_matrix_paper_main_table.tsv"
            paper_appendix_table_path = root / "artifacts" / "main_matrix_paper_appendix_table.tsv"
            paper_table_path = root / "artifacts" / "main_matrix_paper_table.tsv"
            topk_overall_path = root / "artifacts" / "main_matrix_topk_overall.tsv"
            topk_by_engine_path = root / "artifacts" / "main_matrix_topk_by_engine.tsv"
            topk_by_weight_path = root / "artifacts" / "main_matrix_topk_by_weight.tsv"
            topk_by_sequence_path = root / "artifacts" / "main_matrix_topk_by_sequence.tsv"
            topk_by_grouping_path = root / "artifacts" / "main_matrix_topk_by_grouping.tsv"
            topk_validation_only_path = root / "artifacts" / "main_matrix_topk_validation_only.tsv"
            topk_by_budget_path = root / "artifacts" / "main_matrix_topk_by_budget.tsv"
            topk_by_validation_budget_path = root / "artifacts" / "main_matrix_topk_by_validation_budget.tsv"
            topk_improvement_path = root / "artifacts" / "main_matrix_topk_improvement.tsv"
            report_path = root / "artifacts" / "main_matrix_report.md"
            row = {field: "" for field in auto_evolve_module.SUMMARY_EXPORT_FIELDNAMES}
            row.update(
                {
                    "combo_key": "W3|o1|quick|s1|g1",
                    "run_id": "fallback_run",
                    "score_rank": "1",
                    "executed_at": "2026-03-28T12:00:00",
                    "plan": "phasePaper",
                    "weight": "W3",
                    "engine": "o1",
                    "budget": "quick",
                    "sequence": "s1",
                    "grouping": "g1",
                    "status": "ok",
                    "validation_enabled": "false",
                    "score": "0.270000",
                    "delta_vs_b0": "-0.025000",
                    "better_than_b0": "true",
                    "yield_metric": "HWAM",
                    "train_mean_nrmse": "0.270000",
                    "valid_mean_nrmse": "",
                }
            )
            auto_evolve_module.write_tsv_dict_rows(summary_path, auto_evolve_module.SUMMARY_EXPORT_FIELDNAMES, [row])

            with patch.multiple(
                auto_evolve_module,
                EXPERIMENT_SUMMARY_TSV_PATH=summary_path,
                EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH=protocol_source_path,
                MAIN_MATRIX_LEADERBOARD_TSV_PATH=leaderboard_path,
                MAIN_MATRIX_DIMENSION_SUMMARY_TSV_PATH=dimension_path,
                MAIN_MATRIX_BASELINE_SUMMARY_TSV_PATH=baseline_summary_path,
                MAIN_MATRIX_BASELINE_DETAIL_TSV_PATH=baseline_detail_path,
                MAIN_MATRIX_KEY_INDICATOR_TABLE_TSV_PATH=key_indicator_table_path,
                MAIN_MATRIX_BASELINE_WINNERS_TSV_PATH=baseline_winners_path,
                MAIN_MATRIX_METRIC_SNAPSHOT_TSV_PATH=metric_snapshot_path,
                MAIN_MATRIX_PAPER_SUMMARY_TSV_PATH=paper_summary_path,
                MAIN_MATRIX_PROTOCOL_OVERVIEW_TSV_PATH=protocol_overview_path,
                MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_TSV_PATH=protocol_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_TSV_PATH=protocol_nested_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_TSV_PATH=protocol_hotspot_summary_path,
                MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH=protocol_reason_summary_path,
                MAIN_MATRIX_QUALITY_GATE_TSV_PATH=quality_gate_path,
                MAIN_MATRIX_APPENDIX_INDEX_TSV_PATH=appendix_index_path,
                MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH=protocol_paper_table_path,
                MAIN_MATRIX_PAPER_MAIN_TABLE_TSV_PATH=paper_main_table_path,
                MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH=paper_appendix_table_path,
                MAIN_MATRIX_PAPER_TABLE_TSV_PATH=paper_table_path,
                MAIN_MATRIX_TOPK_OVERALL_TSV_PATH=topk_overall_path,
                MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH=topk_by_engine_path,
                MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH=topk_by_weight_path,
                MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH=topk_by_sequence_path,
                MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH=topk_by_grouping_path,
                MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH=topk_validation_only_path,
                MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH=topk_by_budget_path,
                MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH=topk_by_validation_budget_path,
                MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH=topk_improvement_path,
                MAIN_MATRIX_REPORT_MD_PATH=report_path,
            ):
                auto_evolve_module.build_main_matrix_report(report_plan="phasePaper")

            paper_rows = auto_evolve_module.read_tsv_rows(paper_table_path)

        self.assertEqual([row["run_id"] for row in paper_rows], ["fallback_run"])

    def test_build_main_matrix_report_respects_explicit_protocol_status_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_report_protocol_filter_runtime",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            root = Path(tmp)
            summary_path = root / "artifacts" / "experiment_summary.tsv"
            protocol_source_path = root / "artifacts" / "experiment_protocol_artifacts.tsv"
            leaderboard_path = root / "artifacts" / "main_matrix_leaderboard.tsv"
            dimension_path = root / "artifacts" / "main_matrix_dimension_summary.tsv"
            baseline_summary_path = root / "artifacts" / "main_matrix_baseline_summary.tsv"
            baseline_detail_path = root / "artifacts" / "main_matrix_baseline_detail.tsv"
            key_indicator_table_path = root / "artifacts" / "main_matrix_key_indicator_table.tsv"
            baseline_winners_path = root / "artifacts" / "main_matrix_baseline_winners.tsv"
            metric_snapshot_path = root / "artifacts" / "main_matrix_metric_snapshot.tsv"
            paper_summary_path = root / "artifacts" / "main_matrix_paper_summary.tsv"
            protocol_overview_path = root / "artifacts" / "main_matrix_protocol_overview.tsv"
            protocol_dimension_summary_path = root / "artifacts" / "main_matrix_protocol_dimension_summary.tsv"
            protocol_nested_dimension_summary_path = (
                root / "artifacts" / "main_matrix_protocol_nested_dimension_summary.tsv"
            )
            protocol_hotspot_summary_path = root / "artifacts" / "main_matrix_protocol_hotspot_summary.tsv"
            protocol_reason_summary_path = root / "artifacts" / "main_matrix_protocol_reason_summary.tsv"
            quality_gate_path = root / "artifacts" / "main_matrix_quality_gate.tsv"
            appendix_index_path = root / "artifacts" / "main_matrix_appendix_index.tsv"
            protocol_paper_table_path = root / "artifacts" / "main_matrix_protocol_paper_table.tsv"
            paper_main_table_path = root / "artifacts" / "main_matrix_paper_main_table.tsv"
            paper_appendix_table_path = root / "artifacts" / "main_matrix_paper_appendix_table.tsv"
            paper_table_path = root / "artifacts" / "main_matrix_paper_table.tsv"
            topk_overall_path = root / "artifacts" / "main_matrix_topk_overall.tsv"
            topk_by_engine_path = root / "artifacts" / "main_matrix_topk_by_engine.tsv"
            topk_by_weight_path = root / "artifacts" / "main_matrix_topk_by_weight.tsv"
            topk_by_sequence_path = root / "artifacts" / "main_matrix_topk_by_sequence.tsv"
            topk_by_grouping_path = root / "artifacts" / "main_matrix_topk_by_grouping.tsv"
            topk_validation_only_path = root / "artifacts" / "main_matrix_topk_validation_only.tsv"
            topk_by_budget_path = root / "artifacts" / "main_matrix_topk_by_budget.tsv"
            topk_by_validation_budget_path = root / "artifacts" / "main_matrix_topk_by_validation_budget.tsv"
            topk_improvement_path = root / "artifacts" / "main_matrix_topk_improvement.tsv"
            report_path = root / "artifacts" / "main_matrix_report.md"

            def summary_row(**overrides: str) -> dict[str, str]:
                row = {field: "" for field in auto_evolve_module.SUMMARY_EXPORT_FIELDNAMES}
                row.update(
                    {
                        "combo_key": "W0|o1|quick|s1|g1",
                        "run_id": "run_default",
                        "score_rank": "99",
                        "executed_at": "2026-03-28T10:00:00",
                        "plan": "phasePaper",
                        "weight": "W0",
                        "engine": "o1",
                        "budget": "quick",
                        "sequence": "s1",
                        "grouping": "g1",
                        "status": "ok",
                        "validation_enabled": "true",
                        "score": "0.300000",
                        "delta_vs_b0": "-0.020000",
                        "better_than_b0": "true",
                        "better_than_b1": "true",
                        "better_than_negative_ref": "true",
                        "yield_metric": "HWAM",
                        "train_mean_nrmse": "0.300000",
                        "valid_mean_nrmse": "0.310000",
                        "all_mean_nrmse": "0.305000",
                    }
                )
                row.update(overrides)
                return row

            auto_evolve_module.write_tsv_dict_rows(
                summary_path,
                auto_evolve_module.SUMMARY_EXPORT_FIELDNAMES,
                [
                    summary_row(
                        combo_key="W1|o2|quick|s2|g2",
                        run_id="run_b",
                        score_rank="1",
                        weight="W1",
                        engine="o2",
                        sequence="s2",
                        grouping="g2",
                        score="0.250000",
                    ),
                    summary_row(
                        combo_key="W2|o1|quick|s2|g3",
                        run_id="run_d",
                        score_rank="2",
                        weight="W2",
                        engine="o1",
                        sequence="s2",
                        grouping="g3",
                        score="0.260000",
                    ),
                ],
            )
            auto_evolve_module.write_tsv_dict_rows(
                protocol_source_path,
                auto_evolve_module.EXPERIMENT_PROTOCOL_ARTIFACTS_FIELDNAMES,
                [
                    {
                        field: value
                        for field, value in {
                            "run_id": "run_b",
                            "contract_status": "ok",
                            "protocol_weight": "W1",
                            "protocol_engine": "o2",
                            "protocol_budget": "quick",
                            "protocol_sequence": "s2",
                            "protocol_grouping": "g2",
                        }.items()
                    },
                    {
                        field: value
                        for field, value in {
                            "run_id": "run_d",
                            "contract_status": "degraded",
                            "protocol_weight": "W2",
                            "protocol_engine": "o1",
                            "protocol_budget": "quick",
                            "protocol_sequence": "s2",
                            "protocol_grouping": "g3",
                        }.items()
                    },
                ],
            )

            with patch.multiple(
                auto_evolve_module,
                EXPERIMENT_SUMMARY_TSV_PATH=summary_path,
                EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH=protocol_source_path,
                MAIN_MATRIX_LEADERBOARD_TSV_PATH=leaderboard_path,
                MAIN_MATRIX_DIMENSION_SUMMARY_TSV_PATH=dimension_path,
                MAIN_MATRIX_BASELINE_SUMMARY_TSV_PATH=baseline_summary_path,
                MAIN_MATRIX_BASELINE_DETAIL_TSV_PATH=baseline_detail_path,
                MAIN_MATRIX_KEY_INDICATOR_TABLE_TSV_PATH=key_indicator_table_path,
                MAIN_MATRIX_BASELINE_WINNERS_TSV_PATH=baseline_winners_path,
                MAIN_MATRIX_METRIC_SNAPSHOT_TSV_PATH=metric_snapshot_path,
                MAIN_MATRIX_PAPER_SUMMARY_TSV_PATH=paper_summary_path,
                MAIN_MATRIX_PROTOCOL_OVERVIEW_TSV_PATH=protocol_overview_path,
                MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_TSV_PATH=protocol_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_TSV_PATH=protocol_nested_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_TSV_PATH=protocol_hotspot_summary_path,
                MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH=protocol_reason_summary_path,
                MAIN_MATRIX_QUALITY_GATE_TSV_PATH=quality_gate_path,
                MAIN_MATRIX_APPENDIX_INDEX_TSV_PATH=appendix_index_path,
                MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH=protocol_paper_table_path,
                MAIN_MATRIX_PAPER_MAIN_TABLE_TSV_PATH=paper_main_table_path,
                MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH=paper_appendix_table_path,
                MAIN_MATRIX_PAPER_TABLE_TSV_PATH=paper_table_path,
                MAIN_MATRIX_TOPK_OVERALL_TSV_PATH=topk_overall_path,
                MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH=topk_by_engine_path,
                MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH=topk_by_weight_path,
                MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH=topk_by_sequence_path,
                MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH=topk_by_grouping_path,
                MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH=topk_validation_only_path,
                MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH=topk_by_budget_path,
                MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH=topk_by_validation_budget_path,
                MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH=topk_improvement_path,
                MAIN_MATRIX_REPORT_MD_PATH=report_path,
            ):
                auto_evolve_module.build_main_matrix_report(
                    report_plan="phasePaper",
                    paper_protocol_status="degraded",
                )

            paper_rows = auto_evolve_module.read_tsv_rows(paper_table_path)
            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual([row["run_id"] for row in paper_rows], ["run_d"])
        self.assertIn("paper_protocol_status: degraded", report_text)

    def test_build_main_matrix_report_migrates_legacy_root_summary_into_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_report_artifacts_runtime",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            root = Path(tmp)
            legacy_summary_path = root / "experiment_summary.tsv"
            summary_path = root / "artifacts" / "experiment_summary.tsv"
            leaderboard_path = root / "artifacts" / "main_matrix_leaderboard.tsv"
            dimension_path = root / "artifacts" / "main_matrix_dimension_summary.tsv"
            baseline_summary_path = root / "artifacts" / "main_matrix_baseline_summary.tsv"
            baseline_detail_path = root / "artifacts" / "main_matrix_baseline_detail.tsv"
            key_indicator_table_path = root / "artifacts" / "main_matrix_key_indicator_table.tsv"
            baseline_winners_path = root / "artifacts" / "main_matrix_baseline_winners.tsv"
            metric_snapshot_path = root / "artifacts" / "main_matrix_metric_snapshot.tsv"
            paper_summary_path = root / "artifacts" / "main_matrix_paper_summary.tsv"
            protocol_source_path = root / "artifacts" / "experiment_protocol_artifacts.tsv"
            protocol_overview_path = root / "artifacts" / "main_matrix_protocol_overview.tsv"
            protocol_dimension_summary_path = root / "artifacts" / "main_matrix_protocol_dimension_summary.tsv"
            protocol_nested_dimension_summary_path = (
                root / "artifacts" / "main_matrix_protocol_nested_dimension_summary.tsv"
            )
            protocol_hotspot_summary_path = root / "artifacts" / "main_matrix_protocol_hotspot_summary.tsv"
            protocol_reason_summary_path = root / "artifacts" / "main_matrix_protocol_reason_summary.tsv"
            quality_gate_path = root / "artifacts" / "main_matrix_quality_gate.tsv"
            appendix_index_path = root / "artifacts" / "main_matrix_appendix_index.tsv"
            protocol_paper_table_path = root / "artifacts" / "main_matrix_protocol_paper_table.tsv"
            paper_main_table_path = root / "artifacts" / "main_matrix_paper_main_table.tsv"
            paper_appendix_table_path = root / "artifacts" / "main_matrix_paper_appendix_table.tsv"
            paper_table_path = root / "artifacts" / "main_matrix_paper_table.tsv"
            topk_overall_path = root / "artifacts" / "main_matrix_topk_overall.tsv"
            topk_by_engine_path = root / "artifacts" / "main_matrix_topk_by_engine.tsv"
            topk_by_weight_path = root / "artifacts" / "main_matrix_topk_by_weight.tsv"
            topk_by_sequence_path = root / "artifacts" / "main_matrix_topk_by_sequence.tsv"
            topk_by_grouping_path = root / "artifacts" / "main_matrix_topk_by_grouping.tsv"
            topk_validation_only_path = root / "artifacts" / "main_matrix_topk_validation_only.tsv"
            topk_by_budget_path = root / "artifacts" / "main_matrix_topk_by_budget.tsv"
            topk_by_validation_budget_path = root / "artifacts" / "main_matrix_topk_by_validation_budget.tsv"
            topk_improvement_path = root / "artifacts" / "main_matrix_topk_improvement.tsv"
            report_path = root / "artifacts" / "main_matrix_report.md"
            row = {field: "" for field in auto_evolve_module.SUMMARY_EXPORT_FIELDNAMES}
            row.update(
                {
                    "combo_key": "W2|o1|quick|s1|g1",
                    "run_id": "legacy_run",
                    "score_rank": "1",
                    "executed_at": "2026-03-28T11:00:00",
                    "plan": "phaseLegacy",
                    "weight": "W2",
                    "engine": "o1",
                    "budget": "quick",
                    "sequence": "s1",
                    "grouping": "g1",
                    "status": "ok",
                    "score": "0.220000",
                    "delta_vs_b0": "-0.040000",
                    "better_than_b0": "true",
                    "better_than_b1": "true",
                    "better_than_negative_ref": "true",
                    "yield_metric": "HWAM",
                    "train_mean_nrmse": "0.220000",
                    "valid_mean_nrmse": "0.230000",
                    "all_mean_nrmse": "0.225000",
                }
            )
            auto_evolve_module.write_tsv_dict_rows(
                legacy_summary_path,
                auto_evolve_module.SUMMARY_EXPORT_FIELDNAMES,
                [row],
            )

            with patch.object(auto_evolve_module, "SANDBOX_DIR", root), patch.object(
                auto_evolve_module,
                "STANDARD_ARTIFACT_PATHS",
                (
                    summary_path,
                    leaderboard_path,
                    dimension_path,
                    baseline_summary_path,
                    baseline_detail_path,
                    key_indicator_table_path,
                    baseline_winners_path,
                    metric_snapshot_path,
                    paper_summary_path,
                    protocol_overview_path,
                    protocol_dimension_summary_path,
                    protocol_nested_dimension_summary_path,
                    protocol_hotspot_summary_path,
                    protocol_reason_summary_path,
                    quality_gate_path,
                    appendix_index_path,
                    protocol_paper_table_path,
                    paper_main_table_path,
                    paper_appendix_table_path,
                    paper_table_path,
                    topk_overall_path,
                    topk_by_engine_path,
                    topk_by_weight_path,
                    topk_by_sequence_path,
                    topk_by_grouping_path,
                    topk_validation_only_path,
                    topk_by_budget_path,
                    topk_by_validation_budget_path,
                    topk_improvement_path,
                    report_path,
                ),
            ), patch.multiple(
                auto_evolve_module,
                EXPERIMENT_SUMMARY_TSV_PATH=summary_path,
                EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH=protocol_source_path,
                MAIN_MATRIX_LEADERBOARD_TSV_PATH=leaderboard_path,
                MAIN_MATRIX_DIMENSION_SUMMARY_TSV_PATH=dimension_path,
                MAIN_MATRIX_BASELINE_SUMMARY_TSV_PATH=baseline_summary_path,
                MAIN_MATRIX_BASELINE_DETAIL_TSV_PATH=baseline_detail_path,
                MAIN_MATRIX_KEY_INDICATOR_TABLE_TSV_PATH=key_indicator_table_path,
                MAIN_MATRIX_BASELINE_WINNERS_TSV_PATH=baseline_winners_path,
                MAIN_MATRIX_METRIC_SNAPSHOT_TSV_PATH=metric_snapshot_path,
                MAIN_MATRIX_PAPER_SUMMARY_TSV_PATH=paper_summary_path,
                MAIN_MATRIX_PROTOCOL_OVERVIEW_TSV_PATH=protocol_overview_path,
                MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_TSV_PATH=protocol_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_TSV_PATH=protocol_nested_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_TSV_PATH=protocol_hotspot_summary_path,
                MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH=protocol_reason_summary_path,
                MAIN_MATRIX_QUALITY_GATE_TSV_PATH=quality_gate_path,
                MAIN_MATRIX_APPENDIX_INDEX_TSV_PATH=appendix_index_path,
                MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH=protocol_paper_table_path,
                MAIN_MATRIX_PAPER_MAIN_TABLE_TSV_PATH=paper_main_table_path,
                MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH=paper_appendix_table_path,
                MAIN_MATRIX_PAPER_TABLE_TSV_PATH=paper_table_path,
                MAIN_MATRIX_TOPK_OVERALL_TSV_PATH=topk_overall_path,
                MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH=topk_by_engine_path,
                MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH=topk_by_weight_path,
                MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH=topk_by_sequence_path,
                MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH=topk_by_grouping_path,
                MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH=topk_validation_only_path,
                MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH=topk_by_budget_path,
                MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH=topk_by_validation_budget_path,
                MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH=topk_improvement_path,
                MAIN_MATRIX_REPORT_MD_PATH=report_path,
            ):
                auto_evolve_module.build_main_matrix_report(top_n=1)

            leaderboard_rows = auto_evolve_module.read_tsv_rows(leaderboard_path)
            report_text = report_path.read_text(encoding="utf-8")
            self.assertFalse(legacy_summary_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertEqual(len(leaderboard_rows), 1)
            self.assertEqual(leaderboard_rows[0]["run_id"], "legacy_run")
            self.assertIn(str(summary_path.resolve()), report_text)

    def test_rebuild_main_matrix_report_artifacts_runs_end_to_end_from_runtime_protocol_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_report_smoke_runtime",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            root = Path(tmp)
            artifacts_dir = root / "artifacts"
            experiment_runs_path = artifacts_dir / "experiment_runs.tsv"
            protocol_source_path = artifacts_dir / "experiment_protocol_artifacts.tsv"
            aggregate_metrics_path = artifacts_dir / "experiment_aggregate_metrics.tsv"
            summary_path = artifacts_dir / "experiment_summary.tsv"
            leaderboard_path = artifacts_dir / "main_matrix_leaderboard.tsv"
            dimension_path = artifacts_dir / "main_matrix_dimension_summary.tsv"
            baseline_summary_path = artifacts_dir / "main_matrix_baseline_summary.tsv"
            baseline_detail_path = artifacts_dir / "main_matrix_baseline_detail.tsv"
            key_indicator_table_path = artifacts_dir / "main_matrix_key_indicator_table.tsv"
            baseline_winners_path = artifacts_dir / "main_matrix_baseline_winners.tsv"
            metric_snapshot_path = artifacts_dir / "main_matrix_metric_snapshot.tsv"
            paper_summary_path = artifacts_dir / "main_matrix_paper_summary.tsv"
            protocol_overview_path = artifacts_dir / "main_matrix_protocol_overview.tsv"
            protocol_dimension_summary_path = artifacts_dir / "main_matrix_protocol_dimension_summary.tsv"
            protocol_nested_dimension_summary_path = artifacts_dir / "main_matrix_protocol_nested_dimension_summary.tsv"
            protocol_hotspot_summary_path = artifacts_dir / "main_matrix_protocol_hotspot_summary.tsv"
            protocol_reason_summary_path = artifacts_dir / "main_matrix_protocol_reason_summary.tsv"
            quality_gate_path = artifacts_dir / "main_matrix_quality_gate.tsv"
            appendix_index_path = artifacts_dir / "main_matrix_appendix_index.tsv"
            protocol_paper_table_path = artifacts_dir / "main_matrix_protocol_paper_table.tsv"
            paper_main_table_path = artifacts_dir / "main_matrix_paper_main_table.tsv"
            paper_appendix_table_path = artifacts_dir / "main_matrix_paper_appendix_table.tsv"
            paper_table_path = artifacts_dir / "main_matrix_paper_table.tsv"
            topk_overall_path = artifacts_dir / "main_matrix_topk_overall.tsv"
            topk_by_engine_path = artifacts_dir / "main_matrix_topk_by_engine.tsv"
            topk_by_weight_path = artifacts_dir / "main_matrix_topk_by_weight.tsv"
            topk_by_sequence_path = artifacts_dir / "main_matrix_topk_by_sequence.tsv"
            topk_by_grouping_path = artifacts_dir / "main_matrix_topk_by_grouping.tsv"
            topk_validation_only_path = artifacts_dir / "main_matrix_topk_validation_only.tsv"
            topk_by_budget_path = artifacts_dir / "main_matrix_topk_by_budget.tsv"
            topk_by_validation_budget_path = artifacts_dir / "main_matrix_topk_by_validation_budget.tsv"
            topk_improvement_path = artifacts_dir / "main_matrix_topk_improvement.tsv"
            report_path = artifacts_dir / "main_matrix_report.md"
            workspace_a = root / "workspace_a"
            workspace_b = root / "workspace_b"

            def write_protocol_artifacts(
                workspace: Path,
                *,
                run_id: str,
                trt: int,
                sequence: str,
            ) -> None:
                runtime_dir = workspace / "runs" / "runtime"
                runtime_dir.mkdir(parents=True, exist_ok=True)
                (runtime_dir / "run_manifest.json").write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "crop": "wheat",
                            "scenario": {"filex_name": "SWSW7501.WHX", "trts": [trt]},
                            "protocol": {
                                "weight": "W8_DSSAT_PEST_Group_Max",
                                "engine": "o1_least_squares",
                                "budget": "quick",
                                "sequence": sequence,
                                "grouping": "g3_dssat_extended",
                                "weight_mode": "w8_dssat_group_max",
                            },
                            "observations": {
                                "requested_summary_metrics": ["HWAM"],
                                "requested_t_vars": ["LAID"],
                            },
                            "resolved_output": {
                                "summary_metrics": ["HWAM"],
                                "t_vars": ["LAID"],
                                "active_groups": ["obs_yield"],
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                (runtime_dir / "contract_report.json").write_text(
                    json.dumps(
                        {
                            "crop": "wheat",
                            "status": "ok",
                            "resolved": {
                                "active_groups": ["obs_yield"],
                                "summary_metrics": ["HWAM"],
                                "t_vars": ["LAID"],
                            },
                            "requested": {
                                "summary_metrics": ["HWAM"],
                                "t_vars": ["LAID"],
                            },
                            "summary": {
                                "active_metric_count": 1,
                                "active_observation_count": 12,
                                "dropped_group_count": 0,
                                "weight_fallback_count": 0,
                                "zero_weight_observation_count": 0,
                                "fallback_metrics": [],
                            },
                            "dropped_groups": [],
                            "weight_fallbacks": [],
                            "zero_weight_observations": [],
                            "issues": [],
                        }
                    ),
                    encoding="utf-8",
                )

            write_protocol_artifacts(
                workspace_a,
                run_id="run_smoke_a",
                trt=1,
                sequence="s2_sequential_phase",
            )
            write_protocol_artifacts(
                workspace_b,
                run_id="run_smoke_b",
                trt=2,
                sequence="s3_wls_joint",
            )

            aggregate_rows = [
                {
                    "run_id": "run_smoke_a",
                    "plan": "phaseSmoke",
                    "weight": "W8_DSSAT_PEST_Group_Max",
                    "engine": "o1_least_squares",
                    "budget": "quick",
                    "sequence": "s2_sequential_phase",
                    "grouping": "g3_dssat_extended",
                    "status": "ok",
                    "split": "train",
                    "metric": "HWAM",
                    "count": "4",
                    "nrmse": "0.210000",
                    "bias": "0.010000",
                },
                {
                    "run_id": "run_smoke_a",
                    "plan": "phaseSmoke",
                    "weight": "W8_DSSAT_PEST_Group_Max",
                    "engine": "o1_least_squares",
                    "budget": "quick",
                    "sequence": "s2_sequential_phase",
                    "grouping": "g3_dssat_extended",
                    "status": "ok",
                    "split": "valid",
                    "metric": "HWAM",
                    "count": "2",
                    "nrmse": "0.240000",
                    "bias": "0.000000",
                },
                {
                    "run_id": "run_smoke_a",
                    "plan": "phaseSmoke",
                    "weight": "W8_DSSAT_PEST_Group_Max",
                    "engine": "o1_least_squares",
                    "budget": "quick",
                    "sequence": "s2_sequential_phase",
                    "grouping": "g3_dssat_extended",
                    "status": "ok",
                    "split": "all",
                    "metric": "HWAM",
                    "count": "6",
                    "nrmse": "0.220000",
                    "bias": "0.005000",
                },
                {
                    "run_id": "run_smoke_b",
                    "plan": "phaseSmoke",
                    "weight": "W8_DSSAT_PEST_Group_Max",
                    "engine": "o1_least_squares",
                    "budget": "quick",
                    "sequence": "s3_wls_joint",
                    "grouping": "g3_dssat_extended",
                    "status": "ok",
                    "split": "train",
                    "metric": "HWAM",
                    "count": "4",
                    "nrmse": "0.190000",
                    "bias": "-0.010000",
                },
                {
                    "run_id": "run_smoke_b",
                    "plan": "phaseSmoke",
                    "weight": "W8_DSSAT_PEST_Group_Max",
                    "engine": "o1_least_squares",
                    "budget": "quick",
                    "sequence": "s3_wls_joint",
                    "grouping": "g3_dssat_extended",
                    "status": "ok",
                    "split": "valid",
                    "metric": "HWAM",
                    "count": "2",
                    "nrmse": "0.220000",
                    "bias": "0.020000",
                },
                {
                    "run_id": "run_smoke_b",
                    "plan": "phaseSmoke",
                    "weight": "W8_DSSAT_PEST_Group_Max",
                    "engine": "o1_least_squares",
                    "budget": "quick",
                    "sequence": "s3_wls_joint",
                    "grouping": "g3_dssat_extended",
                    "status": "ok",
                    "split": "all",
                    "metric": "HWAM",
                    "count": "6",
                    "nrmse": "0.200000",
                    "bias": "0.000000",
                },
            ]

            with patch.object(auto_evolve_module, "SANDBOX_DIR", root), patch.object(
                auto_evolve_module,
                "STANDARD_ARTIFACT_PATHS",
                (
                    summary_path,
                    leaderboard_path,
                    dimension_path,
                    baseline_summary_path,
                    baseline_detail_path,
                    key_indicator_table_path,
                    baseline_winners_path,
                    metric_snapshot_path,
                    paper_summary_path,
                    protocol_overview_path,
                    protocol_dimension_summary_path,
                    protocol_nested_dimension_summary_path,
                    protocol_hotspot_summary_path,
                    protocol_reason_summary_path,
                    quality_gate_path,
                    appendix_index_path,
                    protocol_paper_table_path,
                    paper_main_table_path,
                    paper_appendix_table_path,
                    paper_table_path,
                    topk_overall_path,
                    topk_by_engine_path,
                    topk_by_weight_path,
                    topk_by_sequence_path,
                    topk_by_grouping_path,
                    topk_validation_only_path,
                    topk_by_budget_path,
                    topk_by_validation_budget_path,
                    topk_improvement_path,
                    report_path,
                ),
            ), patch.multiple(
                auto_evolve_module,
                EXPERIMENT_RUNS_TSV_PATH=experiment_runs_path,
                EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH=protocol_source_path,
                EXPERIMENT_AGGREGATE_METRICS_TSV_PATH=aggregate_metrics_path,
                EXPERIMENT_SUMMARY_TSV_PATH=summary_path,
                MAIN_MATRIX_LEADERBOARD_TSV_PATH=leaderboard_path,
                MAIN_MATRIX_DIMENSION_SUMMARY_TSV_PATH=dimension_path,
                MAIN_MATRIX_BASELINE_SUMMARY_TSV_PATH=baseline_summary_path,
                MAIN_MATRIX_BASELINE_DETAIL_TSV_PATH=baseline_detail_path,
                MAIN_MATRIX_KEY_INDICATOR_TABLE_TSV_PATH=key_indicator_table_path,
                MAIN_MATRIX_BASELINE_WINNERS_TSV_PATH=baseline_winners_path,
                MAIN_MATRIX_METRIC_SNAPSHOT_TSV_PATH=metric_snapshot_path,
                MAIN_MATRIX_PAPER_SUMMARY_TSV_PATH=paper_summary_path,
                MAIN_MATRIX_PROTOCOL_OVERVIEW_TSV_PATH=protocol_overview_path,
                MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_TSV_PATH=protocol_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_TSV_PATH=protocol_nested_dimension_summary_path,
                MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_TSV_PATH=protocol_hotspot_summary_path,
                MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH=protocol_reason_summary_path,
                MAIN_MATRIX_QUALITY_GATE_TSV_PATH=quality_gate_path,
                MAIN_MATRIX_APPENDIX_INDEX_TSV_PATH=appendix_index_path,
                MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH=protocol_paper_table_path,
                MAIN_MATRIX_PAPER_MAIN_TABLE_TSV_PATH=paper_main_table_path,
                MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH=paper_appendix_table_path,
                MAIN_MATRIX_PAPER_TABLE_TSV_PATH=paper_table_path,
                MAIN_MATRIX_TOPK_OVERALL_TSV_PATH=topk_overall_path,
                MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH=topk_by_engine_path,
                MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH=topk_by_weight_path,
                MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH=topk_by_sequence_path,
                MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH=topk_by_grouping_path,
                MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH=topk_validation_only_path,
                MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH=topk_by_budget_path,
                MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH=topk_by_validation_budget_path,
                MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH=topk_improvement_path,
                MAIN_MATRIX_REPORT_MD_PATH=report_path,
            ):
                auto_evolve_module.append_experiment_runs_tsv(
                    auto_evolve_module.MatrixResult(
                        run_id="run_smoke_a",
                        weight_name="W8_DSSAT_PEST_Group_Max",
                        engine="o1_least_squares",
                        budget="quick",
                        sequence="s2_sequential_phase",
                        grouping="g3_dssat_extended",
                        score=0.22,
                        status="ok",
                        weight_mode="w8_dssat_group_max",
                        stdout="",
                        negative_ref_profile="baseline",
                        negative_ref_score=0.35,
                        train_mean_nrmse=0.21,
                        valid_mean_nrmse=0.24,
                        all_mean_nrmse=0.22,
                        yield_metric="HWAM",
                        train_yield_nrmse=0.21,
                        train_yield_bias=0.01,
                        valid_yield_nrmse=0.24,
                        valid_yield_bias=0.00,
                        plan="phaseSmoke",
                        executed_at="2026-04-02T09:00:00",
                        baseline_b0_score=0.26,
                        baseline_b1_score=0.24,
                        workspace_dir=str(workspace_a),
                    )
                )
                auto_evolve_module.append_experiment_runs_tsv(
                    auto_evolve_module.MatrixResult(
                        run_id="run_smoke_b",
                        weight_name="W8_DSSAT_PEST_Group_Max",
                        engine="o1_least_squares",
                        budget="quick",
                        sequence="s3_wls_joint",
                        grouping="g3_dssat_extended",
                        score=0.20,
                        status="ok",
                        weight_mode="w8_dssat_group_max",
                        stdout="",
                        negative_ref_profile="baseline",
                        negative_ref_score=0.35,
                        train_mean_nrmse=0.19,
                        valid_mean_nrmse=0.22,
                        all_mean_nrmse=0.20,
                        yield_metric="HWAM",
                        train_yield_nrmse=0.19,
                        train_yield_bias=-0.01,
                        valid_yield_nrmse=0.22,
                        valid_yield_bias=0.02,
                        plan="phaseSmoke",
                        executed_at="2026-04-02T09:05:00",
                        baseline_b0_score=0.26,
                        baseline_b1_score=0.24,
                        workspace_dir=str(workspace_b),
                    )
                )
                auto_evolve_module.write_tsv_dict_rows(
                    aggregate_metrics_path,
                    auto_evolve_module.AGGREGATE_METRIC_EXPORT_FIELDNAMES,
                    aggregate_rows,
                )
                outputs = auto_evolve_module.rebuild_main_matrix_report_artifacts(
                    report_plan="phaseSmoke",
                    top_n=2,
                    top_k_per_panel=1,
                )

            summary_rows = auto_evolve_module.read_tsv_rows(summary_path)
            protocol_rows = auto_evolve_module.read_tsv_rows(protocol_source_path)
            leaderboard_rows = auto_evolve_module.read_tsv_rows(leaderboard_path)
            quality_gate_rows = auto_evolve_module.read_tsv_rows(quality_gate_path)
            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual(outputs["report"], report_path)
        self.assertEqual(outputs["quality_gate"], quality_gate_path)
        self.assertEqual(len(summary_rows), 2)
        self.assertEqual([row["run_id"] for row in leaderboard_rows], ["run_smoke_b", "run_smoke_a"])
        self.assertEqual([row["run_id"] for row in protocol_rows], ["run_smoke_a", "run_smoke_b"])
        self.assertTrue(all(row["contract_status"] == "ok" for row in protocol_rows))
        self.assertEqual(
            auto_evolve_module.resolve_main_matrix_quality_gate_overall_status(quality_gate_rows),
            "pass",
        )
        self.assertIn("quality_gate_overall: pass", report_text)
        self.assertIn(str(summary_path.resolve()), report_text)
        self.assertIn(str(protocol_source_path.resolve()), report_text)

    def test_main_matrix_quality_gate_batch_decision_respects_stop_level(self) -> None:
        auto_evolve_module = load_module_from_path(
            "test_autoresearch_auto_evolve_quality_gate_decision_runtime",
            ROOT.parent / "autoresearch_sandbox" / "auto_evolve.py",
            extra_sys_path=[ROOT.parent / "autoresearch_sandbox"],
        )

        pass_rows = [{"gate_key": "schema", "gate_level": "required", "status": "pass"}]
        warn_rows = [{"gate_key": "coverage", "gate_level": "advisory", "status": "fail"}]
        fail_rows = [{"gate_key": "schema", "gate_level": "required", "status": "fail"}]

        self.assertEqual(
            auto_evolve_module.resolve_main_matrix_quality_gate_batch_decision(pass_rows, stop_level="required"),
            "go",
        )
        self.assertEqual(
            auto_evolve_module.resolve_main_matrix_quality_gate_batch_decision(warn_rows, stop_level="required"),
            "go",
        )
        self.assertEqual(
            auto_evolve_module.resolve_main_matrix_quality_gate_batch_decision(warn_rows, stop_level="advisory"),
            "stop",
        )
        self.assertEqual(
            auto_evolve_module.resolve_main_matrix_quality_gate_batch_decision(fail_rows, stop_level="required"),
            "stop",
        )
        self.assertEqual(
            auto_evolve_module.resolve_main_matrix_quality_gate_batch_decision(fail_rows, stop_level="off"),
            "go",
        )

    def test_run_matrix_stops_when_required_quality_gate_fails(self) -> None:
        auto_evolve_module = load_module_from_path(
            "test_autoresearch_auto_evolve_matrix_quality_gate_runtime",
            ROOT.parent / "autoresearch_sandbox" / "auto_evolve.py",
            extra_sys_path=[ROOT.parent / "autoresearch_sandbox"],
        )
        result = auto_evolve_module.MatrixResult(
            run_id="run_matrix_gate",
            weight_name="W1_Inverse_Variance",
            engine="o1_least_squares",
            budget="quick",
            sequence="s1_naive_joint",
            grouping="g1_flat_all_in_one",
            score=0.11,
            status="ok",
            weight_mode="w1_inverse_variance",
            stdout="",
            negative_ref_profile="baseline",
            negative_ref_score=0.3,
            train_mean_nrmse=0.1,
            valid_mean_nrmse=0.11,
            all_mean_nrmse=0.105,
            yield_metric="HWAM",
            train_yield_nrmse=0.1,
            train_yield_bias=0.0,
            valid_yield_nrmse=0.11,
            valid_yield_bias=0.0,
        )

        with tempfile.TemporaryDirectory() as tmp:
            quality_gate_path = Path(tmp) / "main_matrix_quality_gate.tsv"
            with ExitStack() as stack:
                stack.enter_context(patch.object(auto_evolve_module, "migrate_legacy_root_artifacts"))
                stack.enter_context(patch.object(auto_evolve_module, "ensure_matrix_header"))
                stack.enter_context(patch.object(auto_evolve_module, "read_text", return_value="strategy"))
                stack.enter_context(patch.object(auto_evolve_module, "write_text"))
                stack.enter_context(
                    patch.object(
                        auto_evolve_module,
                        "resolve_matrix_scope",
                        return_value=(
                            ["W1_Inverse_Variance"],
                            ["o1_least_squares"],
                            ["quick"],
                            ["s1_naive_joint"],
                            ["g1_flat_all_in_one"],
                        ),
                    )
                )
                stack.enter_context(
                    patch.object(
                        auto_evolve_module,
                        "select_weight_candidates",
                        return_value=[SimpleNamespace(name="W1_Inverse_Variance", weight_mode="w1_inverse_variance")],
                    )
                )
                stack.enter_context(
                    patch.object(
                        auto_evolve_module,
                        "run_baseline_reference",
                        side_effect=[("b0", 0.2), ("b1", 0.19), ("neg", 0.3)],
                    )
                )
                stack.enter_context(
                    patch.object(auto_evolve_module, "compatible_groupings_for_sequence", return_value=["g1_flat_all_in_one"])
                )
                stack.enter_context(patch.object(auto_evolve_module, "plan_allows_cell", return_value=True))
                stack.enter_context(patch.object(auto_evolve_module, "execute_matrix_job", return_value=result))
                stack.enter_context(patch.object(auto_evolve_module, "append_matrix_tsv"))
                stack.enter_context(patch.object(auto_evolve_module, "append_experiment_runs_tsv"))
                stack.enter_context(patch.object(auto_evolve_module, "append_experiment_params_tsv"))
                stack.enter_context(patch.object(auto_evolve_module, "append_experiment_metrics_long_tsv"))
                stack.enter_context(patch.object(auto_evolve_module, "append_experiment_aggregate_metrics_tsv"))
                stack.enter_context(patch.object(auto_evolve_module, "write_matrix_result_log"))
                stack.enter_context(patch.object(auto_evolve_module, "write_matrix_log"))
                stack.enter_context(patch.object(auto_evolve_module, "rebuild_experiment_summary_exports"))
                stack.enter_context(
                    patch.object(
                        auto_evolve_module,
                        "rebuild_main_matrix_report_artifacts",
                        return_value={"quality_gate": quality_gate_path},
                    )
                )
                stack.enter_context(
                    patch.object(
                        auto_evolve_module,
                        "read_tsv_rows",
                        return_value=[{"gate_key": "paper_main_table_schema", "gate_level": "required", "status": "fail"}],
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "quality gate blocked publish decision"):
                    auto_evolve_module.run_matrix(
                        weights=["W1_Inverse_Variance"],
                        engines=["o1_least_squares"],
                        budgets=["quick"],
                        sequences=["s1_naive_joint"],
                        groupings=["g1_flat_all_in_one"],
                        quality_gate_stop_level="required",
                    )

    def test_live_wheat_dssat_acceptance_if_enabled(self) -> None:
        if os.environ.get("RUN_LIVE_WHEAT_DSSAT_ACCEPTANCE", "").strip().lower() not in {"1", "true", "yes", "on"}:
            self.skipTest("set RUN_LIVE_WHEAT_DSSAT_ACCEPTANCE=1 to enable live DSSAT acceptance")

        source_case_dir = Path(r"C:\DSSAT48\Wheat")
        source_exe = Path(r"C:\DSSAT48\DSCSM048.EXE")
        source_filex = source_case_dir / "SWSW7501.WHX"
        source_wha = source_case_dir / "SWSW7501.WHA"
        source_wht = source_case_dir / "SWSW7501.WHT"
        required_paths = (source_case_dir, source_exe, source_filex, source_wha, source_wht)
        missing = [str(path) for path in required_paths if not path.exists()]
        if missing:
            self.skipTest(f"missing live Wheat DSSAT files: {', '.join(missing)}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_dir = root / "Wheat"
            shutil.copytree(source_case_dir, case_dir)
            cfg_path = root / "project_live_wheat.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "crop_family": "wheat",
                        "cultivar": {"code": "IB1500", "cul_file": "WHCER048.CUL"},
                        "parameters": {"bounds": {}},
                        "paths": {
                            "dssat_case_dir": str(case_dir),
                            "dssat_exe": str(source_exe),
                            "base_filex": str(case_dir / "SWSW7501.WHX"),
                            "live_filex": str(case_dir / "SWSW7501.WHX"),
                            "obs_a": str(case_dir / "SWSW7501.WHA"),
                            "obs_t": str(case_dir / "SWSW7501.WHT"),
                        },
                        "observations": {
                            "allow_missing_files": False,
                            "yield_var": "HWAM",
                            "summary_vars": ["HWAM", "LAIX"],
                            "t_vars": ["LAID"],
                            "treatment_mapping": {"1": "1"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "params.dat").write_text("", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "PROJECT_CONFIG": str(cfg_path),
                    "DSSAT_TRTS": "1",
                    "DSSAT_KEEP_OUTPUTS": "0",
                },
                clear=False,
            ):
                prepared = run_model.prepare_case_run(root)
                metrics_by_trt, treatment_calls = run_model.execute_case(
                    prepared.base,
                    prepared.live_filex,
                    prepared.cul_path,
                    prepared.cultivar_code,
                    prepared.filex_name,
                    prepared.dssat_dir,
                    prepared.cfg,
                    prepared.trts,
                    prepared.case_runtime,
                    prepared.file_state,
                    prepared.keep_outputs,
                )

        self.assertEqual(prepared.dssat_dir, case_dir)
        self.assertEqual(prepared.trts, [1])
        self.assertEqual(treatment_calls, 1)
        self.assertIn(1, metrics_by_trt)
        self.assertIn("hwam", metrics_by_trt[1])
        self.assertTrue(np.isfinite(metrics_by_trt[1]["hwam"]))

    def test_load_project_config_uses_default_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            cfg_path = project_root / "config" / "project.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            expected = {"crop_family": "wheat", "paths": {"dssat_case_dir": "data/dssat"}}
            cfg_path.write_text(json.dumps(expected), encoding="utf-8")

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PROJECT_CONFIG", None)
                self.assertEqual(load_project_config(project_root), expected)

    def test_load_project_config_prefers_project_config_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_cfg = root / "config" / "project.json"
            env_cfg = root / "custom" / "project_env.json"
            default_cfg.parent.mkdir(parents=True, exist_ok=True)
            env_cfg.parent.mkdir(parents=True, exist_ok=True)
            default_cfg.write_text(json.dumps({"source": "default"}), encoding="utf-8")
            env_cfg.write_text(json.dumps({"source": "env"}), encoding="utf-8")

            with patch.dict(os.environ, {"PROJECT_CONFIG": str(env_cfg)}, clear=False):
                self.assertEqual(load_project_config(root), {"source": "env"})

    def test_load_project_config_returns_empty_dict_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PROJECT_CONFIG", None)
                self.assertEqual(load_project_config(project_root), {})

    def test_load_project_config_supports_custom_candidate_relatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            legacy_cfg = project_root / "project_wheat.json"
            legacy_cfg.write_text(json.dumps({"source": "legacy"}), encoding="utf-8")

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PROJECT_CONFIG", None)
                loaded = load_project_config(
                    project_root,
                    candidate_relatives=("project.json", "project_wheat.json"),
                )

            self.assertEqual(loaded, {"source": "legacy"})

    def test_resolve_parameter_bounds_prefers_custom_then_official_then_fallback(self) -> None:
        bounds, rows = dssat_io.resolve_parameter_bounds(
            initial_values={"p1v": 12.0, "g1": 30.0, "g2": 40.0, "zero": 0.0},
            custom_bounds={"p1v": [5.0, 15.0, "g_custom"]},
            official_bounds={"g1": [10.0, 35.0, "g_official"]},
            fallback_mode="relative_15",
            default_group="g_cul",
        )

        self.assertEqual(bounds["p1v"], [5.0, 15.0, "g_custom"])
        self.assertEqual(bounds["g1"], [10.0, 35.0, "g_official"])
        self.assertEqual(bounds["g2"], [34.0, 46.0, "g_cul"])
        self.assertEqual(bounds["zero"], [-0.1, 0.1, "g_cul"])
        rows_by_name = {str(row["parameter"]): row for row in rows}
        self.assertEqual(rows_by_name["p1v"]["source"], "custom")
        self.assertEqual(rows_by_name["g1"]["source"], "official")
        self.assertEqual(rows_by_name["g2"]["source"], "fallback_15")
        self.assertEqual(rows_by_name["zero"]["source"], "fallback_15")

    def test_resolve_parameter_runtime_contract_uses_generic_project_config(self) -> None:
        cfg = {
            "crop_family": "maize",
            "params": {
                "order": ["p1", "g2", "phint"],
                "initial_values": {"p1": 245.0},
                "bounds": {
                    "p1": [220.0, 280.0, "g_pheno"],
                    "g2": [700.0, 950.0, "g_sink"],
                    "phint": [35.0, 55.0, "g_pheno"],
                },
            },
            "baselines": {
                "negative_optimization_reference": "b0_glue_seed",
                "profiles": {
                    "b0_glue_seed": {
                        "param_source": {
                            "type": "inline_values",
                            "values": {"g2": 820.0, "phint": 44.0},
                        }
                    }
                },
            },
        }

        names = dssat_io.resolve_parameter_names(cfg)
        initial_values = dssat_io.resolve_initial_parameter_values(cfg, names)
        bounds = dssat_io.resolve_parameter_bounds_pairs(cfg, names)

        self.assertEqual(names, ["p1", "g2", "phint"])
        self.assertEqual(initial_values, [245.0, 820.0, 44.0])
        self.assertEqual(bounds, [(220.0, 280.0), (700.0, 950.0), (35.0, 55.0)])

    def test_load_bounds_source_supports_family_wrapped_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bounds_path = root / "official_bounds.json"
            bounds_path.write_text(
                json.dumps(
                    {
                        "families": {
                            "wheat": {
                                "bounds": {
                                    "p1v": [1.0, 9.0, "g_pheno"],
                                    "g1": [10.0, 30.0, "g_grain"],
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            loaded = dssat_io.load_bounds_source(bounds_path, crop_family="wheat")

            self.assertEqual(
                loaded,
                {
                    "p1v": [1.0, 9.0, "g_pheno"],
                    "g1": [10.0, 30.0, "g_grain"],
                },
            )

    def test_prepare_parameter_bounds_updates_config_and_writes_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = root / "run"
            project_root = root / "project"
            cwd.mkdir()
            (project_root / "work").mkdir(parents=True)
            (project_root / "work" / "params.dat").write_text(
                "p1v 12.0\n"
                "g1 30.0\n"
                "g2 40.0\n",
                encoding="utf-8",
            )
            cfg = {
                "crop_family": "wheat",
                "params": {
                    "bounds": {"p1v": [5.0, 15.0, "g_custom"]},
                    "official_bounds": {"g1": [10.0, 35.0, "g_official"]},
                    "fallback_mode": "relative_30",
                }
            }

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                rows = build_pest_setup._prepare_parameter_bounds(cwd, project_root, cfg)

            self.assertEqual(cfg["params"]["bounds"]["p1v"], [5.0, 15.0, "g_custom"])
            self.assertEqual(cfg["params"]["bounds"]["g1"], [10.0, 35.0, "g_official"])
            self.assertEqual(cfg["params"]["bounds"]["g2"], [28.0, 52.0, "g_cul"])
            report_path = cwd / "parameter_bounds_preview.csv"
            self.assertTrue(report_path.exists())
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn(
                "parameter,crop_family,initial,lower,upper,group,source,priority_rank,official_source_path,span",
                report_text,
            )
            self.assertIn("p1v,wheat,12.0,5.0,15.0,g_custom,custom,1,,10.0", report_text)
            self.assertIn("g1,wheat,30.0,10.0,35.0,g_official,official,2,,25.0", report_text)
            terminal_text = buffer.getvalue()
            self.assertIn("parameter      source", terminal_text)
            self.assertIn("p1v            custom", terminal_text)
            self.assertEqual(len(rows), 3)

    def test_prepare_parameter_bounds_loads_official_bounds_from_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = root / "run"
            project_root = root / "project"
            cwd.mkdir()
            (project_root / "work").mkdir(parents=True)
            (project_root / "work" / "params.dat").write_text(
                "p1v 12.0\n"
                "g1 30.0\n"
                "g2 40.0\n",
                encoding="utf-8",
            )
            bounds_path = project_root / "config" / "official_bounds.json"
            bounds_path.parent.mkdir(parents=True, exist_ok=True)
            bounds_path.write_text(
                json.dumps(
                    {
                        "families": {
                            "wheat": {
                                "bounds": {
                                    "g1": [10.0, 35.0, "g_official"],
                                    "g2": [20.0, 70.0, "g_official"],
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            cfg = {
                "crop_family": "wheat",
                "params": {
                    "bounds": {"p1v": [5.0, 15.0, "g_custom"]},
                    "official_bounds_source": "config/official_bounds.json",
                    "fallback_mode": "relative_30",
                },
            }

            rows = build_pest_setup._prepare_parameter_bounds(cwd, project_root, cfg)

            self.assertEqual(cfg["params"]["bounds"]["p1v"], [5.0, 15.0, "g_custom"])
            self.assertEqual(cfg["params"]["bounds"]["g1"], [10.0, 35.0, "g_official"])
            self.assertEqual(cfg["params"]["bounds"]["g2"], [20.0, 70.0, "g_official"])
            rows_by_name = {str(row["parameter"]): row for row in rows}
            self.assertEqual(rows_by_name["g1"]["source"], "official")
            self.assertEqual(rows_by_name["g2"]["source"], "official")
            self.assertEqual(rows_by_name["g1"]["crop_family"], "wheat")
            self.assertTrue(str(rows_by_name["g1"]["official_source_path"]).endswith("official_bounds.json"))

    def test_prepare_parameter_bounds_preview_follows_registry_parameter_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = root / "run"
            project_root = root / "project"
            cwd.mkdir()
            (project_root / "work").mkdir(parents=True)
            (project_root / "work" / "params.dat").write_text(
                "wtpsd 0.200000\n"
                "ppsen 0.050000\n"
                "xfrt 0.700000\n"
                "sfdur 28.000000\n"
                "slavr 210.000000\n",
                encoding="utf-8",
            )
            cfg = {
                "crop_family": "sunflower",
                "params": {
                    "bounds": {
                        "wtpsd": [0.18, 0.24, "g_cul"],
                        "ppsen": [0.01, 0.10, "g_cul"],
                        "xfrt": [0.55, 0.90, "g_cul"],
                    },
                    "official_bounds": {
                        "sfdur": [20.0, 40.0, "g_official"],
                        "slavr": [170.0, 250.0, "g_official"],
                    },
                },
            }

            build_pest_setup._prepare_parameter_bounds(cwd, project_root, cfg)

            preview = pd.read_csv(cwd / "parameter_bounds_preview.csv")
            self.assertEqual(
                preview["parameter"].str.lower().tolist(),
                ["ppsen", "sfdur", "slavr", "wtpsd", "xfrt"],
            )

    def test_quality_gate_scripts_include_autoresearch_sandbox(self) -> None:
        lint_script = (ROOT / "scripts" / "lint.ps1").read_text(encoding="utf-8")
        typecheck_script = (ROOT / "scripts" / "typecheck.ps1").read_text(encoding="utf-8")

        self.assertIn('.venv\\Scripts\\python.exe', lint_script)
        self.assertIn('.venv\\Scripts\\python.exe', typecheck_script)
        self.assertIn('& $python -m ruff check src ..\\autoresearch_sandbox', lint_script)
        self.assertIn('& $python -m mypy src ..\\autoresearch_sandbox', typecheck_script)

    def test_pyproject_quality_gate_targets_include_autoresearch_sandbox(self) -> None:
        pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('src = ["src", "../autoresearch_sandbox"]', pyproject_text)
        self.assertIn('files = ["src", "../autoresearch_sandbox"]', pyproject_text)

    def test_run_eval_process_in_workspace_emits_heartbeat_callbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_heartbeat",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            workspace = Path(tmp)
            eval_path = workspace / "mini_eval.py"
            eval_path.write_text(
                "import time\n"
                "print('boot', flush=True)\n"
                "time.sleep(0.35)\n"
                "print('Final_Score: 0.25', flush=True)\n",
                encoding="utf-8",
            )
            heartbeat_events: list[float] = []

            result = auto_evolve_module.run_eval_process_in_workspace(
                eval_path,
                workspace,
                heartbeat_callback=lambda: heartbeat_events.append(time.time()),
                heartbeat_interval_sec=0.1,
            )

            self.assertGreaterEqual(len(heartbeat_events), 1)
            self.assertEqual(result.returncode, 0)
            self.assertAlmostEqual(result.score, 0.25)
            self.assertIn("Final_Score: 0.25", result.stdout)

    def test_recover_stale_worker_task_marks_state_and_clears_current_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_stale_recovery",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            batch_root = Path(tmp) / "batch"
            task_store = auto_evolve_module.TaskStore(batch_root)
            worker = auto_evolve_module.build_worker_pool(batch_root / "workers", 1)[0]
            task_dir = worker.tasks_dir / "task_000001"
            stale_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 120))

            auto_evolve_module.atomic_write_json(
                worker.heartbeat_path,
                {"worker_id": worker.worker_id, "status": "running", "timestamp": stale_timestamp},
            )
            task_store.write_current_task(
                worker.current_task_path,
                auto_evolve_module.TaskSpec(
                    task_id="task_000001",
                    batch_id="batch",
                    task_type="matrix_cell",
                    crop="wheat",
                    priority=1,
                    project_config_path="project.json",
                ),
            )
            task_store.write_task_state(
                task_dir,
                auto_evolve_module.TaskStateRecord(
                    task_id="task_000001",
                    state="running",
                    worker_id=worker.worker_id,
                    assigned_at="2026-04-04T00:00:00",
                    started_at="2026-04-04T00:00:01",
                ),
            )

            recovered = auto_evolve_module.recover_stale_worker_task(
                task_store,
                worker,
                task_dir,
                "task_000001",
                stale_timeout_sec=30,
                retry_count=1,
            )

            self.assertTrue(recovered)
            state_payload = json.loads((task_dir / "task_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state_payload["state"], "stale")
            self.assertEqual(state_payload["error_code"], "E_STALE")
            current_task_payload = json.loads(worker.current_task_path.read_text(encoding="utf-8"))
            self.assertEqual(current_task_payload, {})

    def test_execute_matrix_job_with_retry_persists_exception_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_retry_exception",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            batch_root = Path(tmp) / "batch"
            task_store = auto_evolve_module.TaskStore(batch_root)
            worker = auto_evolve_module.build_worker_pool(batch_root / "workers", 1)[0]
            job = auto_evolve_module.MatrixJob(
                index=1,
                weight=auto_evolve_module.WeightCandidate("W_TEST", "test", "w_test_mode", "strategy"),
                engine="pest_glm",
                budget="quick",
                sequence="s_test",
                grouping="g_test",
            )

            with patch.object(auto_evolve_module, "execute_matrix_job", side_effect=RuntimeError("boom")):
                result = auto_evolve_module.execute_matrix_job_with_retry(
                    job,
                    "phase-test",
                    "baseline",
                    0.5,
                    "hwam",
                    "strategy",
                    2,
                    worker_sandbox=worker,
                    task_store=task_store,
                    batch_id="batch-001",
                    retry_limit=0,
                )

            task_dir = worker.tasks_dir / "task_000001"
            state_payload = json.loads((task_dir / "task_state.json").read_text(encoding="utf-8"))
            result_payload = json.loads((task_dir / "task_result.json").read_text(encoding="utf-8"))
            current_task_payload = json.loads(worker.current_task_path.read_text(encoding="utf-8"))

            self.assertEqual(result.status, "crash")
            self.assertEqual(state_payload["state"], "failed_fatal")
            self.assertEqual(state_payload["error_code"], "E_EXEC")
            self.assertEqual(result_payload["status"], "crash")
            self.assertEqual(current_task_payload, {})
            self.assertEqual(result.batch_id, "batch-001")
            self.assertEqual(result.task_id, "task_000001")

    def test_execute_matrix_job_records_pending_sandbox_ready_and_collecting_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_execute_states",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            batch_root = Path(tmp) / "batch"
            task_store = auto_evolve_module.TaskStore(batch_root)
            worker = auto_evolve_module.build_worker_pool(batch_root / "workers", 1)[0]
            worker.root_dir.mkdir(parents=True, exist_ok=True)
            worker.sandbox_dir.mkdir(parents=True, exist_ok=True)
            worker.dssat_case_dir.mkdir(parents=True, exist_ok=True)
            runtime_dir = worker.sandbox_dir / "runs" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "run_manifest.json").write_text('{"status":"ok"}\n', encoding="utf-8")
            (runtime_dir / "contract_report.json").write_text('{"status":"ok"}\n', encoding="utf-8")

            job = auto_evolve_module.MatrixJob(
                index=1,
                weight=auto_evolve_module.WeightCandidate("W_TEST", "test", "w_test_mode", "strategy"),
                engine="pest_glm",
                budget="quick",
                sequence="s_test",
                grouping="g_test",
            )
            state_sequence: list[str] = []
            worker_status_sequence: list[str] = []
            original_write_task_state = task_store.write_task_state
            original_write_worker_status = auto_evolve_module.write_worker_status

            def capture_task_state(task_dir: Path, state: object) -> Path:
                state_sequence.append(state.state)
                return original_write_task_state(task_dir, state)

            def capture_worker_status(task_store_arg: object, worker_arg: object, **kwargs: object) -> Path:
                worker_status_sequence.append(str(kwargs.get("status", "")))
                return original_write_worker_status(task_store_arg, worker_arg, **kwargs)

            with (
                patch.object(task_store, "write_task_state", side_effect=capture_task_state),
                patch.object(auto_evolve_module, "write_worker_status", side_effect=capture_worker_status),
                patch.object(auto_evolve_module, "prepare_worker_task_runtime", return_value=None),
                patch.object(
                    auto_evolve_module,
                    "run_eval_process_in_workspace",
                    return_value=auto_evolve_module.EvalExecutionResult(
                        stdout="Final_Score: 0.1\n",
                        stderr="",
                        merged="Final_Score: 0.1\n",
                        score=0.1,
                        returncode=0,
                    ),
                ),
                patch.object(auto_evolve_module, "project_observation_bundle", return_value=([1], {1: "train"}, {})),
                patch.object(auto_evolve_module, "build_treatment_metric_rows", return_value=[]),
                patch.object(auto_evolve_module, "build_aggregate_metric_rows", return_value=[]),
                patch.object(auto_evolve_module, "project_crop_name", return_value="wheat"),
                patch.object(auto_evolve_module, "validate_matrix_combination", return_value=None),
                patch.object(auto_evolve_module, "validate_strategy_source", return_value=None),
            ):
                result = auto_evolve_module.execute_matrix_job(
                    job,
                    "phase-test",
                    "baseline",
                    0.5,
                    "HWAM",
                    "strategy",
                    1,
                    worker_sandbox=worker,
                    task_store=task_store,
                    batch_id="batch-001",
                    retry_index=0,
                )

            self.assertEqual(result.status, "ok")
            self.assertIn("pending", state_sequence)
            self.assertIn("sandbox_ready", state_sequence)
            self.assertIn("collecting", state_sequence)
            self.assertEqual(state_sequence[-1], "passed")
            self.assertIn("preparing", worker_status_sequence)
            self.assertIn("collecting", worker_status_sequence)
            self.assertEqual(worker_status_sequence[-1], "idle")

    def test_execute_matrix_job_with_retry_records_failed_retryable_before_retry_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_retry_states",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            batch_root = Path(tmp) / "batch"
            task_store = auto_evolve_module.TaskStore(batch_root)
            worker = auto_evolve_module.build_worker_pool(batch_root / "workers", 1)[0]
            job = auto_evolve_module.MatrixJob(
                index=1,
                weight=auto_evolve_module.WeightCandidate("W_TEST", "test", "w_test_mode", "strategy"),
                engine="pest_glm",
                budget="quick",
                sequence="s_test",
                grouping="g_test",
            )
            state_sequence: list[str] = []
            original_write_task_state = task_store.write_task_state

            def capture_task_state(task_dir: Path, state: object) -> Path:
                state_sequence.append(state.state)
                return original_write_task_state(task_dir, state)

            first = auto_evolve_module.build_matrix_result(
                run_id="run-001",
                weight=job.weight,
                engine=job.engine,
                budget=job.budget,
                sequence=job.sequence,
                grouping=job.grouping,
                score=999.0,
                status="crash",
                stdout="boom",
                negative_ref_profile="baseline",
                negative_ref_score=0.5,
                yield_metric="HWAM",
            )
            second = auto_evolve_module.build_matrix_result(
                run_id="run-002",
                weight=job.weight,
                engine=job.engine,
                budget=job.budget,
                sequence=job.sequence,
                grouping=job.grouping,
                score=0.1,
                status="ok",
                stdout="ok",
                negative_ref_profile="baseline",
                negative_ref_score=0.5,
                yield_metric="HWAM",
            )

            with (
                patch.object(task_store, "write_task_state", side_effect=capture_task_state),
                patch.object(auto_evolve_module, "execute_matrix_job", side_effect=[first, second]),
                patch.object(auto_evolve_module, "project_crop_name", return_value="wheat"),
            ):
                result = auto_evolve_module.execute_matrix_job_with_retry(
                    job,
                    "phase-test",
                    "baseline",
                    0.5,
                    "HWAM",
                    "strategy",
                    1,
                    worker_sandbox=worker,
                    task_store=task_store,
                    batch_id="batch-001",
                    retry_limit=1,
                )

            self.assertEqual(result.status, "ok")
            self.assertIn("failed_retryable", state_sequence)
            self.assertIn("retry_pending", state_sequence)
            self.assertLess(state_sequence.index("failed_retryable"), state_sequence.index("retry_pending"))

    def test_mark_task_result_aggregated_updates_task_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_mark_aggregated",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            batch_root = Path(tmp) / "batch"
            task_store = auto_evolve_module.TaskStore(batch_root)
            worker = auto_evolve_module.build_worker_pool(batch_root / "workers", 1)[0]
            task_dir = worker.tasks_dir / "task_000001"
            task_store.write_task_state(
                task_dir,
                auto_evolve_module.TaskStateRecord(
                    task_id="task_000001",
                    state="passed",
                    worker_id=worker.worker_id,
                    assigned_at="2026-04-04T00:00:00",
                    started_at="2026-04-04T00:00:01",
                    finished_at="2026-04-04T00:00:02",
                ),
            )
            result = auto_evolve_module.MatrixResult(
                run_id="run-1",
                weight_name="W_TEST",
                engine="pest_glm",
                budget="quick",
                sequence="s_test",
                grouping="g_test",
                score=0.1,
                status="ok",
                weight_mode="mode",
                stdout="ok",
                negative_ref_profile="baseline",
                negative_ref_score=0.5,
                train_mean_nrmse=0.1,
                valid_mean_nrmse=0.1,
                all_mean_nrmse=0.1,
                yield_metric="HWAM",
                train_yield_nrmse=0.1,
                train_yield_bias=0.0,
                valid_yield_nrmse=0.1,
                valid_yield_bias=0.0,
                batch_id="batch-1",
                batch_root=str(batch_root),
                task_id="task_000001",
                task_dir=str(task_dir),
                worker_id=worker.worker_id,
            )

            auto_evolve_module.mark_task_result_aggregated(result)

            state_payload = json.loads((task_dir / "task_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state_payload["state"], "aggregated")
            self.assertEqual(state_payload["worker_id"], worker.worker_id)

    def test_write_matrix_batch_report_copies_artifacts_and_records_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_batch_report",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            root = Path(tmp)
            batch_root = root / "batch"
            task_store = auto_evolve_module.TaskStore(batch_root)
            worker = auto_evolve_module.build_worker_pool(batch_root / "workers", 1)[0]
            task_dir = worker.tasks_dir / "task_000001"
            task_store.write_task_state(
                task_dir,
                auto_evolve_module.TaskStateRecord(
                    task_id="task_000001",
                    state="aggregated",
                    worker_id=worker.worker_id,
                ),
            )
            experiment_runs_path = root / "experiment_runs.tsv"
            experiment_summary_path = root / "experiment_summary.tsv"
            quality_gate_path = root / "quality_gate.tsv"
            paper_table_path = root / "paper_table.tsv"
            for path in (experiment_runs_path, experiment_summary_path, quality_gate_path, paper_table_path):
                path.write_text("header\nvalue\n", encoding="utf-8")
            results = [
                auto_evolve_module.MatrixResult(
                    run_id="run-1",
                    weight_name="W_TEST",
                    engine="pest_glm",
                    budget="quick",
                    sequence="s_test",
                    grouping="g_test",
                    score=0.1,
                    status="ok",
                    weight_mode="mode",
                    stdout="ok",
                    negative_ref_profile="baseline",
                    negative_ref_score=0.5,
                    train_mean_nrmse=0.1,
                    valid_mean_nrmse=0.1,
                    all_mean_nrmse=0.1,
                    yield_metric="HWAM",
                    train_yield_nrmse=0.1,
                    train_yield_bias=0.0,
                    valid_yield_nrmse=0.1,
                    valid_yield_bias=0.0,
                )
            ]
            quality_gate_rows = [{"gate_key": "paper_main_table_schema", "status": "fail"}]

            with (
                patch.object(auto_evolve_module, "EXPERIMENT_RUNS_TSV_PATH", experiment_runs_path),
                patch.object(auto_evolve_module, "EXPERIMENT_SUMMARY_TSV_PATH", experiment_summary_path),
                patch.object(auto_evolve_module, "MAIN_MATRIX_QUALITY_GATE_TSV_PATH", quality_gate_path),
                patch.object(auto_evolve_module, "MAIN_MATRIX_PAPER_TABLE_TSV_PATH", paper_table_path),
            ):
                report_path = auto_evolve_module.write_matrix_batch_report(
                    batch_root=batch_root,
                    batch_id="batch-001",
                    plan="phase-test",
                    results=results,
                    quality_gate_rows=quality_gate_rows,
                    report_outputs={"quality_gate": quality_gate_path, "paper_table": paper_table_path},
                    final_status="completed",
                )

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            aggregate_dir = batch_root / "aggregate"
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["task_state_counts"]["aggregated"], 1)
            self.assertEqual(payload["quality_gate"]["failing_gate_keys"], ["paper_main_table_schema"])
            self.assertTrue((aggregate_dir / experiment_runs_path.name).exists())
            self.assertTrue((aggregate_dir / quality_gate_path.name).exists())

    def test_resume_batch_recovers_completed_results_and_pending_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_resume_batch",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            batch_root = Path(tmp) / "batch"
            task_store = auto_evolve_module.TaskStore(batch_root)
            worker = auto_evolve_module.build_worker_pool(batch_root / "workers", 1)[0]
            batch_spec = auto_evolve_module.BatchSpec(
                batch_id="batch-001",
                batch_type="matrix",
                created_at="2026-04-04T00:00:00",
                project_root=str(batch_root),
                scheduler_config=auto_evolve_module.SchedulerConfig(task_parallelism=1),
                task_count=2,
                crop_set=["wheat"],
                quality_gate_mode="matrix",
                protocol_snapshot={"plan": "phase-test"},
                status="running",
            )
            task_store.write_batch_manifest(batch_spec)
            completed_task_dir = worker.tasks_dir / "task_000001"
            pending_task_dir = worker.tasks_dir / "task_000002"
            stdout_path = completed_task_dir / "stdout.txt"
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_path.write_text(
                "\n".join(
                    (
                        "Final_Score: 0.123",
                        "TRAIN_MEAN_NRMSE: 0.111",
                        "VALID_MEAN_NRMSE: 0.222",
                        "ALL_MEAN_NRMSE: 0.333",
                        "TRAIN_HWAM_NRMSE: 0.444",
                        "TRAIN_HWAM_BIAS: 1.000",
                        "VALID_HWAM_NRMSE: 0.555",
                        "VALID_HWAM_BIAS: 2.000",
                    )
                ),
                encoding="utf-8",
            )
            auto_evolve_module.atomic_write_json(
                completed_task_dir / "task_manifest.json",
                {
                    "task_id": "task_000001",
                    "protocol": {
                        "run_id": "run-001",
                        "plan": "phase-test",
                        "weight": "W_TEST",
                        "weight_mode": "test_mode",
                        "engine": "pest_glm",
                        "budget": "quick",
                        "sequence": "s_test",
                        "grouping": "g_test",
                    },
                },
            )
            auto_evolve_module.atomic_write_json(
                completed_task_dir / "task_result.json",
                {
                    "status": "ok",
                    "score": 0.123,
                    "duration_sec": 1.5,
                    "stdout_path": str(stdout_path),
                    "artifact_index": {"runtime_dir": str(completed_task_dir / "runtime")},
                },
            )
            task_store.write_task_state(
                completed_task_dir,
                auto_evolve_module.TaskStateRecord(
                    task_id="task_000001",
                    state="aggregated",
                    worker_id=worker.worker_id,
                    assigned_at="2026-04-04T00:00:01",
                    started_at="2026-04-04T00:00:02",
                    finished_at="2026-04-04T00:00:03",
                ),
            )
            task_store.write_task_state(
                pending_task_dir,
                auto_evolve_module.TaskStateRecord(
                    task_id="task_000002",
                    state="running",
                    worker_id=worker.worker_id,
                    assigned_at="2026-04-04T00:00:04",
                    started_at="2026-04-04T00:00:05",
                ),
            )
            jobs = [
                auto_evolve_module.MatrixJob(
                    index=1,
                    weight=auto_evolve_module.WeightCandidate("W_TEST", "test", "test_mode", None),
                    engine="pest_glm",
                    budget="quick",
                    sequence="s_test",
                    grouping="g_test",
                ),
                auto_evolve_module.MatrixJob(
                    index=2,
                    weight=auto_evolve_module.WeightCandidate("W_TEST_2", "test", "test_mode", None),
                    engine="pest_glm",
                    budget="quick",
                    sequence="s_test",
                    grouping="g_test",
                ),
            ]

            resolved_root, completed_results, pending_jobs, batch_id = auto_evolve_module.resume_batch(
                str(batch_root),
                jobs,
                negative_ref_profile="baseline",
                negative_ref_score=0.9,
                yield_metric="HWAM",
            )

            self.assertEqual(resolved_root, batch_root.resolve())
            self.assertEqual(batch_id, "batch-001")
            self.assertEqual(sorted(completed_results), [1])
            self.assertEqual([job.index for job in pending_jobs], [2])
            recovered = completed_results[1]
            self.assertEqual(recovered.task_id, "task_000001")
            self.assertEqual(recovered.status, "ok")
            self.assertAlmostEqual(recovered.valid_mean_nrmse, 0.222)
            self.assertAlmostEqual(recovered.valid_yield_nrmse, 0.555)

    def test_execute_matrix_jobs_with_worker_pool_resume_preserves_created_at_and_sets_aggregating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_resume_pool",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            batch_root = Path(tmp) / "batch"
            batch_root.mkdir(parents=True, exist_ok=True)
            task_store = auto_evolve_module.TaskStore(batch_root)
            original_created_at = "2026-04-04T08:00:00"
            task_store.write_batch_manifest(
                auto_evolve_module.BatchSpec(
                    batch_id="batch-001",
                    batch_type="matrix",
                    created_at=original_created_at,
                    project_root=str(batch_root),
                    scheduler_config=auto_evolve_module.SchedulerConfig(task_parallelism=1),
                    task_count=1,
                    crop_set=["wheat"],
                    quality_gate_mode="matrix",
                    protocol_snapshot={"plan": "phase-test"},
                    status="running",
                )
            )
            job = auto_evolve_module.MatrixJob(
                index=1,
                weight=auto_evolve_module.WeightCandidate("W_TEST", "test", "test_mode", None),
                engine="pest_glm",
                budget="quick",
                sequence="s_test",
                grouping="g_test",
            )
            fake_result = auto_evolve_module.MatrixResult(
                run_id="run-001",
                weight_name="W_TEST",
                engine="pest_glm",
                budget="quick",
                sequence="s_test",
                grouping="g_test",
                score=0.1,
                status="ok",
                weight_mode="test_mode",
                stdout="ok",
                negative_ref_profile="baseline",
                negative_ref_score=0.9,
                train_mean_nrmse=0.1,
                valid_mean_nrmse=0.1,
                all_mean_nrmse=0.1,
                yield_metric="HWAM",
                train_yield_nrmse=0.1,
                train_yield_bias=0.0,
                valid_yield_nrmse=0.1,
                valid_yield_bias=0.0,
                task_id="task_000001",
            )

            with (
                patch.object(auto_evolve_module, "initialize_worker_sandbox", side_effect=lambda worker, reset_root=True: worker),
                patch.object(auto_evolve_module, "monitor_worker_pool", return_value=None),
                patch.object(auto_evolve_module, "execute_matrix_job_with_retry", return_value=fake_result),
                patch.object(auto_evolve_module, "project_crop_name", return_value="wheat"),
            ):
                results, resolved_root, batch_id = auto_evolve_module.execute_matrix_jobs_with_worker_pool(
                    [job],
                    plan="phase-test",
                    negative_ref_profile="baseline",
                    negative_ref_score=0.9,
                    yield_metric="HWAM",
                    original_strategy="def calculate_loss():\n    return 0.0\n",
                    max_workers=1,
                    retry_limit=2,
                    batch_root_override=batch_root,
                    batch_id_override="batch-001",
                    resume=True,
                )

            manifest_payload = json.loads((batch_root / "batch_manifest.json").read_text(encoding="utf-8"))
            batch_state_payload = json.loads((batch_root / "batch_state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(results), 1)
            self.assertEqual(resolved_root, batch_root.resolve())
            self.assertEqual(batch_id, "batch-001")
            self.assertEqual(manifest_payload["created_at"], original_created_at)
            self.assertEqual(manifest_payload["status"], "aggregating")
            self.assertEqual(manifest_payload["scheduler_config"]["retry_limit"], 2)
            self.assertEqual(batch_state_payload["created_at"], original_created_at)
            self.assertEqual(batch_state_payload["status"], "aggregating")
            self.assertEqual(batch_state_payload["task_count"], 1)
            self.assertEqual(batch_state_payload["completed_task_count"], 1)
            self.assertEqual(batch_state_payload["pending_task_count"], 0)

    def test_resolve_scheduler_config_prefers_project_json_and_cli_overrides(self) -> None:
        sandbox_root = ROOT.parent / "autoresearch_sandbox"
        auto_evolve_module = load_module_from_path(
            "test_autoresearch_auto_evolve_scheduler_config",
            sandbox_root / "auto_evolve.py",
            extra_sys_path=[sandbox_root],
        )

        scheduler_config, source = auto_evolve_module.resolve_scheduler_config(
            {
                "scheduler": {
                    "task_parallelism": 3,
                    "crop_parallelism": 2,
                    "retry_limit": 4,
                    "heartbeat_interval_sec": 9,
                    "stale_timeout_sec": 120,
                    "sandbox_reuse": False,
                    "copy_case_once": False,
                    "aggregate_write_mode": "batched_writer",
                }
            },
            max_workers=5,
        )

        self.assertEqual(scheduler_config.task_parallelism, 5)
        self.assertEqual(scheduler_config.crop_parallelism, 2)
        self.assertEqual(scheduler_config.retry_limit, 4)
        self.assertEqual(scheduler_config.heartbeat_interval_sec, 9)
        self.assertEqual(scheduler_config.stale_timeout_sec, 120)
        self.assertFalse(scheduler_config.sandbox_reuse)
        self.assertFalse(scheduler_config.copy_case_once)
        self.assertEqual(scheduler_config.aggregate_write_mode, "batched_writer")
        self.assertEqual(source, "project_config+cli:max_workers")

    def test_parse_args_accepts_resume_batch_root_and_retry_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_parse_args_resume",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            batch_root = Path(tmp) / "batch"

            with patch.object(
                sys,
                "argv",
                [
                    "auto_evolve.py",
                    "--mode",
                    "matrix",
                    "--resume",
                    "--batch-root",
                    str(batch_root),
                    "--retry-limit",
                    "3",
                ],
            ):
                args = auto_evolve_module.parse_args()

            self.assertTrue(args.resume)
            self.assertEqual(args.batch_root, str(batch_root))
            self.assertEqual(args.retry_limit, 3)
            self.assertIsNone(args.max_workers)

    def test_monitor_worker_pool_marks_stale_task_and_requests_termination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = ROOT.parent / "autoresearch_sandbox"
            auto_evolve_module = load_module_from_path(
                "test_autoresearch_auto_evolve_monitor_pool",
                sandbox_root / "auto_evolve.py",
                extra_sys_path=[sandbox_root],
            )
            batch_root = Path(tmp) / "batch"
            task_store = auto_evolve_module.TaskStore(batch_root)
            worker = auto_evolve_module.build_worker_pool(batch_root / "workers", 1)[0]
            task_id = "task_000001"
            task_dir = worker.tasks_dir / task_id
            stale_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 120))

            auto_evolve_module.atomic_write_json(
                worker.heartbeat_path,
                {"worker_id": worker.worker_id, "status": "running", "timestamp": stale_timestamp},
            )
            task_store.write_current_task(
                worker.current_task_path,
                auto_evolve_module.TaskSpec(
                    task_id=task_id,
                    batch_id="batch",
                    task_type="matrix_cell",
                    crop="wheat",
                    priority=1,
                    project_config_path="project.json",
                ),
            )
            task_store.write_task_state(
                task_dir,
                auto_evolve_module.TaskStateRecord(
                    task_id=task_id,
                    state="running",
                    worker_id=worker.worker_id,
                    assigned_at="2026-04-04T00:00:00",
                    started_at="2026-04-04T00:00:01",
                    retry_count=2,
                ),
            )
            stop_event = auto_evolve_module.threading.Event()
            termination_calls: list[str] = []

            with patch.object(
                auto_evolve_module,
                "terminate_worker_process",
                side_effect=lambda worker_id: termination_calls.append(worker_id) or True,
            ):
                monitor_thread = auto_evolve_module.threading.Thread(
                    target=auto_evolve_module.monitor_worker_pool,
                    kwargs={
                        "task_store": task_store,
                        "worker_pool": [worker],
                        "stale_timeout_sec": 1,
                        "stop_event": stop_event,
                    },
                    daemon=True,
                )
                monitor_thread.start()
                time.sleep(1.2)
                stop_event.set()
                monitor_thread.join(timeout=2.0)

            state_payload = json.loads((task_dir / "task_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state_payload["state"], "stale")
            self.assertEqual(termination_calls, [worker.worker_id])


class TestCaseRuntimeResolution(unittest.TestCase):
    def test_resolve_case_dir_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = root / "work"
            project_root = root / "project"
            cwd.mkdir(parents=True, exist_ok=True)
            project_root.mkdir(parents=True, exist_ok=True)
            env_dir = root / "env_case"
            cfg_dir = root / "cfg_case"
            env_dir.mkdir(parents=True, exist_ok=True)
            cfg_dir.mkdir(parents=True, exist_ok=True)
            cfg = {"paths": {"dssat_case_dir": str(cfg_dir)}}

            self.assertEqual(
                resolve_case_dir(cwd, project_root, cfg, env_case_dir=str(env_dir), local_case_exists=True),
                env_dir.resolve(),
            )
            self.assertEqual(
                resolve_case_dir(cwd, project_root, cfg, env_case_dir="", local_case_exists=True),
                cfg_dir.resolve(),
            )
            self.assertEqual(
                resolve_case_dir(cwd, project_root, {}, env_case_dir="", local_case_exists=True),
                (cwd / "dssat_case").resolve(),
            )
            self.assertEqual(
                resolve_case_dir(cwd, project_root, {}, env_case_dir="", local_case_exists=False),
                (project_root / "data" / "dssat").resolve(),
            )

    def test_resolve_case_dir_supports_relative_cfg_dir_via_dssat_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = root / "work"
            project_root = root / "project"
            dssat_root = root / "portable_dssat"
            case_dir = dssat_root / "Wheat"
            cwd.mkdir(parents=True, exist_ok=True)
            project_root.mkdir(parents=True, exist_ok=True)
            case_dir.mkdir(parents=True, exist_ok=True)

            cfg = {"paths": {"dssat_root": str(dssat_root), "dssat_case_dir": "Wheat"}}

            self.assertEqual(
                resolve_case_dir(cwd, project_root, cfg, env_case_dir="", local_case_exists=False),
                case_dir.resolve(),
            )

    def test_resolve_runtime_root_uses_env_override_then_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = root / "project"
            project_root.mkdir(parents=True, exist_ok=True)
            runtime_env = root / "runtime_override"
            runtime_env.mkdir(parents=True, exist_ok=True)

            self.assertEqual(resolve_runtime_root(project_root, str(runtime_env)), runtime_env.resolve())
            self.assertEqual(resolve_runtime_root(project_root, ""), (project_root.parent / "local_dssat").resolve())

    def test_rewrite_cultivar_path_row_preserves_width_for_inp_and_inh(self) -> None:
        new_dir = "C:\\RT\\"
        inp_row = "CULTIVAR     WHCER048.CUL     C:\\DSSAT48\\Genotype\\                    "
        inh_row = "WHCER048.CUL                 C:\\DSSAT48\\Genotype\\                    "

        inp_out, inp_changed = rewrite_cultivar_path_row("DSSAT48.INP", inp_row, new_dir)
        inh_out, inh_changed = rewrite_cultivar_path_row("DSSAT48.INH", inh_row, new_dir)

        self.assertTrue(inp_changed)
        self.assertTrue(inh_changed)
        self.assertEqual(len(inp_out), len(inp_row))
        self.assertEqual(len(inh_out), len(inh_row))
        self.assertEqual(inp_out[inp_out.index("C:\\") : inp_out.index("C:\\") + len(new_dir)], new_dir)
        self.assertEqual(inh_out[inh_out.index("C:\\") : inh_out.index("C:\\") + len(new_dir)], new_dir)

    def test_parse_inp_cultivar_reference_extracts_file_and_dir(self) -> None:
        lines = [
            "SPECIES      WHCER048.SPE     C:\\DSSAT48\\Genotype\\",
            "CULTIVAR     WHCER048.CUL     C:\\DSSAT48\\Genotype\\",
        ]

        cul_name, cul_dir = parse_inp_cultivar_reference(lines)

        self.assertEqual(cul_name, "WHCER048.CUL")
        self.assertEqual(cul_dir, "C:\\DSSAT48\\Genotype\\")

    def test_infer_cul_path_from_inp_prefers_inp_source_path_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            genotype_dir = dssat_dir / "GENOTYPE"
            genotype_dir.mkdir(parents=True, exist_ok=True)
            local_cul = genotype_dir / "WHCER048.CUL"
            local_cul.write_text("LOCAL", encoding="utf-8")
            src_dir = dssat_dir / "src_genotype"
            src_dir.mkdir(parents=True, exist_ok=True)
            source_cul = src_dir / "WHCER048.CUL"
            source_cul.write_text("SOURCE", encoding="utf-8")
            (dssat_dir / "DSSAT48.INP").write_text(
                f"CULTIVAR     WHCER048.CUL     {str(src_dir)}\\\n",
                encoding="utf-8",
            )

            inferred = infer_cul_path_from_inp(dssat_dir, {})

            self.assertEqual(inferred, source_cul)

    def test_resolve_cultivar_path_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dssat_dir = root / "case"
            genotype_dir = dssat_dir / "GENOTYPE"
            dssat_dir.mkdir(parents=True, exist_ok=True)
            genotype_dir.mkdir(parents=True, exist_ok=True)
            local_cul = genotype_dir / "LOCAL.CUL"
            local_cul.write_text("LOCAL", encoding="utf-8")
            cfg_cul = root / "cfg" / "CFG.CUL"
            cfg_cul.parent.mkdir(parents=True, exist_ok=True)
            cfg_cul.write_text("CFG", encoding="utf-8")
            env_cul = root / "env" / "ENV.CUL"
            env_cul.parent.mkdir(parents=True, exist_ok=True)
            env_cul.write_text("ENV", encoding="utf-8")

            self.assertEqual(
                resolve_cultivar_path(dssat_dir, {"paths": {"cul_path": str(cfg_cul)}}, env_cul_path=str(env_cul)),
                env_cul,
            )
            self.assertEqual(
                resolve_cultivar_path(dssat_dir, {"paths": {"cul_path": str(cfg_cul)}}),
                local_cul,
            )

            local_cul.unlink()
            self.assertEqual(
                resolve_cultivar_path(dssat_dir, {"paths": {"cul_path": str(cfg_cul)}}),
                cfg_cul,
            )

    def test_resolve_cultivar_path_falls_back_to_crop_registry_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            maize_case = root / "Maize"
            cotton_case = root / "Cotton"
            portable_root = root / "portable_dssat"
            genotype_dir = portable_root / "Genotype"
            maize_case.mkdir(parents=True, exist_ok=True)
            cotton_case.mkdir(parents=True, exist_ok=True)
            genotype_dir.mkdir(parents=True, exist_ok=True)
            (genotype_dir / "MZCER048.CUL").write_text("MZ", encoding="utf-8")
            (genotype_dir / "COGRO048.CUL").write_text("CO", encoding="utf-8")

            self.assertEqual(
                resolve_cultivar_path(
                    maize_case,
                    {"crop_family": "maize", "paths": {"dssat_root": str(portable_root)}},
                    project_root=root,
                ),
                genotype_dir / "MZCER048.CUL",
            )
            self.assertEqual(
                resolve_cultivar_path(
                    cotton_case,
                    {"crop_family": "cotton", "paths": {"dssat_root": str(portable_root)}},
                    project_root=root,
                ),
                genotype_dir / "COGRO048.CUL",
            )

    def test_resolve_dssat_root_prefers_env_override_and_relative_exe_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = root / "project"
            env_root = root / "env_dssat"
            cfg_root = root / "cfg_dssat"
            project_root.mkdir(parents=True, exist_ok=True)
            env_root.mkdir(parents=True, exist_ok=True)
            cfg_root.mkdir(parents=True, exist_ok=True)
            (env_root / "DSCSM048.EXE").write_text("ENV", encoding="utf-8")
            (cfg_root / "DSCSM048.EXE").write_text("CFG", encoding="utf-8")

            cfg = {"paths": {"dssat_root": str(cfg_root), "dssat_exe": "DSCSM048.EXE"}}

            self.assertEqual(dssat_io.resolve_dssat_root(project_root, cfg=cfg), cfg_root.resolve())
            self.assertEqual(
                dssat_io.resolve_dssat_exe_path(project_root, cfg=cfg),
                cfg_root.resolve() / "DSCSM048.EXE",
            )
            self.assertEqual(
                dssat_io.resolve_dssat_root(project_root, cfg=cfg, env_dssat_root=str(env_root)),
                env_root.resolve(),
            )

    def test_scan_dssat_trials_resolves_cultivar_from_filex_trial_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            genotype_dir = root / "Genotype"
            genotype_dir.mkdir(parents=True, exist_ok=True)
            for cul_name in ("MZCER048.CUL", "COGRO048.CUL"):
                (genotype_dir / cul_name).write_text("GENOTYPE", encoding="utf-8")
            for crop_dir_name, stem, suffix in (
                ("Maize", "UFGA8201", "MZ"),
                ("Cotton", "UFGA8201", "CO"),
            ):
                crop_dir = root / crop_dir_name
                crop_dir.mkdir(parents=True, exist_ok=True)
                for ext in ("A", "T", "X"):
                    (crop_dir / f"{stem}.{suffix}{ext}").write_text(ext, encoding="utf-8")

            rows = dssat_io.scan_dssat_trials(root)
            rows_by_crop = {row["crop_dir"]: row for row in rows}

            self.assertEqual(set(rows_by_crop), {"Cotton", "Maize"})
            self.assertTrue(rows_by_crop["Maize"]["fileX"].endswith("UFGA8201.MZX"))
            self.assertTrue(rows_by_crop["Cotton"]["fileX"].endswith("UFGA8201.COX"))
            self.assertTrue(rows_by_crop["Maize"]["cul"].endswith("MZCER048.CUL"))
            self.assertTrue(rows_by_crop["Cotton"]["cul"].endswith("COGRO048.CUL"))

    def test_extract_filex_sections_and_cultivar_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            filex_path = Path(tmp) / "UFGA8201.MZX"
            filex_path.write_text(
                "\n".join(
                    [
                        "*EXP.DETAILS: MAIZE",
                        "*TREATMENTS                        -------------FACTOR LEVELS------------",
                        "@N R O C TNAME.................... CU FL SA IC MP MI MF MR MC MT ME MH SM",
                        " 1 1 0 0 MAIZE_TRT_1               1  1  0  0  0  0  0  0  0  0  0  0  0",
                        " 7 1 0 0 MAIZE_TRT_7               1  1  0  0  0  0  0  0  0  0  0  0  0",
                        "*CULTIVARS",
                        "@C CR INGENO CNAME",
                        " 1 MZ CVMZ01 MAIZE_TEST",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(dssat_io.extract_trts_from_filex(filex_path), [1, 7])
            self.assertEqual(dssat_io.extract_cultivar_code(filex_path), "CVMZ01")

    def test_rewrite_cul_values_preserves_target_row_width_and_other_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cul_path = Path(tmp) / "MZCER048.CUL"
            original_lines = [
                "*MAIZE CULTIVARS\n",
                "@VAR#  VRNAME........  EXPNO   ECO#    P1    P2    P5    G2    G3 PHINT\n",
                "CVMZ01 TEST_ENTRY_1         .   ECO1 240.0 0.50 780.0 650.0  8.5  45.0\n",
                "CVMZ02 TEST_ENTRY_2         .   ECO1 220.0 0.40 760.0 620.0  8.0  43.0\n",
            ]
            cul_path.write_text("".join(original_lines), encoding="utf-8")

            original_target = original_lines[2].rstrip("\n")
            original_other = original_lines[3]
            header_cols = [token.lstrip("@").strip().upper() for token in original_lines[1].split()]
            spans = {
                col: (match.start(), match.end())
                for col, match in zip(header_cols, re.finditer(r"\S+", original_target))
            }

            dssat_io.rewrite_cul_values(
                cul_path,
                "CVMZ01",
                {"P1": 245.0, "P2": 0.65, "G2": 700.0},
            )

            updated_lines = cul_path.read_text(encoding="utf-8").splitlines(keepends=True)
            updated_target = updated_lines[2].rstrip("\n")

            self.assertEqual(len(updated_target), len(original_target))
            self.assertEqual(updated_lines[3], original_other)
            self.assertEqual(updated_target[spans["P1"][0] : spans["P1"][1]].strip(), "245.0")
            self.assertEqual(updated_target[spans["P2"][0] : spans["P2"][1]].strip(), "0.65")
            self.assertEqual(updated_target[spans["G2"][0] : spans["G2"][1]].strip(), "700.0")

    def test_rewrite_cul_values_preserves_existing_decimal_precision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cul_path = Path(tmp) / "WHCER048.CUL"
            cul_path.write_text(
                "".join(
                    [
                        "*WHEAT CULTIVARS\n",
                        "@VAR#  VRNAME........  EXPNO   ECO#    P1V   P1D    P5   G1   G2   G3 PHINT\n",
                        "CVW01  TEST_ENTRY         .   ECO1   5.0  3.50 500.0 18.0 22.00 1.20  95.0\n",
                    ]
                ),
                encoding="utf-8",
            )

            dssat_io.rewrite_cul_values(
                cul_path,
                "CVW01",
                {"P1D": 4.25, "G2": 24.5, "G3": 1.75},
            )

            updated_row = cul_path.read_text(encoding="utf-8").splitlines()[2]
            tokens = updated_row.split()

            self.assertEqual(tokens[5], "4.25")
            self.assertEqual(tokens[8], "24.50")
            self.assertEqual(tokens[9], "1.750")

    def test_rewrite_cul_values_handles_vrname_with_spaces_without_column_shift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cul_path = Path(tmp) / "SBGRO048.CUL"
            cul_path.write_text(
                "".join(
                    [
                        "*SOYBEAN CULTIVARS\n",
                        "@VAR#  VAR-NAME........ EXPNO   ECO#  CSDL PPSEN EM-FL FL-SH FL-SD SD-PM FL-LF LFMAX SLAVR SIZLF  XFRT WTPSD SFDUR SDPDV PODUR THRSH SDPRO SDLIP\n",
                        "IB0002 COBB (8)             . SB0801 12.07 0.330  21.0   9.4  16.0 37.20 19.00 1.400   393 199.6  1.28 0.191  20.8  2.13   6.6  81.8  0.47  0.34\n",
                    ]
                ),
                encoding="utf-8",
            )

            dssat_io.rewrite_cul_values(cul_path, "IB0002", {"SLAVR": 387.5, "SDPDV": 2.2, "em_fl": 18.9})

            updated_row = cul_path.read_text(encoding="utf-8").splitlines()[2]
            self.assertIn("COBB (8)", updated_row)
            self.assertIn(" 388 ", updated_row)
            self.assertIn(" 2.20", updated_row)
            self.assertIn("18.9", updated_row)
            self.assertIn("1.400", updated_row)

    def test_parse_cul_header_and_row_handles_vrname_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cul_path = Path(tmp) / "COGRO048.CUL"
            cul_path.write_text(
                "".join(
                    [
                        "*COTTON CULTIVARS\n",
                        "@VAR#  VRNAME.......... EXPNO   ECO#  CSDL PPSEN EM-FL FL-SH FL-SD SD-PM FL-LF LFMAX SLAVR SIZLF  XFRT WTPSD SFDUR SDPDV PODUR THRSH SDPRO SDLIP\n",
                        "IB0001 Deltapine 77         2 CO0001 23.00  0.01  34.0   8.0  15.0 49.00 75.00  1.12   170 250.0  0.73 0.180  32.7 27.00    12  74.0  0.15  0.12\n",
                    ]
                ),
                encoding="utf-8",
            )

            cols, values = dssat_io._parse_cul_header_and_row(cul_path, "IB0001")

            self.assertIn("LFMAX", cols)
            self.assertIn("SLAVR", cols)
            self.assertAlmostEqual(values["LFMAX"], 1.12, places=6)
            self.assertAlmostEqual(values["SLAVR"], 170.0, places=6)
            self.assertAlmostEqual(values["SDPDV"], 27.0, places=6)

    def test_ensure_case_files_writes_registry_parameter_order_into_params_and_tpl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = root / "project"
            case_dir = root / "case"
            project_root.mkdir(parents=True, exist_ok=True)
            case_dir.mkdir(parents=True, exist_ok=True)
            cfg = {
                "crop_family": "sunflower",
                "paths": {"dssat_case_dir": str(case_dir)},
                "params": {
                    "bounds": {
                        "wtpsd": [0.18, 0.24, "g_cul"],
                        "ppsen": [0.01, 0.10, "g_cul"],
                        "xfrt": [0.55, 0.90, "g_cul"],
                        "sfdur": [20.0, 40.0, "g_cul"],
                        "slavr": [170.0, 250.0, "g_cul"],
                    }
                },
            }

            build_pest_setup._ensure_case_files(case_dir, project_root, cfg)

            params_lines = (case_dir / "params.dat").read_text(encoding="utf-8").splitlines()
            tpl_lines = (case_dir / "params.tpl").read_text(encoding="utf-8").splitlines()
            ordered_names = [line.split()[0].strip().lower() for line in params_lines if line.strip()]
            tpl_names = [line.split()[0].strip().lower() for line in tpl_lines[1:] if line.strip()]

            self.assertEqual(ordered_names, ["ppsen", "sfdur", "slavr", "wtpsd", "xfrt"])
            self.assertEqual(tpl_names, ordered_names)

    def test_resolve_wht_and_adapter_paths_map_relative_to_case_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            cfg = {
                "paths": {"obs_t_path": "OBS\\SWSW7501.WHT"},
                "adapter": {
                    "wth_updates": [{"date": 75001, "TMAX": 20.0}],
                    "sol_updates": [{"layer": 1, "SDUL": 0.22}],
                    "wth_path": "Weather\\TEST.WTH",
                    "sol_path": "Soil\\TEST.SOL",
                },
            }

            self.assertEqual(resolve_wht_path(dssat_dir, cfg), dssat_dir / "OBS" / "SWSW7501.WHT")
            wth_updates, sol_updates, wth_path, sol_path = resolve_adapter_paths(dssat_dir, cfg)

            self.assertEqual(wth_updates, cfg["adapter"]["wth_updates"])
            self.assertEqual(sol_updates, cfg["adapter"]["sol_updates"])
            self.assertEqual(wth_path, dssat_dir / "Weather" / "TEST.WTH")
            self.assertEqual(sol_path, dssat_dir / "Soil" / "TEST.SOL")

    def test_resolve_obs_a_path_prefers_env_then_filex_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dssat_dir = root / "case"
            dssat_dir.mkdir(parents=True, exist_ok=True)
            live_filex = dssat_dir / "SWSW7501.WHX"
            live_filex.write_text("*X", encoding="utf-8")

            env_path = resolve_obs_a_path(dssat_dir, {}, live_filex, env_obs_a_path="OBS\\ENV.WHA")
            fallback_path = resolve_obs_a_path(dssat_dir, {}, live_filex, env_obs_a_path="__skip__")

            self.assertEqual(env_path, dssat_dir / "OBS" / "ENV.WHA")
            self.assertEqual(fallback_path, dssat_dir / "SWSW7501.WHA")

    def test_resolve_primary_metric_codes_filters_by_obs_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a_path = Path(tmp) / "SWSW7501.WHA"
            a_path.write_text("*A\n@TRNO DATE HWAM\n 1 75001 1000\n", encoding="utf-8")

            yield_code, laix_code = resolve_primary_metric_codes({"yield_var": "YIELD", "laix_var": "LAIX"}, a_path)

            self.assertEqual(yield_code, "HWAM")
            self.assertEqual(laix_code, "")

    def test_build_pest_output_text_supports_single_and_multi_trt_layouts(self) -> None:
        single_text = build_pest_output_text({1: {"hwam": 123.4, "laix": 4.5}}, [1], "", ["HWAM", "LAIX"], {})
        multi_text = build_pest_output_text(
            {
                1: {"hwam": 123.4, "laid_d75001": 1.2, "lwad_d75001": 2.3},
                2: {"hwam": 140.0, "swad_d75002": 3.4},
            },
            [1, 2],
            "1,2",
            ["HWAM"],
            {1: [75001], 2: [75002]},
        )

        self.assertEqual(single_text, "hwam 123.400000 \nlaix 4.500000 \n")
        self.assertEqual(
            multi_text,
            "hwam_t01 123.400000 \n"
            "laid_t01_d75001 1.200000 \n"
            "lwad_t01_d75001 2.300000 \n"
            "hwam_t02 140.000000 \n"
            "swad_t02_d75002 3.400000 \n",
        )

    def test_result_schema_exposes_stable_output_naming_contract(self) -> None:
        context = result_schema.resolve_output_context(
            [1, 2],
            "1,2",
            ["HWAM", "LAIX"],
            {1: [75001], 2: [75002]},
        )
        records = result_schema.iter_pest_output_records(
            {
                1: {"hwam": 123.4, "laid_d75001": 1.2},
                2: {"laix": 5.6, "swad_d75002": 3.4},
            },
            context,
        )

        self.assertEqual(
            [(record.name, record.value) for record in records],
            [
                ("hwam_t01", 123.4),
                ("laid_t01_d75001", 1.2),
                ("laix_t02", 5.6),
                ("swad_t02_d75002", 3.4),
            ],
        )
        self.assertEqual(result_schema.build_summary_metric_name("HWAM", 3, single_treatment=False), "hwam_t03")
        self.assertEqual(result_schema.build_timeseries_metric_name("LAID", 4, 75012), "laid_t04_d75012")

    def test_resolve_metrics_cfg_prefers_metrics_then_variables(self) -> None:
        self.assertEqual(resolve_metrics_cfg({"metrics": {"yield_var": "HWAM"}}), {"yield_var": "HWAM"})
        self.assertEqual(resolve_metrics_cfg({"variables": {"yield_var": "CWAM"}}), {"yield_var": "CWAM"})
        self.assertEqual(resolve_metrics_cfg({}), {})

    def test_parse_var_codes_and_dedupe_codes_normalize_tokens(self) -> None:
        parsed = parse_var_codes(" hwam, laix; hwam  swad ")
        deduped = dedupe_codes(parsed)

        self.assertEqual(parsed, ["HWAM", "LAIX", "HWAM", "SWAD"])
        self.assertEqual(deduped, ["HWAM", "LAIX", "SWAD"])

    def test_resolve_summary_var_codes_includes_primary_and_extra(self) -> None:
        var_codes = resolve_summary_var_codes("HWAM", "", env_extra_summary_vars="laix, hwam; cwam")

        self.assertEqual(var_codes, ["HWAM", "LAIX", "CWAM"])

    def test_resolve_allow_missing_dates_prefers_env_true_else_cfg(self) -> None:
        self.assertTrue(resolve_allow_missing_dates({}, env_allow_missing="true"))
        self.assertTrue(resolve_allow_missing_dates({"observations": {"allow_missing_obs_files": True}}, env_allow_missing="0"))
        self.assertFalse(resolve_allow_missing_dates({}, env_allow_missing="0"))

    def test_resolve_t_vars_uses_configured_list_else_defaults(self) -> None:
        self.assertEqual(resolve_t_vars({"t_vars": ["laix", " lwad "]}), ["LAIX", "LWAD"])
        self.assertEqual(resolve_t_vars({"t_vars": []}), ["LAID", "LWAD", "SWAD"])
        self.assertEqual(resolve_t_vars({}), ["LAID", "LWAD", "SWAD"])

    def test_crop_registry_normalizes_aliases_and_trial_prefixes(self) -> None:
        self.assertEqual(dssat_io.resolve_crop_family({"crop_family": "WH"}), "wheat")
        self.assertEqual(dssat_io.resolve_crop_family({}, Path("Maize")), "maize")
        self.assertEqual(crop_registry.resolve_cultivar_file_by_trial_prefix("sb"), "SBGRO048.CUL")

    def test_resolve_parameter_names_uses_registry_priority_when_order_missing(self) -> None:
        self.assertEqual(dssat_io.resolve_parameter_names({"crop_family": "sunflower"}), ["ppsen", "sfdur", "slavr", "wtpsd", "xfrt"])

    def test_build_project_config_uses_registry_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_dir = root / "Wheat"
            case_dir.mkdir()
            file_a = case_dir / "TRIAL.WHA"
            file_t = case_dir / "TRIAL.WHT"
            file_x = case_dir / "TRIAL.WHX"
            file_a.write_text("*A", encoding="utf-8")
            file_t.write_text("*T", encoding="utf-8")
            file_x.write_text("*X", encoding="utf-8")

            cfg = dssat_io._build_project_config(
                "WH",
                file_a,
                file_t,
                file_x,
                None,
                [1, 2],
                {"p1v": 12.0},
                {"p1v": [5.0, 20.0, "g_cul"]},
                123,
            )

            self.assertEqual(cfg["crop_family"], "wheat")
            self.assertEqual(cfg["metrics"]["yield_var"], "HWAM")
            self.assertEqual(cfg["metrics"]["t_vars"], ["LAID", "LWAD", "SWAD"])
            self.assertIn("obs_yield", cfg["observations"]["groups"])

    def test_resolve_sh2o_updates_detects_family_and_applies_defaults(self) -> None:
        has_sh2o, updates = resolve_sh2o_updates({"sh2o_15": 0.19, "p1v": 12.0})
        has_none, empty_updates = resolve_sh2o_updates({"p1v": 12.0})

        self.assertTrue(has_sh2o)
        self.assertEqual(updates, {15: 0.19, 30: 0.17})
        self.assertFalse(has_none)
        self.assertEqual(empty_updates, {})

    def test_resolve_cul_updates_uses_cfg_param_list_and_param_map(self) -> None:
        params = {"p1v": 12.0, "g1": 25.0, "sh2o_15": 0.18}
        cfg = {"cul": {"params": ["P1V", " PHINT ", ""]}}
        param_map = {"phint": "g1"}

        cul_updates = resolve_cul_updates(params, cfg, param_map)

        self.assertEqual(cul_updates, {"p1v": 12.0, "g1": 25.0})

    def test_resolve_cul_updates_defaults_to_non_sh2o_params(self) -> None:
        params = {"p1v": 12.0, "g1": 25.0, "sh2o_15": 0.18}

        cul_updates = resolve_cul_updates(params, {}, {})

        self.assertEqual(cul_updates, {"p1v": 12.0, "g1": 25.0})

    def test_resolve_case_runtime_config_assembles_runtime_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a_path = Path(tmp) / "SWSW7501.WHA"
            a_path.write_text("*A\n@TRNO DATE HWAM LAIX\n 1 75001 1000 3.2\n", encoding="utf-8")

            runtime_cfg = resolve_case_runtime_config(
                {
                    "metrics": {"yield_var": "YIELD", "laix_var": "LAIX", "t_vars": ["laid", " swad "]},
                    "observations": {"allow_missing_obs_files": False},
                },
                a_path,
                {1: [75001], 2: [75002, 75003]},
                env_extra_summary_vars="cwam, hwam",
                env_allow_missing="true",
            )

            self.assertEqual(runtime_cfg.var_codes, ["HWAM", "LAIX", "CWAM"])
            self.assertEqual(runtime_cfg.t_vars, ["LAID", "SWAD"])
            self.assertTrue(runtime_cfg.allow_missing_dates)
            self.assertEqual(runtime_cfg.wht_dates_by_trt, {1: [75001], 2: [75002, 75003]})

    def test_resolve_case_runtime_config_handles_missing_obs_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a_path = Path(tmp) / "missing.WHA"

            runtime_cfg = resolve_case_runtime_config(
                {"variables": {"t_vars": []}, "observations": {"allow_missing_obs_files": True}},
                a_path,
                {},
                env_extra_summary_vars="",
                env_allow_missing="0",
            )

            self.assertEqual(runtime_cfg.var_codes, [])
            self.assertEqual(runtime_cfg.t_vars, ["LAID", "LWAD", "SWAD"])
            self.assertTrue(runtime_cfg.allow_missing_dates)
            self.assertEqual(runtime_cfg.wht_dates_by_trt, {})

    def test_read_wht_dates_by_trt_extracts_unique_sorted_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wht_path = Path(tmp) / "SWSW7501.WHT"
            wht_path.write_text(
                "*WHT\n"
                "@TRNO DATE LAID\n"
                " 1 75002 1.1\n"
                " 2 75003 2.2\n"
                " 1 75001 0.9\n"
                " 1 75002 1.1\n",
                encoding="utf-8",
            )

            dates_by_trt = read_wht_dates_by_trt(wht_path, [1, 2])

            self.assertEqual(dates_by_trt, {1: [75001, 75002], 2: [75003]})

    def test_resolve_observation_runtime_assembles_paths_and_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            obs_dir = dssat_dir / "OBS"
            obs_dir.mkdir(parents=True, exist_ok=True)
            live_filex = dssat_dir / "SWSW7501.WHX"
            live_filex.write_text("*X", encoding="utf-8")
            (dssat_dir / "SWSW7501.WHA").write_text("*A\n@TRNO DATE HWAM\n", encoding="utf-8")
            (obs_dir / "SWSW7501.WHT").write_text(
                "*WHT\n@TRNO DATE LAID\n 1 75002 1.1\n 2 75003 2.2\n",
                encoding="utf-8",
            )

            observation = resolve_observation_runtime(
                dssat_dir,
                {"paths": {"obs_t_path": "OBS\\SWSW7501.WHT"}},
                live_filex,
                [1, 2],
                env_obs_a_path="__skip__",
            )

            self.assertEqual(observation.obs_a_path, dssat_dir / "SWSW7501.WHA")
            self.assertEqual(observation.obs_wht_path, obs_dir / "SWSW7501.WHT")
            self.assertEqual(observation.wht_dates_by_trt, {1: [75002], 2: [75003]})

    def test_resolve_output_contract_assembles_summary_and_timeseries_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a_path = Path(tmp) / "SWSW7501.WHA"
            a_path.write_text("*A\n@TRNO DATE HWAM LAIX\n 1 75001 1000 3.1\n", encoding="utf-8")

            contract = resolve_output_contract(
                {
                    "metrics": {"yield_var": "YIELD", "laix_var": "LAIX", "t_vars": ["laid", "swad"]},
                    "observations": {"allow_missing_obs_files": False},
                },
                a_path,
                env_extra_summary_vars="cwam",
                env_allow_missing="true",
            )

            self.assertEqual(contract.var_codes, ["HWAM", "LAIX", "CWAM"])
            self.assertEqual(contract.t_vars, ["LAID", "SWAD"])
            self.assertTrue(contract.allow_missing_dates)

    def test_observations_module_resolves_observation_and_output_contracts_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            obs_dir = dssat_dir / "OBS"
            obs_dir.mkdir(parents=True, exist_ok=True)
            live_filex = dssat_dir / "SWSW7501.WHX"
            live_filex.write_text("*X", encoding="utf-8")
            (dssat_dir / "SWSW7501.WHA").write_text("*A\n@TRNO DATE HWAM LAIX\n", encoding="utf-8")
            (obs_dir / "SWSW7501.WHT").write_text(
                "*WHT\n@TRNO DATE LAID\n 1 75002 1.1\n 2 75003 2.2\n",
                encoding="utf-8",
            )

            observation, output = observations.resolve_observation_contracts(
                dssat_dir,
                {
                    "paths": {"obs_t_path": "OBS\\SWSW7501.WHT"},
                    "metrics": {"yield_var": "YIELD", "laix_var": "LAIX", "t_vars": ["laid", "swad"]},
                },
                live_filex,
                [1, 2],
                env_obs_a_path="__skip__",
                env_extra_summary_vars="cwam",
                env_allow_missing="true",
            )

            self.assertEqual(observation.obs_a_path, dssat_dir / "SWSW7501.WHA")
            self.assertEqual(observation.obs_wht_path, obs_dir / "SWSW7501.WHT")
            self.assertEqual(observation.wht_dates_by_trt, {1: [75002], 2: [75003]})
            self.assertEqual(output.var_codes, ["HWAM", "LAIX", "CWAM"])
            self.assertEqual(output.t_vars, ["LAID", "SWAD"])
            self.assertTrue(output.allow_missing_dates)

    def test_resolve_runtime_file_state_captures_original_texts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            live_filex = dssat_dir / "SWSW7501.WHX"
            cul_path = dssat_dir / "WHCER048.CUL"
            wth_path = dssat_dir / "TEST.WTH"
            sol_path = dssat_dir / "TEST.SOL"
            live_filex.write_text("FILEX", encoding="utf-8")
            cul_path.write_text("CUL", encoding="utf-8")
            wth_path.write_text("WTH", encoding="utf-8")
            sol_path.write_text("SOL", encoding="utf-8")

            file_state = resolve_runtime_file_state(
                live_filex,
                cul_path,
                resolve_input_plan(
                    dssat_dir,
                    {
                        "adapter": {
                            "wth_updates": [{"date": 75002, "TMAX": 20.0}],
                            "sol_updates": [{"layer": 1, "SDUL": 0.22}],
                            "wth_path": "TEST.WTH",
                            "sol_path": "TEST.SOL",
                        }
                    },
                    {},
                    {},
                ),
            )

            self.assertEqual(file_state.live_filex_original, "FILEX")
            self.assertEqual(file_state.cul_original, "CUL")
            self.assertEqual(file_state.wth_original, "WTH")
            self.assertEqual(file_state.sol_original, "SOL")

    def test_resolve_case_runtime_assembles_runtime_and_input_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            obs_dir = dssat_dir / "OBS"
            weather_dir = dssat_dir / "Weather"
            soil_dir = dssat_dir / "Soil"
            obs_dir.mkdir(parents=True, exist_ok=True)
            weather_dir.mkdir(parents=True, exist_ok=True)
            soil_dir.mkdir(parents=True, exist_ok=True)

            live_filex = dssat_dir / "SWSW7501.WHX"
            live_filex.write_text("*X", encoding="utf-8")
            (dssat_dir / "SWSW7501.WHA").write_text(
                "*A\n@TRNO DATE HWAM LAIX\n 1 75001 1000 3.0\n",
                encoding="utf-8",
            )
            (obs_dir / "SWSW7501.WHT").write_text(
                "*WHT\n@TRNO DATE LAID\n 1 75002 1.1\n 2 75003 2.2\n",
                encoding="utf-8",
            )
            (weather_dir / "TEST.WTH").write_text("*WTH", encoding="utf-8")
            (soil_dir / "TEST.SOL").write_text("*SOL", encoding="utf-8")

            runtime = resolve_case_runtime(
                dssat_dir,
                {
                    "paths": {"obs_t_path": "OBS\\SWSW7501.WHT"},
                    "metrics": {"yield_var": "YIELD", "laix_var": "LAIX", "t_vars": ["laid"]},
                    "observations": {"allow_missing_obs_files": False},
                    "adapter": {
                        "wth_updates": [{"date": 75002, "TMAX": 20.0}],
                        "sol_updates": [{"layer": 1, "SDUL": 0.22}],
                        "wth_path": "Weather\\TEST.WTH",
                        "sol_path": "Soil\\TEST.SOL",
                    },
                    "cul": {"params": ["P1V"]},
                },
                live_filex,
                [1, 2],
                {"p1v": 12.0, "sh2o_15": 0.19},
                {},
                env_obs_a_path="__skip__",
                env_extra_summary_vars="cwam",
                env_allow_missing="true",
            )

            self.assertEqual(runtime.observation.obs_a_path, dssat_dir / "SWSW7501.WHA")
            self.assertEqual(runtime.observation.obs_wht_path, obs_dir / "SWSW7501.WHT")
            self.assertEqual(runtime.output.var_codes, ["HWAM", "LAIX", "CWAM"])
            self.assertEqual(runtime.output.t_vars, ["LAID"])
            self.assertTrue(runtime.output.allow_missing_dates)
            self.assertEqual(runtime.observation.wht_dates_by_trt, {1: [75002], 2: [75003]})
            self.assertTrue(runtime.input_plan.has_sh2o)
            self.assertEqual(runtime.input_plan.sh2o_by_icbl, {15: 0.19, 30: 0.17})
            self.assertEqual(runtime.input_plan.cul_updates, {"p1v": 12.0})
            self.assertEqual(runtime.input_plan.wth_path, weather_dir / "TEST.WTH")
            self.assertEqual(runtime.input_plan.sol_path, soil_dir / "TEST.SOL")

    def test_resolve_observation_contracts_smoke_on_live_wheat_reference_files_if_present(self) -> None:
        dssat_dir = Path(r"C:\DSSAT48\Wheat")
        live_filex = dssat_dir / "SWSW7501.WHX"
        live_wha = dssat_dir / "SWSW7501.WHA"
        live_wht = dssat_dir / "SWSW7501.WHT"
        if not all(path.exists() for path in (live_filex, live_wha, live_wht)):
            self.skipTest("Live Wheat reference files are unavailable in the DSSAT root.")

        observation, output = resolve_observation_contracts(
            dssat_dir,
            {
                "paths": {
                    "wha_path": "SWSW7501.WHA",
                    "wht_path": "SWSW7501.WHT",
                },
                "metrics": {"yield_var": "HWAM", "laix_var": "LAIX", "t_vars": ["LAID"]},
                "observations": {"allow_missing_obs_files": False},
            },
            live_filex,
            [1, 2],
            env_extra_summary_vars="CWAM",
        )

        self.assertEqual(observation.obs_a_path, live_wha)
        self.assertEqual(observation.obs_wht_path, live_wht)
        self.assertEqual(observation.wht_dates_by_trt[1], [75167, 75174, 75192, 75204, 75233])
        self.assertEqual(observation.wht_dates_by_trt[2], [75167, 75174, 75192, 75204, 75233])
        self.assertEqual(output.var_codes, ["HWAM", "LAIX", "CWAM"])
        self.assertEqual(output.t_vars, ["LAID"])
        self.assertFalse(output.allow_missing_dates)

    def test_execute_treatment_merges_eval_summary_and_timeseries_metrics(self) -> None:
        runtime = CaseRuntime(
            observation=ObservationRuntime(
                obs_a_path=Path("SWSW7501.WHA"),
                obs_wht_path=Path("SWSW7501.WHT"),
                wht_dates_by_trt={2: [75002]},
            ),
            output=OutputContract(
                var_codes=["HWAM", "LAIX"],
                t_vars=["LAID", "SWAD"],
                allow_missing_dates=True,
            ),
            input_plan=CaseInputPlan(
                has_sh2o=False,
                sh2o_by_icbl={},
                cul_updates={},
                wth_updates=[],
                sol_updates=[],
                wth_path=None,
                sol_path=None,
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            def write_outputs(*args: object, **kwargs: object) -> None:
                (dssat_dir / "Summary.OUT").write_text("summary", encoding="utf-8")

            with (
                patch.object(run_model, "_run_dssat", side_effect=write_outputs) as run_dssat_mock,
                patch.object(run_model, "_extract_eval_metrics", return_value={"hwam": 123.4}),
                patch.object(run_model, "_extract_table_metrics", return_value={"laix": 4.5, "hwam": 999.0}),
                patch.object(
                    run_model,
                    "_extract_plantgro_vars_at_dates",
                    return_value={75002: {"laid": 1.2, "swad": 2.3}},
                ),
            ):
                metrics = run_model.execute_treatment(2, "SWSW7501.WHX", dssat_dir, {"paths": {}}, runtime)

            run_dssat_mock.assert_called_once_with("SWSW7501.WHX", 2, dssat_dir, {"paths": {}})
            self.assertEqual(
                metrics,
                {"hwam": 123.4, "laix": 4.5, "laid_d75002": 1.2, "swad_d75002": 2.3},
            )

    def test_execute_treatment_wraps_timeseries_runtime_error_with_trt(self) -> None:
        runtime = CaseRuntime(
            observation=ObservationRuntime(
                obs_a_path=Path("SWSW7501.WHA"),
                obs_wht_path=Path("SWSW7501.WHT"),
                wht_dates_by_trt={3: [75003]},
            ),
            output=OutputContract(
                var_codes=["HWAM"],
                t_vars=["LAID"],
                allow_missing_dates=False,
            ),
            input_plan=CaseInputPlan(
                has_sh2o=False,
                sh2o_by_icbl={},
                cul_updates={},
                wth_updates=[],
                sol_updates=[],
                wth_path=None,
                sol_path=None,
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            with (
                patch.object(run_model, "_run_dssat"),
                patch.object(run_model, "_extract_eval_metrics", return_value={"hwam": 123.4}),
                patch.object(run_model, "_extract_plantgro_vars_at_dates", side_effect=RuntimeError("missing date")),
            ):
                with self.assertRaisesRegex(RuntimeError, r"\[TRT 3\] missing date"):
                    run_model.execute_treatment(3, "SWSW7501.WHX", dssat_dir, {}, runtime)

    def test_execute_case_applies_plan_runs_all_trts_and_restores_files(self) -> None:
        runtime = CaseRuntime(
            observation=ObservationRuntime(
                obs_a_path=Path("SWSW7501.WHA"),
                obs_wht_path=Path("SWSW7501.WHT"),
                wht_dates_by_trt={},
            ),
            output=OutputContract(
                var_codes=["HWAM"],
                t_vars=["LAID"],
                allow_missing_dates=True,
            ),
            input_plan=CaseInputPlan(
                has_sh2o=True,
                sh2o_by_icbl={15: 0.19},
                cul_updates={"p1v": 12.0},
                wth_updates=[{"date": 75002, "TMAX": 20.0}],
                sol_updates=[{"layer": 1, "SDUL": 0.22}],
                wth_path=Path("TEST.WTH"),
                sol_path=Path("TEST.SOL"),
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            base = dssat_dir / "BASE.WHX"
            live_filex = dssat_dir / "LIVE.WHX"
            cul_path = dssat_dir / "WHCER048.CUL"
            wth_path = dssat_dir / "TEST.WTH"
            sol_path = dssat_dir / "TEST.SOL"
            base.write_text("BASE", encoding="utf-8")
            live_filex.write_text("LIVE_ORIGINAL", encoding="utf-8")
            cul_path.write_text("CUL_ORIGINAL", encoding="utf-8")
            wth_path.write_text("WTH_ORIGINAL", encoding="utf-8")
            sol_path.write_text("SOL_ORIGINAL", encoding="utf-8")

            runtime = CaseRuntime(
                observation=runtime.observation,
                output=runtime.output,
                input_plan=CaseInputPlan(
                    has_sh2o=True,
                    sh2o_by_icbl={15: 0.19},
                    cul_updates={"p1v": 12.0},
                    wth_updates=[{"date": 75002, "TMAX": 20.0}],
                    sol_updates=[{"layer": 1, "SDUL": 0.22}],
                    wth_path=wth_path,
                    sol_path=sol_path,
                ),
            )
            file_state = RuntimeFileState(
                live_filex_path=live_filex,
                live_filex_original="LIVE_ORIGINAL",
                cul_path=cul_path,
                cul_original="CUL_ORIGINAL",
                wth_path=wth_path,
                wth_original="WTH_ORIGINAL",
                sol_path=sol_path,
                sol_original="SOL_ORIGINAL",
            )

            def mutate_and_measure(trt: int, *args: object, **kwargs: object) -> dict[str, float]:
                live_filex.write_text(f"LIVE_{trt}", encoding="utf-8")
                cul_path.write_text(f"CUL_{trt}", encoding="utf-8")
                wth_path.write_text(f"WTH_{trt}", encoding="utf-8")
                sol_path.write_text(f"SOL_{trt}", encoding="utf-8")
                return {"hwam": float(trt)}

            with (
                patch.object(run_model, "rewrite_wth_daily") as rewrite_wth_mock,
                patch.object(run_model, "rewrite_sol_layers") as rewrite_sol_mock,
                patch.object(run_model, "rewrite_initial_sh2o") as rewrite_sh2o_mock,
                patch.object(run_model, "_rewrite_cul_params") as rewrite_cul_mock,
                patch.object(run_model, "execute_treatment", side_effect=mutate_and_measure) as execute_treatment_mock,
                patch.object(run_model, "_clear_output_files") as clear_outputs_mock,
            ):
                metrics_by_trt, treatment_calls = run_model.execute_case(
                    base,
                    live_filex,
                    cul_path,
                    "CV01",
                    "SWSW7501.WHX",
                    dssat_dir,
                    {"paths": {}},
                    [1, 2],
                    runtime,
                    file_state,
                    keep_outputs=False,
                )

            rewrite_wth_mock.assert_called_once_with(wth_path, runtime.input_plan.wth_updates)
            rewrite_sol_mock.assert_called_once_with(sol_path, runtime.input_plan.sol_updates)
            rewrite_sh2o_mock.assert_called_once_with(base, live_filex, runtime.input_plan.sh2o_by_icbl)
            rewrite_cul_mock.assert_called_once_with(cul_path, "CV01", runtime.input_plan.cul_updates)
            self.assertEqual(execute_treatment_mock.call_count, 2)
            self.assertEqual(clear_outputs_mock.call_count, 2)
            self.assertEqual(treatment_calls, 2)
            self.assertEqual(metrics_by_trt, {1: {"hwam": 1.0}, 2: {"hwam": 2.0}})
            self.assertEqual(live_filex.read_text(encoding="utf-8"), "LIVE_ORIGINAL")
            self.assertEqual(cul_path.read_text(encoding="utf-8"), "CUL_ORIGINAL")
            self.assertEqual(wth_path.read_text(encoding="utf-8"), "WTH_ORIGINAL")
            self.assertEqual(sol_path.read_text(encoding="utf-8"), "SOL_ORIGINAL")

    def test_execute_case_restores_files_after_treatment_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dssat_dir = Path(tmp)
            base = dssat_dir / "BASE.WHX"
            live_filex = dssat_dir / "LIVE.WHX"
            cul_path = dssat_dir / "WHCER048.CUL"
            base.write_text("BASE", encoding="utf-8")
            live_filex.write_text("LIVE_ORIGINAL", encoding="utf-8")
            cul_path.write_text("CUL_ORIGINAL", encoding="utf-8")

            runtime = CaseRuntime(
                observation=ObservationRuntime(
                    obs_a_path=Path("SWSW7501.WHA"),
                    obs_wht_path=None,
                    wht_dates_by_trt={},
                ),
                output=OutputContract(
                    var_codes=["HWAM"],
                    t_vars=["LAID"],
                    allow_missing_dates=True,
                ),
                input_plan=CaseInputPlan(
                    has_sh2o=False,
                    sh2o_by_icbl={},
                    cul_updates={},
                    wth_updates=[],
                    sol_updates=[],
                    wth_path=None,
                    sol_path=None,
                ),
            )
            file_state = RuntimeFileState(
                live_filex_path=live_filex,
                live_filex_original="LIVE_ORIGINAL",
                cul_path=cul_path,
                cul_original="CUL_ORIGINAL",
                wth_path=None,
                wth_original=None,
                sol_path=None,
                sol_original=None,
            )

            def raise_after_mutation(*args: object, **kwargs: object) -> dict[str, float]:
                live_filex.write_text("LIVE_MUTATED", encoding="utf-8")
                cul_path.write_text("CUL_MUTATED", encoding="utf-8")
                raise RuntimeError("boom")

            with (
                patch.object(run_model, "execute_treatment", side_effect=raise_after_mutation),
                patch.object(run_model, "_clear_output_files") as clear_outputs_mock,
            ):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    run_model.execute_case(
                        base,
                        live_filex,
                        cul_path,
                        "CV01",
                        "SWSW7501.WHX",
                        dssat_dir,
                        {},
                        [1],
                        runtime,
                        file_state,
                        keep_outputs=False,
                    )

            self.assertEqual(clear_outputs_mock.call_count, 2)
            self.assertEqual(live_filex.read_text(encoding="utf-8"), "LIVE_ORIGINAL")
            self.assertEqual(cul_path.read_text(encoding="utf-8"), "CUL_ORIGINAL")

    def test_prepare_case_run_assembles_runtime_context_for_cli_and_research(self) -> None:
        runtime = CaseRuntime(
            observation=ObservationRuntime(
                obs_a_path=Path("SWSW7501.WHA"),
                obs_wht_path=None,
                wht_dates_by_trt={},
            ),
            output=OutputContract(
                var_codes=["HWAM"],
                t_vars=["LAID"],
                allow_missing_dates=True,
            ),
            input_plan=CaseInputPlan(
                has_sh2o=False,
                sh2o_by_icbl={},
                cul_updates={},
                wth_updates=[],
                sol_updates=[],
                wth_path=None,
                sol_path=None,
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            dssat_dir = cwd / "case"
            dssat_dir.mkdir(parents=True, exist_ok=True)
            (cwd / "params.dat").write_text("P1V 12.0\n", encoding="utf-8")
            (dssat_dir / "CASE_base.WHX").write_text("BASE", encoding="utf-8")
            live_filex = dssat_dir / "CASE.WHX"
            live_filex.write_text("LIVE", encoding="utf-8")
            cul_path = dssat_dir / "WHCER048.CUL"
            cul_path.write_text("CUL", encoding="utf-8")
            file_state = RuntimeFileState(
                live_filex_path=live_filex,
                live_filex_original="LIVE",
                cul_path=cul_path,
                cul_original="CUL",
                wth_path=None,
                wth_original=None,
                sol_path=None,
                sol_original=None,
            )
            captured: dict[str, object] = {}

            def capture_runtime(
                dssat_dir_arg: Path,
                cfg_arg: dict,
                live_filex_arg: Path,
                trts_arg: list[int],
                params_arg: dict[str, float],
                param_map_arg: dict[str, str],
                **kwargs: object,
            ) -> CaseRuntime:
                captured["dssat_dir"] = dssat_dir_arg
                captured["cfg"] = cfg_arg
                captured["live_filex"] = live_filex_arg
                captured["trts"] = trts_arg
                captured["params"] = params_arg
                captured["param_map"] = param_map_arg
                captured["kwargs"] = kwargs
                return runtime

            with (
                patch.dict(
                    os.environ,
                    {
                        "DSSAT_TRTS": "3,4",
                        "DSSAT_KEEP_OUTPUTS": "true",
                        "DSSAT_OBS_A_PATH": "OBS\\SWSW7501.WHA",
                        "DSSAT_EXTRA_SUMMARY_VARS": "cwam",
                        "DSSAT_ALLOW_MISSING_WHT_DATES": "true",
                    },
                    clear=False,
                ),
                patch.object(
                    run_model,
                    "_load_project_config",
                    return_value={"scenario": {"filex": "CASE.WHX", "base_filex": "CASE_base.WHX"}},
                ),
                patch.object(run_model, "_choose_case_dir", return_value=dssat_dir),
                patch.object(run_model, "ensure_case_support_files"),
                patch.object(run_model, "resolve_param_mapping", return_value=({"p1v": "g1"}, {})),
                patch.object(run_model, "resolve_cultivar_path", return_value=cul_path),
                patch.object(run_model, "ensure_nonempty_cultivar_file"),
                patch.object(run_model, "infer_cul_path_from_inp", return_value=None),
                patch.object(run_model, "resolve_dssat_genotype_dir", return_value=Path(r"d:\tmp\runtime\GENOTYPE")),
                patch.object(
                    run_model,
                    "ensure_local_runtime",
                    return_value=(Path("DSCSM048.EXE"), Path(r"d:\tmp\runtime\GENOTYPE")),
                ),
                patch.object(run_model, "_extract_cultivar_code", return_value="CV01"),
                patch.object(run_model, "patch_cultivar_dir_in_inp_inh"),
                patch.object(run_model, "resolve_case_runtime", side_effect=capture_runtime),
                patch.object(run_model, "resolve_runtime_file_state", return_value=file_state),
            ):
                prepared = run_model.prepare_case_run(cwd)

            self.assertEqual(prepared.cfg["paths"]["dssat_exe"], "DSCSM048.EXE")
            self.assertEqual(prepared.dssat_dir, dssat_dir)
            self.assertEqual(prepared.filex_name, "CASE.WHX")
            self.assertEqual(prepared.trts, [3, 4])
            self.assertIs(prepared.case_runtime, runtime)
            self.assertIs(prepared.file_state, file_state)
            self.assertTrue(prepared.keep_outputs)
            self.assertEqual(prepared.base, dssat_dir / "CASE_base.WHX")
            self.assertEqual(prepared.live_filex, live_filex)
            self.assertEqual(prepared.cul_path, Path(r"d:\tmp\runtime\GENOTYPE\WHCER048.CUL"))
            self.assertEqual(prepared.cultivar_code, "CV01")
            self.assertEqual(prepared.trts_env, "3,4")
            self.assertEqual(captured["dssat_dir"], dssat_dir)
            self.assertEqual(captured["live_filex"], live_filex)
            self.assertEqual(captured["trts"], [3, 4])
            self.assertEqual(captured["params"], {"g1": 12.0})
            self.assertEqual(captured["param_map"], {"p1v": "g1"})
            self.assertEqual(
                captured["kwargs"],
                {
                    "env_obs_a_path": "OBS\\SWSW7501.WHA",
                    "env_extra_summary_vars": "cwam",
                    "env_allow_missing": "true",
                },
            )

    def test_prepare_case_run_accepts_project_config_alias_and_paths_filex_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            dssat_dir = cwd / "case"
            dssat_dir.mkdir(parents=True, exist_ok=True)
            live_filex = dssat_dir / "SWSW7501.WHX"
            live_filex.write_text("*X", encoding="utf-8")
            cul_path = dssat_dir / "WHCER048.CUL"
            cul_path.write_text("*C", encoding="utf-8")
            params_path = cwd / "params.dat"
            params_path.write_text("", encoding="utf-8")
            runtime = CaseRuntime(
                observation=ObservationRuntime(
                    obs_a_path=dssat_dir / "SWSW7501.WHA",
                    obs_wht_path=dssat_dir / "SWSW7501.WHT",
                    wht_dates_by_trt={},
                ),
                output=OutputContract(var_codes=["HWAM"], t_vars=[], allow_missing_dates=False),
                input_plan=CaseInputPlan(
                    has_sh2o=False,
                    sh2o_by_icbl={},
                    cul_updates={},
                    wth_updates=[],
                    sol_updates=[],
                    wth_path=None,
                    sol_path=None,
                ),
            )
            file_state = RuntimeFileState(
                live_filex_path=live_filex,
                live_filex_original="*X",
                cul_path=cul_path,
                cul_original="*C",
                wth_path=None,
                wth_original=None,
                sol_path=None,
                sol_original=None,
            )
            cfg_path = cwd / "project_live.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "paths": {
                            "dssat_case_dir": str(dssat_dir),
                            "live_filex": str(live_filex),
                            "base_filex": str(live_filex),
                        }
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.dict(os.environ, {"PEST_PROJECT_CONFIG": str(cfg_path), "DSSAT_TRTS": "1"}, clear=False),
                patch.object(run_model, "_choose_case_dir", return_value=dssat_dir),
                patch.object(run_model, "ensure_case_support_files"),
                patch.object(run_model, "resolve_param_mapping", return_value=({}, {})),
                patch.object(run_model, "resolve_cultivar_path", return_value=cul_path),
                patch.object(run_model, "ensure_nonempty_cultivar_file"),
                patch.object(run_model, "infer_cul_path_from_inp", return_value=None),
                patch.object(
                    run_model,
                    "ensure_local_runtime",
                    return_value=(Path("DSCSM048.EXE"), Path(r"d:\tmp\runtime\GENOTYPE")),
                ),
                patch.object(run_model, "_extract_cultivar_code", return_value="CV01"),
                patch.object(run_model, "patch_cultivar_dir_in_inp_inh"),
                patch.object(run_model, "resolve_case_runtime", return_value=runtime),
                patch.object(run_model, "resolve_runtime_file_state", return_value=file_state),
            ):
                prepared = run_model.prepare_case_run(cwd)

            self.assertEqual(prepared.base, live_filex)
            self.assertEqual(prepared.live_filex, live_filex)
            self.assertEqual(prepared.filex_name, "SWSW7501.WHX")


class TestPestBuilderRunner(unittest.TestCase):
    def test_write_pest_output_instruction_file_emits_summary_and_wht_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ins_path = Path(tmp) / "pest_out.ins"
            pest_builder.write_pest_output_instruction_file(
                ins_path,
                trts=[1, 3],
                summary_metrics=["HWAM", "CWAM"],
                wht_dates_by_trt={1: [75020]},
                wht_second="L#SM",
            )

            self.assertEqual(
                ins_path.read_text(encoding="utf-8").splitlines(),
                [
                    "pif ~",
                    "~hwam_t01~ !hwam_t01!",
                    "~cwam_t01~ !cwam_t01!",
                    "~laid_t01_d75020~ !laid_t01_d75020!",
                    "~l#sm_t01_d75020~ !l#sm_t01_d75020!",
                    "~hwam_t03~ !hwam_t03!",
                    "~cwam_t03~ !cwam_t03!",
                ],
            )

    def test_compute_group_weights_applies_max_mode_and_alpha_feedback(self) -> None:
        weights = pest_builder.compute_group_weights(
            group_defs={
                "obs_yield": {"weight": 1.0, "sigma": 2.0},
                "obs_canopy": {"weight": 4.0, "sigma": 5.0},
            },
            group_variances={"obs_yield": 9.0, "obs_canopy": 16.0},
            group_maxima={"obs_yield": 20.0, "obs_canopy": 10.0},
            group_rms=None,
            group_means_abs=None,
            weight_mode="w8_dssat_group_max",
            mgda_alphas={"obs_canopy": 0.5},
        )

        self.assertAlmostEqual(weights["obs_yield"], 0.05)
        self.assertAlmostEqual(weights["obs_canopy"], 0.1 * np.sqrt(0.5))

    def test_calibration_core_build_pst_applies_shared_contract(self) -> None:
        parameter_data = pd.DataFrame(
            {
                "parlbnd": [0.0, 0.0],
                "parubnd": [0.0, 0.0],
                "pargp": ["default", "default"],
                "partrans": ["none", "none"],
                "parval1": [10.0, 20.0],
            },
            index=["p1v", "g1"],
        )
        parameter_groups = pd.DataFrame(
            [
                {
                    "pargpnme": "default",
                    "inctyp": "relative",
                    "derinc": 0.01,
                    "derinclb": 0.0,
                    "forcen": "switch",
                    "derincmul": 2.0,
                    "dermthd": "parabolic",
                    "splitthresh": 1.0e-5,
                    "splitreldiff": 0.5,
                    "splitaction": "smaller",
                }
            ]
        )
        observation_data = pd.DataFrame(
            {
                "obsval": [0.0, 0.0, 0.0],
                "obgnme": ["", "", ""],
                "weight": [1.0, 1.0, 1.0],
            },
            index=["hwam_t01", "laid_t01_d75020", "hwam_t02"],
        )
        pst = SimpleNamespace(
            control_data=SimpleNamespace(noptmax=0, pestmode=""),
            pestpp_options={},
            parameter_data=parameter_data,
            parameter_groups=parameter_groups,
            observation_data=observation_data,
            model_command=[],
        )
        pyemu_module = SimpleNamespace(
            utils=SimpleNamespace(
                helpers=SimpleNamespace(
                    pst_from_io_files=lambda **_: pst,
                )
            )
        )

        built = core_pest_builder.build_pst(
            pyemu_module=pyemu_module,
            model_command='python "run_model.py"',
            noptmax=7,
            pst_bounds={"p1v": (5.0, 15.0, "phenology"), "g1": (10.0, 30.0, "yield")},
            params={"p1v": 12.0, "g1": 24.0},
            group_specs={"phenology": ("relative", 0.05)},
            group_defaults={
                "derinclb": 0.0,
                "forcen": "switch",
                "derincmul": 2.0,
                "dermthd": "parabolic",
                "splitthresh": 1.0e-5,
                "splitreldiff": 0.5,
                "splitaction": "smaller",
            },
            meas={"hwam_t01": 123.4, "laid_t01_d75020": 4.5},
            group_defs={"obs_yield": {}, "obs_canopy": {}},
            group_weights={"obs_yield": 0.25, "obs_canopy": 0.5},
            weights_overrides={},
            split_by_trt={2: "valid"},
            active_metrics={"hwam", "laid"},
            yield_prefix="hwam",
            laix_prefix="laix",
            resolve_obs_group_name=lambda oname, *_: "obs_yield" if oname.startswith("hwam") else "obs_canopy",
            extract_metric_from_obs_name=lambda oname: oname.split("_", 1)[0].lower(),
            extract_trt_from_obs_name=lambda oname: int(oname.split("_t", 1)[1].split("_", 1)[0]) if "_t" in oname else None,
            active_params={"p1v"},
            ies_num_reals=20,
            ies_subset_size=5,
        )

        self.assertIs(built, pst)
        self.assertEqual(built.model_command, ['python "run_model.py"'])
        self.assertEqual(built.control_data.noptmax, 7)
        self.assertEqual(built.control_data.pestmode, "estimation")
        self.assertEqual(built.pestpp_options["ies_num_reals"], 20)
        self.assertEqual(built.pestpp_options["ies_subset_size"], 5)
        self.assertEqual(built.pestpp_options["ies_save_binary"], False)
        self.assertEqual(built.parameter_data.loc["p1v", "pargp"], "phenology")
        self.assertEqual(built.parameter_data.loc["p1v", "parval1"], 12.0)
        self.assertEqual(built.parameter_data.loc["g1", "partrans"], "fixed")
        self.assertIn("phenology", built.parameter_groups.index)
        self.assertEqual(built.observation_data.loc["hwam_t01", "obsval"], 123.4)
        self.assertEqual(built.observation_data.loc["hwam_t01", "weight"], 0.25)
        self.assertEqual(built.observation_data.loc["laid_t01_d75020", "weight"], 0.5)
        self.assertEqual(built.observation_data.loc["hwam_t02", "weight"], 0.0)

    def test_pest_builder_wrapper_exports_shared_build_pst(self) -> None:
        self.assertIs(pest_builder.build_pst, core_pest_builder.build_pst)

    def test_resolve_pestpp_executable_prefers_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            override = root / "custom" / "pestpp-ies.exe"
            override.parent.mkdir(parents=True, exist_ok=True)
            override.write_text("", encoding="utf-8")

            resolved = pest_runner.resolve_pestpp_executable(
                "pestpp-ies.exe",
                root,
                env={"PESTPP_IES": str(override)},
            )

            self.assertEqual(resolved, override)

    def test_resolve_pestpp_executable_accepts_root_inferred_from_run_model_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inferred_root = root / "alt" / "mvp_pest_mgda"
            binary = inferred_root / "vendor" / "pestpp_5.2.16_iwin" / "bin" / "pestpp-glm.exe"
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("", encoding="utf-8")
            fake_python = inferred_root / ".venv" / "Scripts" / "python.exe"
            fake_python.parent.mkdir(parents=True, exist_ok=True)
            fake_python.write_text("", encoding="utf-8")

            resolved = pest_runner.resolve_pestpp_executable(
                "pestpp-glm.exe",
                root / "missing_root",
                env={"PEST_RUN_MODEL_PYTHON": str(fake_python)},
            )

            self.assertEqual(resolved, binary)

    def test_resolve_pestpp_executable_accepts_sibling_wheat_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_root = root / "Parallel_Exp" / "mvp_pest_mgda"
            sibling_root = root / "Parallel_Exp" / "Wheat" / "mvp_pest_mgda"
            binary = sibling_root / "vendor" / "pestpp_5.2.16_iwin" / "bin" / "pestpp-glm.exe"
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("", encoding="utf-8")

            resolved = pest_runner.resolve_pestpp_executable(
                "pestpp-glm.exe",
                base_root,
                env={},
            )

            self.assertEqual(resolved, binary)

    def test_run_pestpp_executable_uses_resolved_binary_and_runner_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work_dir = root / "work"
            work_dir.mkdir()
            executable = root / "bin" / "pestpp-ies.exe"
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("", encoding="utf-8")
            calls: list[tuple[list[str], Path, dict[str, str], str]] = []

            def fake_run_process(command, cwd, env, failure_label):
                calls.append((command, cwd, env, failure_label))
                return "ok"

            with patch.object(core_pest_runner, "run_process", side_effect=fake_run_process):
                result = core_pest_runner.run_pestpp_executable(
                    "pestpp-ies.exe",
                    root,
                    work_dir,
                    {"PEST_NOPTMAX": "2"},
                    pst_filename="custom_case.pst",
                )

            self.assertEqual(result, "ok")
            self.assertEqual(
                calls,
                [
                    (
                        [str(executable), "custom_case.pst"],
                        work_dir,
                        {"PEST_NOPTMAX": "2"},
                        "pestpp-ies execution",
                    )
                ],
            )

    def test_parse_best_glm_result_prefers_estimated_par_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp_est.par").write_text("P1V 12.5\nG1 88\n", encoding="utf-8")
            (work_dir / "ksas_mvp.par").write_text("P1V 99\n", encoding="utf-8")
            clipped_inputs: list[np.ndarray] = []

            def fake_clip(params: np.ndarray) -> np.ndarray:
                clipped_inputs.append(np.array(params, dtype=float))
                return np.array(params, dtype=float)

            params, phi = core_pest_runner.parse_best_glm_result(
                work_dir=work_dir,
                start_params=np.array([1.0, 2.0], dtype=float),
                param_names=["p1v", "g1"],
                clip_params=fake_clip,
            )

            self.assertTrue(np.allclose(params, np.array([12.5, 88.0], dtype=float)))
            self.assertTrue(np.isnan(phi))
            self.assertEqual(len(clipped_inputs), 1)

    def test_pest_runner_cli_run_subcommand_reuses_shared_binary_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp) / "work"
            pestpp_root = Path(tmp) / "root"
            work_dir.mkdir()
            pestpp_root.mkdir()
            captured: list[tuple[str, str, str, dict[str, str], str, str | None]] = []

            def fake_run(*, exe_name, pestpp_root, work_dir, env, pst_filename="ksas_mvp.pst", failure_label=None):
                captured.append((exe_name, pestpp_root, work_dir, dict(env), pst_filename, failure_label))
                return "ok"

            argv = [
                "pest_runner.py",
                "run",
                "--exe-name",
                "pestpp-glm.exe",
                "--pestpp-root",
                str(pestpp_root),
                "--work-dir",
                str(work_dir),
                "--pst-filename",
                "custom_case.pst",
            ]
            with patch.object(core_pest_runner, "run_pestpp_cli", side_effect=fake_run):
                with patch.object(sys, "argv", argv):
                    core_pest_runner.main()

            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0][0], "pestpp-glm.exe")
            self.assertEqual(captured[0][1], str(pestpp_root))
            self.assertEqual(captured[0][2], str(work_dir))
            self.assertEqual(captured[0][4], "custom_case.pst")
            self.assertIsNone(captured[0][5])

    def test_pest_builder_cli_run_subcommand_reuses_shared_builder_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp) / "work"
            work_dir.mkdir()
            captured: list[tuple[str, dict[str, str], str, str, str]] = []

            def fake_run(*, work_dir, env, python_executable=None, script_path=None, label=None):
                captured.append(
                    (
                        str(work_dir),
                        dict(env),
                        python_executable or "",
                        str(script_path or ""),
                        label or "",
                    )
                )
                return "ok"

            argv = [
                "pest_builder.py",
                "run",
                "--work-dir",
                str(work_dir),
                "--python-executable",
                "python-custom",
                "--script-path",
                str(work_dir / "custom_build.py"),
                "--label",
                "builder-cli",
            ]
            with patch.object(core_pest_builder, "run_build_pest_setup_cli", side_effect=fake_run):
                with patch.object(sys, "argv", argv):
                    core_pest_builder.main()

            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0][0], str(work_dir))
            self.assertEqual(captured[0][2], "python-custom")
            self.assertEqual(captured[0][3], str(work_dir / "custom_build.py"))
            self.assertEqual(captured[0][4], "builder-cli")

    def test_build_pest_setup_reuses_shared_run_model_helper(self) -> None:
        self.assertIs(build_pest_setup.run_model_with_params, core_pest_runner.run_model_with_params)
        self.assertIs(build_pest_setup.build_run_model_env, core_pest_runner.build_run_model_env)

    def test_runtime_modules_reuse_shared_protocol_artifact_builders(self) -> None:
        self.assertIs(run_model.build_run_manifest_payload, core_pest_runner.build_run_manifest_payload)
        self.assertIs(run_model.build_contract_report_payload, core_pest_runner.build_contract_report_payload)
        self.assertIs(run_model.resolve_protocol_options, core_pest_runner.resolve_protocol_options)
        self.assertIs(build_pest_setup.build_run_manifest_payload, core_pest_runner.build_run_manifest_payload)
        self.assertIs(build_pest_setup.build_contract_report_payload, core_pest_runner.build_contract_report_payload)
        self.assertIs(build_pest_setup.resolve_protocol_options, core_pest_runner.resolve_protocol_options)

    def test_result_schema_stable_entrypoints_are_reused_by_runtime_modules(self) -> None:
        self.assertIs(case_runtime.build_pest_output_text, result_schema.build_pest_output_text)
        self.assertIs(run_model.build_pest_output_text, result_schema.build_pest_output_text)

    def test_no_production_script_bypasses_stable_pest_entrypoints(self) -> None:
        allowed_paths = {
            SRC / "pest_builder.py",
            SRC / "result_schema.py",
            SRC / "calibration_core" / "pest_builder.py",
            SRC / "calibration_core" / "pest_runner.py",
            SRC / "calibration_core" / "result_schema.py",
        }
        target_roots = [SRC, ROOT.parent / "autoresearch_sandbox"]
        offenders: list[str] = []
        forbidden_tokens = (
            "from calibration_core.pest_builder import",
            "import calibration_core.pest_builder",
            "from calibration_core.pest_runner import",
            "import calibration_core.pest_runner",
            "from calibration_core.result_schema import",
            "import calibration_core.result_schema",
        )

        for target_root in target_roots:
            for path in target_root.rglob("*.py"):
                if path in allowed_paths or path.name.startswith("test_"):
                    continue
                text = path.read_text(encoding="utf-8")
                if any(token in text for token in forbidden_tokens):
                    offenders.append(str(path.relative_to(ROOT.parent)))

        self.assertEqual(offenders, [])

    def test_run_model_with_params_reuses_shared_python_entrypoint(self) -> None:
        captured: dict[str, object] = {}

        def fake_run_python_entrypoint(
            python_executable: str,
            script_path: Path,
            cwd: Path,
            env: dict[str, str],
            failure_label: str,
            args: list[str] | None = None,
        ) -> object:
            captured["python_executable"] = python_executable
            captured["script_path"] = script_path
            captured["cwd"] = cwd
            captured["env"] = dict(env)
            captured["failure_label"] = failure_label
            captured["args"] = list(args or [])
            return object()

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            params_path = work_dir / "params.dat"
            helper_path = work_dir / "run_model.py"
            with patch.object(core_pest_runner, "run_python_entrypoint", side_effect=fake_run_python_entrypoint):
                core_pest_runner.run_model_with_params(
                    work_dir,
                    params_path,
                    trts=[1, 3],
                    keep_outputs=True,
                    python_executable="python-custom",
                    run_model_path=helper_path,
                    extra_env={"EXTRA_FLAG": "1"},
                    failure_label="shared runner",
                )

            request_payload = json.loads(Path(captured["env"]["AR_RUNTIME_REQUEST_PATH"]).read_text(encoding="utf-8"))
            self.assertEqual(request_payload["purpose"], "run_model")
            self.assertEqual(request_payload["script_path"], str(helper_path))
            self.assertEqual(request_payload["env"]["PARAMS_PATH"], str(params_path))
            self.assertEqual(request_payload["env"]["DSSAT_TRTS"], "1,3")
            self.assertEqual(request_payload["env"]["DSSAT_KEEP_OUTPUTS"], "1")

        self.assertEqual(captured["python_executable"], "python-custom")
        self.assertEqual(captured["script_path"], helper_path)
        self.assertEqual(captured["cwd"], work_dir)
        self.assertEqual(captured["failure_label"], "shared runner")
        self.assertEqual(captured["env"]["EXTRA_FLAG"], "1")
        self.assertIn("AR_RUNTIME_REQUEST_PATH", captured["env"])
        self.assertEqual(captured["args"], ["--runtime-request", captured["env"]["AR_RUNTIME_REQUEST_PATH"]])

    def test_runtime_request_env_extracts_only_runtime_contract_keys(self) -> None:
        payload = core_pest_runner.extract_runtime_request_env(
            {
                "AR_WEIGHTING": "w0_raw_identity",
                "DSSAT_TRTS": "1,3",
                "PEST_NOPTMAX": 4,
                "MGDA_START_MODE": "grid",
                "PROJECT_CONFIG": r"d:\tmp\project.json",
                "CUL_PATH": r"d:\tmp\WHCER048.CUL",
                "PATH": r"C:\Windows\System32",
                "PYTHONPATH": r"d:\tmp\src",
                "EXTRA_FLAG": "1",
            }
        )

        self.assertEqual(
            payload,
            {
                "AR_WEIGHTING": "w0_raw_identity",
                "CUL_PATH": r"d:\tmp\WHCER048.CUL",
                "DSSAT_TRTS": "1,3",
                "MGDA_START_MODE": "grid",
                "PEST_NOPTMAX": "4",
                "PROJECT_CONFIG": r"d:\tmp\project.json",
            },
        )

    def test_build_run_model_env_populates_shared_runtime_contract(self) -> None:
        env = core_pest_runner.build_run_model_env(
            params_path=Path(r"d:\tmp\work\params.dat"),
            trts=[1, 3],
            keep_outputs=True,
            base_env={"PROJECT_CONFIG": r"d:\tmp\project.json", "DSSAT_TRTS": "9"},
            extra_env={"EXTRA_FLAG": 5},
            project_config_path=Path(r"d:\tmp\project_override.json"),
            case_dir=Path(r"d:\tmp\case"),
            cul_path=Path(r"d:\tmp\case\GENOTYPE\WHCER048.CUL"),
            extra_summary_vars=["cwam", " laix ", ""],
            allow_missing_wht_dates=True,
        )

        self.assertEqual(env["PARAMS_PATH"], r"d:\tmp\work\params.dat")
        self.assertEqual(env["DSSAT_TRTS"], "1,3")
        self.assertEqual(env["DSSAT_KEEP_OUTPUTS"], "1")
        self.assertEqual(env["PROJECT_CONFIG"], r"d:\tmp\project_override.json")
        self.assertEqual(env["DSSAT_CASE_DIR"], r"d:\tmp\case")
        self.assertEqual(env["CUL_PATH"], r"d:\tmp\case\GENOTYPE\WHCER048.CUL")
        self.assertEqual(env["WH_CUL_PATH"], r"d:\tmp\case\GENOTYPE\WHCER048.CUL")
        self.assertEqual(env["DSSAT_EXTRA_SUMMARY_VARS"], "cwam,laix")
        self.assertEqual(env["DSSAT_ALLOW_MISSING_WHT_DATES"], "1")
        self.assertEqual(env["EXTRA_FLAG"], "5")

    def test_run_manifest_and_contract_report_merge_json_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)

            core_pest_runner.write_run_manifest(
                work_dir,
                {
                    "run_id": "trial-001",
                    "protocol": {"weight": "w8"},
                    "paths": {"params_path": work_dir / "params.dat"},
                },
            )
            core_pest_runner.write_run_manifest(
                work_dir,
                {
                    "protocol": {"engine": "pestpp-ies"},
                    "results": {"score": 1.23},
                },
            )
            core_pest_runner.write_contract_report(
                work_dir,
                {
                    "status": "ok",
                    "issues": [],
                },
            )

            manifest = json.loads((work_dir / "run_manifest.json").read_text(encoding="utf-8"))
            contract = json.loads((work_dir / "contract_report.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["run_id"], "trial-001")
            self.assertEqual(manifest["protocol"]["weight"], "w8")
            self.assertEqual(manifest["protocol"]["engine"], "pestpp-ies")
            self.assertEqual(manifest["paths"]["params_path"], str(work_dir / "params.dat"))
            self.assertEqual(manifest["results"]["score"], 1.23)
            self.assertEqual(contract["status"], "ok")
            self.assertEqual(contract["issues"], [])

    def test_build_pest_setup_protocol_artifacts_write_manifest_and_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            dssat_dir = cwd / "case"
            dssat_dir.mkdir(parents=True, exist_ok=True)
            (cwd / "parameter_bounds_preview.csv").write_text(
                "parameter,lower,upper,group\nhwam,1.0,2.0,g_obs\n",
                encoding="utf-8",
            )
            filex_path = dssat_dir / "CASE.WHX"
            filex_path.write_text("FILEX", encoding="utf-8")
            a_path = cwd / "OBS.WHA"
            a_path.write_text("", encoding="utf-8")
            wht_path = cwd / "OBS.WHT"

            with patch.dict(
                os.environ,
                {
                    "AR_RUN_ID": "setup-001",
                    "AR_WEIGHTING": "w8",
                    "AR_GROUPING": "phenology",
                },
                clear=False,
            ):
                build_pest_setup._write_build_setup_protocol_artifacts(
                    cwd=cwd,
                    project_root=ROOT,
                    cfg={"crop_family": "wheat"},
                    dssat_dir=dssat_dir,
                    filex_path=filex_path,
                    trts=[1, 2],
                    requested_summary_metrics=["HWAM", "LAIX"],
                    resolved_summary_metrics=["HWAM"],
                    requested_t_vars=["LAID"],
                    split_by_trt={1: "train", 2: "valid"},
                    weight_mode="w1_inverse_variance",
                    active_metrics={"hwam", "laid"},
                    allow_missing_obs_files=False,
                    a_path=a_path,
                    wht_path=wht_path,
                    wht_dates_by_trt={},
                    meas={"hwam_t01": 100.0, "laix_t01": 3.0, "laix_t02": 4.0},
                    group_defs={
                        "obs_yield": {"patterns": ["hwam_"], "weight": 1.0, "sigma": 2.0},
                        "obs_canopy": {"patterns": ["laix_"], "weight": 1.0, "sigma": 0.0},
                        "obs_biomass": {"patterns": ["cwam_"], "weight": 1.0, "sigma": 1.0},
                    },
                    group_variances={"obs_yield": float("nan"), "obs_canopy": float("nan")},
                    group_maxima={},
                    group_weights={"obs_yield": 1.0, "obs_canopy": 0.0},
                    weights_overrides={"hwam_t01": 0.0},
                    yield_prefix="hwam",
                    laix_prefix="laix",
                    observation_count=7,
                )

            manifest = json.loads((cwd / "run_manifest.json").read_text(encoding="utf-8"))
            contract = json.loads((cwd / "contract_report.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["run_id"], "setup-001")
            self.assertEqual(manifest["protocol"]["split"]["assignments"]["2"], "valid")
            self.assertEqual(manifest["execution"]["cwd"], str(cwd))
            self.assertEqual(manifest["paths"]["bounds_preview_path"], str(cwd / "parameter_bounds_preview.csv"))
            self.assertEqual(manifest["observations"]["requested_t_vars"], ["LAID"])
            self.assertEqual(contract["status"], "degraded")
            self.assertEqual(contract["protocol"]["weight_mode"], "w1_inverse_variance")
            self.assertEqual(contract["paths"]["bounds_preview_path"], str(cwd / "parameter_bounds_preview.csv"))
            self.assertEqual(contract["summary"]["active_groups"], ["obs_yield"])
            self.assertEqual(contract["summary"]["active_metric_count"], 1)
            self.assertEqual(contract["summary"]["active_observation_count"], 7)
            self.assertEqual(contract["summary"]["fallback_metrics"], ["LAIX"])
            self.assertEqual(contract["summary"]["dropped_group_count"], 2)
            self.assertEqual(contract["summary"]["weight_fallback_count"], 2)
            self.assertEqual(contract["summary"]["zero_weight_observation_count"], 3)
            self.assertEqual(
                contract["dropped_groups"],
                [
                    {"group": "obs_biomass", "reason": "no_train_observations"},
                    {"group": "obs_canopy", "reason": "non_positive_group_weight"},
                ],
            )
            self.assertEqual(
                contract["weight_fallbacks"],
                [
                    {
                        "group": "obs_canopy",
                        "reason": "variance_and_sigma_unavailable_used_configured_weight",
                        "configured_weight": 1.0,
                        "applied_weight": 0.0,
                    },
                    {
                        "group": "obs_yield",
                        "reason": "variance_unavailable_used_sigma",
                        "sigma": 2.0,
                        "applied_weight": 1.0,
                    },
                ],
            )
            self.assertEqual(
                contract["zero_weight_observations"],
                [
                    {
                        "obs_name": "hwam_t01",
                        "group": "obs_yield",
                        "metric": "hwam",
                        "reason": "explicit_weight_override",
                        "trt": 1,
                    },
                    {
                        "obs_name": "laix_t01",
                        "group": "obs_canopy",
                        "metric": "laix",
                        "reason": "inactive_metric",
                        "trt": 1,
                    },
                    {
                        "obs_name": "laix_t02",
                        "group": "obs_canopy",
                        "metric": "laix",
                        "reason": "validation_split",
                        "trt": 2,
                    },
                ],
            )
            self.assertEqual(contract["summary"]["resolved_output_context"]["wht_observation_file_present"], False)
            self.assertTrue(contract["summary"]["resolved_output_context"]["parameter_bounds_preview_present"])
            self.assertEqual(
                [issue["code"] for issue in contract["issues"]],
                ["missing_summary_metrics", "missing_wht_observations"],
            )

    def test_run_model_main_writes_manifest_and_contract_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            dssat_dir = cwd / "case"
            dssat_dir.mkdir(parents=True, exist_ok=True)
            (cwd / "parameter_bounds_preview.csv").write_text(
                "parameter,lower,upper,group\np1v,10.0,16.0,g_cul\n",
                encoding="utf-8",
            )
            (cwd / "OBS.WHT").write_text("", encoding="utf-8")
            runtime = CaseRuntime(
                observation=ObservationRuntime(
                    obs_a_path=cwd / "OBS.WHA",
                    obs_wht_path=cwd / "OBS.WHT",
                    wht_dates_by_trt={1: [75020]},
                ),
                output=OutputContract(
                    var_codes=["HWAM"],
                    t_vars=["LAID"],
                    allow_missing_dates=True,
                ),
                input_plan=CaseInputPlan(
                    has_sh2o=False,
                    sh2o_by_icbl={},
                    cul_updates={},
                    wth_updates=[],
                    sol_updates=[],
                    wth_path=None,
                    sol_path=None,
                ),
            )
            base = dssat_dir / "CASE_base.WHX"
            base.write_text("BASE", encoding="utf-8")
            live_filex = dssat_dir / "CASE.WHX"
            live_filex.write_text("LIVE", encoding="utf-8")
            (dssat_dir / "Summary.OUT").write_text("SUMMARY", encoding="utf-8")
            (dssat_dir / "PlantGro.OUT").write_text("PLANTGRO", encoding="utf-8")
            cul_path = dssat_dir / "WHCER048.CUL"
            cul_path.write_text("CUL", encoding="utf-8")
            file_state = RuntimeFileState(
                live_filex_path=live_filex,
                live_filex_original="LIVE",
                cul_path=cul_path,
                cul_original="CUL",
                wth_path=None,
                wth_original=None,
                sol_path=None,
                sol_original=None,
            )
            prepared = run_model.PreparedCaseRun(
                cfg={
                    "crop_family": "wheat",
                    "metrics": {"yield_var": "HWAM", "laix_var": "", "t_vars": ["LAID"]},
                    "paths": {"dssat_exe": "DSCSM048.EXE"},
                },
                project_config_path=ROOT / "config" / "project.json",
                dssat_dir=dssat_dir,
                filex_name="CASE.WHX",
                trts=[1],
                case_runtime=runtime,
                file_state=file_state,
                keep_outputs=True,
                base=base,
                live_filex=live_filex,
                cul_path=cul_path,
                cultivar_code="CV01",
                trts_env="1",
            )

            with (
                patch.object(run_model, "prepare_case_run", return_value=prepared),
                patch.object(run_model, "execute_case", return_value=({1: {"hwam": 123.0}}, 1)),
                patch.object(run_model.Path, "cwd", return_value=cwd),
            ):
                run_model.main()

            manifest = json.loads((cwd / "run_manifest.json").read_text(encoding="utf-8"))
            contract = json.loads((cwd / "contract_report.json").read_text(encoding="utf-8"))
            pest_out = (cwd / "pest_out.dat").read_text(encoding="utf-8")

            self.assertEqual(manifest["crop"], "wheat")
            self.assertEqual(manifest["scenario"]["trts"], [1])
            self.assertEqual(manifest["scenario"]["base_filex_name"], "CASE_base.WHX")
            self.assertEqual(manifest["execution"]["cwd"], str(cwd))
            self.assertEqual(manifest["paths"]["bounds_preview_path"], str(cwd / "parameter_bounds_preview.csv"))
            self.assertEqual(manifest["paths"]["cul_path"], str(cul_path))
            self.assertEqual(manifest["paths"]["pest_output_path"], str(cwd / "pest_out.dat"))
            self.assertEqual(manifest["resolved_output"]["summary_metrics"], ["HWAM"])
            self.assertEqual(sorted(manifest["resolved_output"]["available_output_files"]), ["PlantGro.OUT", "Summary.OUT"])
            self.assertEqual(manifest["results"]["metrics_by_trt"]["1"]["hwam"], 123.0)
            self.assertEqual(contract["status"], "ok")
            self.assertTrue(contract["protocol"]["keep_outputs"])
            self.assertEqual(contract["summary"]["issue_count"], 0)
            self.assertTrue(contract["summary"]["parameter_bounds_preview_present"])
            self.assertEqual(contract["paths"]["bounds_preview_path"], str(cwd / "parameter_bounds_preview.csv"))
            self.assertEqual(contract["resolved"]["t_vars"], ["LAID"])
            self.assertIn("hwam_t01", pest_out)

    def test_run_compare_model_reuses_shared_runner_and_output_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            params_path = work_dir / "params.dat"
            params_path.write_text("p1v 10.0\n", encoding="utf-8")
            captured: dict[str, object] = {}

            def fake_run_model_with_params(
                work_dir: Path,
                params_path: Path,
                trts: list[int] | None = None,
                keep_outputs: bool = False,
                python_executable: str | None = None,
                run_model_path: Path | None = None,
                extra_env: dict[str, str] | None = None,
                failure_label: str = "run_model.py",
            ) -> object:
                captured["work_dir"] = work_dir
                captured["params_path"] = params_path
                captured["trts"] = list(trts or [])
                captured["keep_outputs"] = keep_outputs
                captured["failure_label"] = failure_label
                (work_dir / "pest_out.dat").write_text("HWAM 321.0\n", encoding="utf-8")
                return object()

            with patch.object(core_pest_runner, "run_model_with_params", side_effect=fake_run_model_with_params):
                result = core_pest_runner.run_compare_model(
                    work_dir=work_dir,
                    params_path=params_path,
                    trts=[1, 3],
                    keep_outputs=False,
                    failure_label="compare helper",
                )

            self.assertEqual(result, {"hwam": 321.0})
            self.assertEqual(captured["work_dir"], work_dir)
            self.assertEqual(captured["params_path"], params_path)
            self.assertEqual(captured["trts"], [1, 3])
            self.assertEqual(captured["keep_outputs"], False)
            self.assertEqual(captured["failure_label"], "compare helper")

    def test_read_key_value_output_skips_comments_and_bad_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "pest_out.dat"
            output_path.write_text(
                "* header\n! comment\nHWAM 123.4\nBAD value\nLAIX 5.6\n",
                encoding="utf-8",
            )

            parsed = pest_runner.read_key_value_output(output_path, comment_prefixes=("*", "!"))

            self.assertEqual(parsed, {"hwam": 123.4, "laix": 5.6})

    def test_materialize_params_dat_converts_par_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "ksas_mvp_est.par"
            target_path = root / "params.dat"
            source_path.write_text(
                "! header\n"
                "single point parameter file\n"
                "P1V 12.5\n"
                "G1 bad\n"
                "PHINT 95\n",
                encoding="utf-8",
            )

            result_path = pest_runner.materialize_params_dat(source_path, target_path)

            self.assertEqual(result_path, target_path)
            self.assertEqual(target_path.read_text(encoding="utf-8"), "p1v 12.5\nphint 95.0\n")

    def test_materialize_params_dat_copies_non_par_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "params_mgda.dat"
            target_path = root / "params.dat"
            source_path.write_text("p1v 11.0\n", encoding="utf-8")

            result_path = pest_runner.materialize_params_dat(source_path, target_path)

            self.assertEqual(result_path, target_path)
            self.assertEqual(target_path.read_text(encoding="utf-8"), "p1v 11.0\n")

    def test_resolve_compare_param_files_uses_standard_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            project_root = work_dir / "project"

            resolved = pest_runner.resolve_compare_param_files("standard", work_dir, project_root)

            self.assertEqual(
                resolved,
                {
                    "baseline": work_dir / "params_baseline.dat",
                    "pest": work_dir / "ksas_mvp_est.par",
                    "mgda": work_dir / "params_mgda.dat",
                },
            )

    def test_resolve_compare_param_files_uses_tournament_and_progress_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work_dir = root / "work"
            project_root = root / "project"
            env = {
                "TOURNAMENT_BASELINE": str(root / "baseline.dat"),
                "TOURNAMENT_PEST": str(root / "final_pest.dat"),
                "TOURNAMENT_MGDA": str(root / "final_mgda.dat"),
                "MGDA_PARAMS_PATH": str(root / "progress_mgda.dat"),
            }

            tournament = pest_runner.resolve_compare_param_files("tournament", work_dir, project_root, env=env)
            progress = pest_runner.resolve_compare_param_files("progress", work_dir, project_root, env=env)

            self.assertEqual(
                tournament,
                {
                    "baseline": root / "baseline.dat",
                    "pest": root / "final_pest.dat",
                    "mgda": root / "final_mgda.dat",
                },
            )
            self.assertEqual(progress, {"mgda": root / "progress_mgda.dat"})

    def test_run_compare_scenarios_materializes_and_runs_existing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work_dir = root / "work"
            work_dir.mkdir()
            par_path = root / "ksas_mvp_est.par"
            dat_path = root / "params_mgda.dat"
            par_path.write_text("P1V 12.5\n", encoding="utf-8")
            dat_path.write_text("g1 33.0\n", encoding="utf-8")
            captured: list[tuple[str, Path, Path, str]] = []

            def fake_runner(scenario: str, scenario_dir: Path, params_path: Path) -> dict[str, float]:
                captured.append((scenario, scenario_dir, params_path, params_path.read_text(encoding="utf-8")))
                return {f"{scenario}_value": float(len(captured))}

            results = pest_runner.run_compare_scenarios(
                {
                    "pest": par_path,
                    "mgda": dat_path,
                    "missing": root / "does_not_exist.dat",
                },
                work_dir,
                fake_runner,
            )

            self.assertEqual(
                results,
                {
                    "pest": {"pest_value": 1.0},
                    "mgda": {"mgda_value": 2.0},
                },
            )
            self.assertEqual(
                captured,
                [
                    ("pest", work_dir / "pest", work_dir / "pest" / "params.dat", "p1v 12.5\n"),
                    ("mgda", work_dir / "mgda", work_dir / "mgda" / "params.dat", "g1 33.0\n"),
                ],
            )

    def test_load_measurements_reads_summary_and_wht_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_path = root / "obs.WHA"
            wht_path = root / "obs.WHT"
            a_path.write_text(
                "@TRNO HWAM LAIX\n"
                "1 100.0 3.5\n"
                "2 120.0 4.0\n",
                encoding="utf-8",
            )
            wht_path.write_text(
                "@TRNO DATE LAID\n"
                "1 75020 1.1\n"
                "1 75030 2.2\n"
                "2 75025 1.8\n",
                encoding="utf-8",
            )

            measurements, wht_dates = compare_eval.load_measurements(a_path, wht_path, [1], "HWAM", "LAIX")

            self.assertEqual(
                measurements,
                {
                    "hwam_t01": 100.0,
                    "laix_t01": 3.5,
                    "laid_t01_d75020": 1.1,
                    "laid_t01_d75030": 2.2,
                },
            )
            self.assertEqual(wht_dates, {1: [75020, 75030]})

    def test_build_summary_rows_aggregates_compare_metrics(self) -> None:
        rows = compare_eval.build_trt_rows(
            sim_results={
                "baseline": {
                    "hwam_t01": 115.0,
                    "laix_t01": 4.0,
                    "laid_t01_d75020": 1.3,
                }
            },
            measurements={
                "hwam_t01": 100.0,
                "laix_t01": 3.0,
                "laid_t01_d75020": 1.0,
            },
            weights={
                "hwam_t01": 0.5,
                "laix_t01": 2.0,
                "laid_t01_d75020": 3.0,
            },
            trts=[1],
            yield_var="HWAM",
            laix_var="LAIX",
            wht_dates={1: [75020]},
        )

        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["phi"], 226.09)
        self.assertAlmostEqual(rows[0]["phi_w"], 61.06)
        self.assertEqual(rows[0]["n_wht_dates"], 1)

        summary_rows = compare_eval.build_summary_rows(["baseline"], rows)

        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(summary_rows[0]["scenario"], "baseline")
        self.assertEqual(summary_rows[0]["n_trt"], 1)
        self.assertAlmostEqual(float(summary_rows[0]["rmse_yield"]), 15.0)
        self.assertAlmostEqual(float(summary_rows[0]["rmse_laix"]), 1.0)
        self.assertAlmostEqual(float(summary_rows[0]["phi"]), 226.09)
        self.assertAlmostEqual(float(summary_rows[0]["phi_w"]), 61.06)

    def test_compare_three_main_uses_shared_selector_and_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            source_path = work_dir / "ksas_mvp_est.par"
            source_path.write_text("P1V 12.5\n", encoding="utf-8")
            selector_calls: list[tuple[str, Path, Path]] = []
            runner_calls: list[tuple[dict[str, Path], Path]] = []
            cfg = {
                "paths": {
                    "dssat_case_dir": str(work_dir),
                    "wha_path": "obs.WHA",
                    "wht_path": "obs.WHT",
                },
                "metrics": {"yield_var": "HWAM", "laix_var": "LAIX"},
                "scenario": {"trts": [1]},
            }

            def fake_selector(mode: str, current_work_dir: Path, project_root: Path, env: dict[str, str] | None = None) -> dict[str, Path]:
                selector_calls.append((mode, current_work_dir, project_root))
                return {"pest": source_path}

            def fake_run_compare_scenarios(
                param_files: dict[str, Path],
                current_work_dir: Path,
                runner: object,
                skip_missing: bool = True,
            ) -> dict[str, dict[str, float]]:
                runner_calls.append((param_files, current_work_dir))
                return {"pest": {"hwam_t01": 101.0}}

            previous_cwd = Path.cwd()
            try:
                os.chdir(work_dir)
                with (
                    patch.object(compare_three, "resolve_compare_param_files", side_effect=fake_selector),
                    patch.object(compare_three, "run_compare_scenarios", side_effect=fake_run_compare_scenarios),
                    patch.object(compare_three, "load_project_config", return_value=cfg),
                    patch.object(compare_three, "load_measurements", return_value=({}, {})),
                    patch.object(compare_three, "_read_obs_weights", return_value={}),
                    patch.object(compare_three, "build_trt_rows", return_value=[]),
                    patch.object(compare_three, "build_summary_rows", return_value=[{"scenario": "pest", "n_trt": 0}]),
                    patch.object(compare_three.sys, "argv", ["compare_three.py"]),
                ):
                    compare_three.main()
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(selector_calls[0][0], "standard")
            self.assertEqual(selector_calls[0][1], work_dir)
            self.assertEqual(runner_calls, [({"pest": source_path}, work_dir)])

    def test_compare_three_main_writes_compare_summary_with_schema_and_scenario_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            cfg = {
                "paths": {
                    "dssat_case_dir": str(work_dir),
                    "wha_path": "obs.WHA",
                    "wht_path": "obs.WHT",
                },
                "metrics": {"yield_var": "HWAM", "laix_var": "LAIX"},
                "scenario": {"trts": [1]},
            }
            summary_rows = [
                {"scenario": "baseline", "n_trt": 1, "phi_w": 2.5, "custom_metric": 7.0},
                {"scenario": "mgda", "rmse_yield": 0.4, "n_trt": 1},
            ]

            previous_cwd = Path.cwd()
            try:
                os.chdir(work_dir)
                with (
                    patch.object(compare_three, "resolve_compare_param_files", return_value={"baseline": work_dir / "a.dat"}),
                    patch.object(compare_three, "run_compare_scenarios", return_value={"baseline": {"hwam_t01": 101.0}, "mgda": {"hwam_t01": 99.0}}),
                    patch.object(compare_three, "load_project_config", return_value=cfg),
                    patch.object(compare_three, "load_measurements", return_value=({}, {})),
                    patch.object(compare_three, "_read_obs_weights", return_value={}),
                    patch.object(compare_three, "build_trt_rows", return_value=[]),
                    patch.object(compare_three, "build_summary_rows", return_value=summary_rows),
                    patch.object(compare_three.sys, "argv", ["compare_three.py"]),
                ):
                    compare_three.main()
            finally:
                os.chdir(previous_cwd)

            compare_path = work_dir / "compare_summary.csv"
            self.assertTrue(compare_path.exists())
            with compare_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            header_parts = compare_path.read_text(encoding="utf-8").splitlines()[0].split(",")
            self.assertEqual(header_parts[:4], ["scenario", "n_trt", "rmse_yield", "mae_yield"])
            self.assertEqual([row["scenario"] for row in rows], ["baseline", "mgda"])
            self.assertIn("phi_w", header_parts)

    def test_result_schema_build_compare_summary_fieldnames_keeps_schema_order(self) -> None:
        fieldnames = result_schema.build_compare_summary_fieldnames(
            [
                {"scenario": "pest", "n_trt": 1, "phi_w": 2.5, "custom_metric": 7.0},
                {"scenario": "mgda", "rmse_yield": 0.4},
            ]
        )

        self.assertEqual(fieldnames[:4], ["scenario", "n_trt", "rmse_yield", "mae_yield"])
        self.assertIn("phi_w", fieldnames)
        self.assertEqual(fieldnames[-1], "custom_metric")

    def test_compare_three_run_one_uses_shared_compare_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            params_path = work_dir / "params.dat"
            params_path.write_text("p1v 10.0\n", encoding="utf-8")
            captured: dict[str, object] = {}

            def fake_run_compare_model(
                work_dir: Path,
                params_path: Path,
                trts: list[int] | None = None,
                keep_outputs: bool = False,
                python_executable: str | None = None,
                run_model_path: Path | None = None,
                failure_label: str = "run_model.py",
                extra_env: dict[str, str] | None = None,
                output_path: Path | None = None,
            ) -> dict[str, float]:
                captured["work_dir"] = work_dir
                captured["params_path"] = params_path
                captured["trts"] = list(trts or [])
                captured["keep_outputs"] = keep_outputs
                captured["python_executable"] = python_executable
                captured["run_model_path"] = run_model_path
                captured["extra_env"] = dict(extra_env or {})
                captured["failure_label"] = failure_label
                captured["output_path"] = output_path
                return {"hwam": 321.0}

            with patch.object(compare_three, "run_compare_model", side_effect=fake_run_compare_model):
                result = compare_three._run_one(work_dir, work_dir, params_path, [1, 3])

            self.assertEqual(result, {"hwam": 321.0})
            self.assertEqual(captured["work_dir"], work_dir)
            self.assertEqual(captured["params_path"], params_path)
            self.assertEqual(captured["failure_label"], "compare_three run_model.py")
            self.assertEqual(captured["trts"], [1, 3])
            self.assertEqual(captured["keep_outputs"], False)
            self.assertIsNone(captured["run_model_path"])
            self.assertIsNone(captured["output_path"])

    def test_compare_three_main_passes_shared_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            source_path = work_dir / "params_pest.dat"
            source_path.write_text("p1v 10.0\n", encoding="utf-8")
            scenario_dir = work_dir / "pest"
            scenario_dir.mkdir()
            scenario_params = scenario_dir / "params.dat"
            scenario_params.write_text("p1v 10.0\n", encoding="utf-8")
            cfg = {
                "paths": {
                    "dssat_case_dir": str(work_dir),
                    "wha_path": "SWSW7501.WHA",
                    "wht_path": "SWSW7501.WHT",
                },
                "scenario": {"trts": [1, 3]},
                "metrics": {"yield_var": "HWAM", "laix_var": "LAIX"},
            }
            captured: dict[str, object] = {}

            def fake_selector(mode: str, current_work_dir: Path, project_root: Path, env: dict[str, str] | None = None) -> dict[str, Path]:
                captured["selector_mode"] = mode
                captured["selector_work_dir"] = current_work_dir
                captured["selector_project_root"] = project_root
                captured["selector_env"] = dict(env or {})
                return {"pest": source_path}

            def fake_run_one(
                scen_dir: Path,
                dssat_dir: Path,
                params_path: Path,
                trts: list[int],
            ) -> dict[str, float]:
                captured["scenario_dir"] = scen_dir
                captured["dssat_dir"] = dssat_dir
                captured["params_path"] = params_path
                captured["trts"] = list(trts)
                return {"hwam": 321.0}

            def fake_run_compare_scenarios(
                param_files: dict[str, Path],
                current_work_dir: Path,
                runner,
                skip_missing: bool = True,
            ) -> dict[str, dict[str, float]]:
                captured["param_files"] = dict(param_files)
                captured["runner_work_dir"] = current_work_dir
                captured["skip_missing"] = skip_missing
                return {"pest": runner("pest", scenario_dir, scenario_params)}

            previous_cwd = Path.cwd()
            try:
                os.chdir(work_dir)
                with (
                    patch.object(compare_three, "resolve_compare_param_files", side_effect=fake_selector),
                    patch.object(compare_three, "run_compare_scenarios", side_effect=fake_run_compare_scenarios),
                    patch.object(compare_three, "_run_one", side_effect=fake_run_one),
                    patch.object(compare_three, "load_project_config", return_value=cfg),
                    patch.object(compare_three, "load_measurements", return_value=({}, {})),
                    patch.object(compare_three, "_read_obs_weights", return_value={}),
                    patch.object(compare_three, "build_trt_rows", return_value=[]),
                    patch.object(compare_three, "build_summary_rows", return_value=[{"scenario": "pest", "n_trt": 1}]),
                    patch.object(compare_three.sys, "argv", ["compare_three.py"]),
                ):
                    compare_three.main()
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(captured["dssat_dir"], work_dir)
            self.assertEqual(captured["params_path"], scenario_params)
            self.assertEqual(captured["trts"], [1, 3])

    def test_mgda_update_evaluate_phi_uses_shared_compare_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            fake_pst = object()
            captured: dict[str, object] = {}

            def fake_run_compare_model(
                work_dir: Path,
                params_path: Path,
                trts: list[int] | None = None,
                keep_outputs: bool = False,
                python_executable: str | None = None,
                run_model_path: Path | None = None,
                failure_label: str = "run_model.py",
                extra_env: dict[str, str] | None = None,
                output_path: Path | None = None,
            ) -> dict[str, float]:
                captured["work_dir"] = work_dir
                captured["params_path"] = params_path
                captured["trts"] = list(trts or [])
                captured["keep_outputs"] = keep_outputs
                captured["python_executable"] = python_executable
                captured["run_model_path"] = run_model_path
                captured["extra_env"] = dict(extra_env or {})
                captured["failure_label"] = failure_label
                captured["output_path"] = output_path
                return {"hwam": 98.5}

            with (
                patch.object(mgda_update, "run_compare_model", side_effect=fake_run_compare_model),
                patch.object(mgda_update, "_calc_phi", return_value=7.25) as calc_phi_mock,
            ):
                phi = mgda_update._evaluate_phi(
                    work_dir,
                    fake_pst,
                    {"p1v": 12.0},
                    {"observations": {}},
                    {"obs_yield": 1},
                )

            self.assertEqual(phi, 7.25)
            self.assertEqual(captured["work_dir"], work_dir)
            self.assertEqual(captured["failure_label"], "mgda_update run_model.py")
            self.assertEqual(captured["keep_outputs"], False)
            self.assertEqual(captured["trts"], [])
            self.assertTrue(str(captured["params_path"]).endswith("_mgda_eval_params.dat"))
            self.assertIsNone(captured["run_model_path"])
            self.assertIsNone(captured["output_path"])
            calc_phi_mock.assert_called_once_with(
                fake_pst,
                {"hwam": 98.5},
                {"observations": {}},
                {"obs_yield": 1},
                "mse",
                1.0,
            )

    def test_parse_best_ies_result_reads_best_realization_from_par_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,p1v,g1\nrealA,12.5,33.0\nrealB,14.0,35.0\n",
                encoding="utf-8",
            )

            params, phi = pest_runner.parse_best_ies_result(
                work_dir,
                np.array([0.0, 0.0], dtype=float),
                ["p1v", "g1"],
                lambda values: values,
            )

            self.assertEqual(phi, 1.5)
            self.assertTrue(np.array_equal(params, np.array([12.5, 33.0], dtype=float)))

    def test_export_posterior_diagnostics_writes_summary_and_svg_plots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,p1v,g1\nrealA,12.5,33.0\nrealB,14.0,35.0\n",
                encoding="utf-8",
            )
            (work_dir / "parameter_bounds_preview.csv").write_text(
                "parameter,lower,upper,group\np1v,10.0,16.0,g_cul\ng1,30.0,40.0,g_eco\n",
                encoding="utf-8",
            )
            prior_bounds, parameter_groups = pest_runner._read_bounds_preview(work_dir / "parameter_bounds_preview.csv")

            artifacts = pest_runner.export_posterior_diagnostics(
                work_dir,
                prior_params={"p1v": 11.0, "g1": 31.0},
                prior_bounds=prior_bounds,
                parameter_groups=parameter_groups,
            )

            summary_path = artifacts["summary_csv"]
            manifest_path = artifacts["manifest_csv"]
            self.assertTrue(summary_path.exists())
            self.assertTrue(manifest_path.exists())
            summary_text = summary_path.read_text(encoding="utf-8")
            self.assertIn("parameter,group,iteration,sample_count,prior,best,prior_lower,prior_upper,posterior_mean", summary_text)
            self.assertIn("p1v,g_cul,2,2,11.0,12.5,10.0,16.0,13.25", summary_text)
            p1v_svg = artifacts["plots_dir"] / "p1v.svg"
            self.assertTrue(p1v_svg.exists())
            svg_text = p1v_svg.read_text(encoding="utf-8")
            self.assertIn("p1v posterior", svg_text)
            self.assertIn(">prior<", svg_text)
            self.assertIn(">best<", svg_text)
            self.assertIn(">prior_lb<", svg_text)
            self.assertIn(">prior_ub<", svg_text)
            self.assertIn(">median<", svg_text)
            atlas_path = artifacts["atlas_dir"] / "g_cul.html"
            self.assertTrue(atlas_path.exists())
            self.assertIn("plots/p1v.svg", atlas_path.read_text(encoding="utf-8"))

    def test_export_posterior_diagnostics_filters_requested_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,p1v,g1\nrealA,12.5,33.0\nrealB,14.0,35.0\n",
                encoding="utf-8",
            )

            artifacts = pest_runner.export_posterior_diagnostics(
                work_dir,
                include_params=["g1"],
            )

            summary_text = artifacts["summary_csv"].read_text(encoding="utf-8")
            self.assertIn("g1", summary_text)
            self.assertNotIn("p1v", summary_text)
            self.assertTrue((artifacts["plots_dir"] / "g1.svg").exists())
            self.assertFalse((artifacts["plots_dir"] / "p1v.svg").exists())

    def test_export_posterior_diagnostics_respects_bounds_preview_parameter_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,p1v,g1\nrealA,12.5,33.0\nrealB,14.0,35.0\n",
                encoding="utf-8",
            )
            bounds_preview_path = work_dir / "parameter_bounds_preview.csv"
            bounds_preview_path.write_text(
                "parameter,lower,upper,group\n"
                "g1,30.0,40.0,g_eco\n"
                "p1v,10.0,16.0,g_cul\n",
                encoding="utf-8",
            )

            prior_bounds, parameter_groups, parameter_order = pest_runner._read_bounds_preview_metadata(
                bounds_preview_path
            )
            artifacts = pest_runner.export_posterior_diagnostics(
                work_dir,
                prior_params={"p1v": 11.0, "g1": 31.0},
                prior_bounds=prior_bounds,
                parameter_groups=parameter_groups,
                parameter_order=parameter_order,
            )

            with artifacts["summary_csv"].open("r", encoding="utf-8", newline="") as handle:
                summary_rows = list(csv.DictReader(handle))
            with artifacts["manifest_csv"].open("r", encoding="utf-8", newline="") as handle:
                manifest_rows = list(csv.DictReader(handle))

            self.assertEqual([row["parameter"] for row in summary_rows], ["g1", "p1v"])
            self.assertEqual([row["parameter"] for row in manifest_rows], ["g1", "p1v"])
            self.assertEqual(summary_rows[0]["group"], "g_eco")
            self.assertEqual(summary_rows[1]["group"], "g_cul")

    def test_export_posterior_diagnostics_preserves_group_atlas_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,p1v,g1\nrealA,12.5,33.0\nrealB,14.0,35.0\n",
                encoding="utf-8",
            )
            bounds_preview_path = work_dir / "parameter_bounds_preview.csv"
            bounds_preview_path.write_text(
                "parameter,lower,upper,group\n"
                "g1,30.0,40.0,g_shared\n"
                "p1v,10.0,16.0,g_shared\n",
                encoding="utf-8",
            )

            prior_bounds, parameter_groups, parameter_order = pest_runner._read_bounds_preview_metadata(
                bounds_preview_path
            )
            artifacts = pest_runner.export_posterior_diagnostics(
                work_dir,
                prior_params={"p1v": 11.0, "g1": 31.0},
                prior_bounds=prior_bounds,
                parameter_groups=parameter_groups,
                parameter_order=parameter_order,
            )

            atlas_text = (artifacts["atlas_dir"] / "g_shared.html").read_text(encoding="utf-8")
            self.assertLess(atlas_text.index("<h2>g1</h2>"), atlas_text.index("<h2>p1v</h2>"))
            self.assertLess(atlas_text.index("plots/g1.svg"), atlas_text.index("plots/p1v.svg"))

    def test_export_posterior_diagnostics_keeps_summary_manifest_and_atlas_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,g1,p1v,xfrt\nrealA,33.0,12.5,0.70\nrealB,35.0,14.0,0.80\n",
                encoding="utf-8",
            )
            bounds_preview_path = work_dir / "parameter_bounds_preview.csv"
            bounds_preview_path.write_text(
                "parameter,lower,upper,group\n"
                "g1,30.0,40.0,g_eco\n"
                "p1v,10.0,16.0,g_cul\n"
                "xfrt,0.55,0.90,g_cul\n",
                encoding="utf-8",
            )

            prior_bounds, parameter_groups, parameter_order = pest_runner._read_bounds_preview_metadata(
                bounds_preview_path
            )
            artifacts = pest_runner.export_posterior_diagnostics(
                work_dir,
                prior_params={"g1": 31.0, "p1v": 11.0, "xfrt": 0.65},
                prior_bounds=prior_bounds,
                parameter_groups=parameter_groups,
                parameter_order=parameter_order,
            )

            with artifacts["summary_csv"].open("r", encoding="utf-8", newline="") as handle:
                summary_rows = list(csv.DictReader(handle))
            with artifacts["manifest_csv"].open("r", encoding="utf-8", newline="") as handle:
                manifest_rows = list(csv.DictReader(handle))

            self.assertEqual([row["parameter"] for row in summary_rows], ["g1", "p1v", "xfrt"])
            self.assertEqual([row["parameter"] for row in manifest_rows], ["g1", "p1v", "xfrt"])
            self.assertEqual([row["group"] for row in summary_rows], [row["group"] for row in manifest_rows])
            for row in manifest_rows:
                plot_path = Path(row["plot_path"])
                self.assertTrue(plot_path.exists())
                self.assertEqual(plot_path.parent, artifacts["plots_dir"])
                self.assertEqual(plot_path.stem, row["parameter"])

            eco_atlas = (artifacts["atlas_dir"] / "g_eco.html").read_text(encoding="utf-8")
            cul_atlas = (artifacts["atlas_dir"] / "g_cul.html").read_text(encoding="utf-8")
            self.assertIn("plots/g1.svg", eco_atlas)
            self.assertNotIn("plots/p1v.svg", eco_atlas)
            self.assertLess(cul_atlas.index("<h2>p1v</h2>"), cul_atlas.index("<h2>xfrt</h2>"))
            self.assertIn("plots/p1v.svg", cul_atlas)
            self.assertIn("plots/xfrt.svg", cul_atlas)

    def test_format_posterior_summary_table_renders_terminal_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "posterior_summary.csv"
            summary_path.write_text(
                "parameter,group,iteration,sample_count,prior,best,prior_lower,prior_upper,posterior_mean,posterior_std,posterior_p05,posterior_p50,posterior_p95\n"
                "p1v,g_cul,2,2,11.0,12.5,10.0,16.0,13.25,0.75,12.57,13.25,13.93\n",
                encoding="utf-8",
            )

            table_text = pest_runner.format_posterior_summary_table(summary_path)

            self.assertIn("parameter", table_text)
            self.assertIn("group", table_text)
            self.assertIn("p1v", table_text)
            self.assertIn("13.2500", table_text)
            self.assertIn("16.0000", table_text)

    def test_format_posterior_summary_table_allows_blank_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "posterior_summary.csv"
            summary_path.write_text(
                "parameter,group,iteration,sample_count,prior,best,prior_lower,prior_upper,posterior_mean,posterior_std,posterior_p05,posterior_p50,posterior_p95\n"
                "g1,,2,2,31.0,33.0,,,34.00,1.00,33.10,34.00,34.90\n",
                encoding="utf-8",
            )

            table_text = pest_runner.format_posterior_summary_table(summary_path)

            self.assertIn("g1", table_text)
            self.assertIn("34.0000", table_text)
            self.assertNotIn("ValueError", table_text)

    def test_pest_runner_main_exports_posterior_from_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,p1v,g1\nrealA,12.5,33.0\nrealB,14.0,35.0\n",
                encoding="utf-8",
            )
            prior_path = work_dir / "params.dat"
            prior_path.write_text("p1v 11.0\ng1 31.0\n", encoding="utf-8")
            bounds_preview_path = work_dir / "parameter_bounds_preview.csv"
            bounds_preview_path.write_text(
                "parameter,lower,upper,group\np1v,10.0,16.0,g_cul\ng1,30.0,40.0,g_eco\n",
                encoding="utf-8",
            )
            buffer = io.StringIO()
            argv = [
                "pest_runner.py",
                "export-posterior",
                "--work-dir",
                str(work_dir),
                "--prior-params",
                str(prior_path),
                "--bounds-preview",
                str(bounds_preview_path),
                "--include-params",
                "p1v",
            ]

            with patch.object(sys, "argv", argv):
                with redirect_stdout(buffer):
                    pest_runner.main()

            text = buffer.getvalue()
            self.assertIn("Posterior summary saved to", text)
            self.assertIn("Posterior atlas saved to", text)
            self.assertIn("parameter", text)
            self.assertIn("p1v", text)
            self.assertNotIn("g1", text)

    def test_pest_runner_main_exports_posterior_using_run_manifest_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,p1v,g1\nrealA,12.5,33.0\nrealB,14.0,35.0\n",
                encoding="utf-8",
            )
            prior_path = work_dir / "params.dat"
            prior_path.write_text("p1v 11.0\ng1 31.0\n", encoding="utf-8")
            bounds_preview_path = work_dir / "parameter_bounds_preview.csv"
            bounds_preview_path.write_text(
                "parameter,lower,upper,group\n"
                "g1,30.0,40.0,g_eco\n"
                "p1v,10.0,16.0,g_cul\n",
                encoding="utf-8",
            )
            (work_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "paths": {
                            "params_path": str(prior_path),
                            "bounds_preview_path": str(bounds_preview_path),
                        }
                    }
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            argv = [
                "pest_runner.py",
                "export-posterior",
                "--work-dir",
                str(work_dir),
            ]

            with patch.object(sys, "argv", argv):
                with redirect_stdout(buffer):
                    pest_runner.main()

            with (work_dir / "posterior_diagnostics" / "posterior_summary.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                summary_rows = list(csv.DictReader(handle))
            self.assertEqual([row["parameter"] for row in summary_rows], ["g1", "p1v"])
            self.assertEqual(summary_rows[0]["prior"], "31.0")
            self.assertEqual(summary_rows[0]["prior_lower"], "30.0")
            self.assertEqual(summary_rows[1]["prior"], "11.0")
            self.assertEqual(summary_rows[1]["prior_upper"], "16.0")
            self.assertIn("Posterior summary saved to", buffer.getvalue())

    def test_resolve_posterior_reference_inputs_prefers_explicit_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            explicit_params = work_dir / "explicit_params.dat"
            explicit_params.write_text("g1 31.0\np1v 11.0\n", encoding="utf-8")
            explicit_bounds = work_dir / "explicit_bounds.csv"
            explicit_bounds.write_text(
                "parameter,lower,upper,group\n"
                "g1,30.0,40.0,g_explicit\n"
                "p1v,10.0,16.0,g_explicit\n",
                encoding="utf-8",
            )
            fallback_params = work_dir / "fallback_params.dat"
            fallback_params.write_text("other 99.0\n", encoding="utf-8")
            fallback_bounds = work_dir / "fallback_bounds.csv"
            fallback_bounds.write_text(
                "parameter,lower,upper,group\nother,1.0,2.0,g_fallback\n",
                encoding="utf-8",
            )
            (work_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "paths": {
                            "params_path": str(fallback_params),
                            "bounds_preview_path": str(fallback_bounds),
                        }
                    }
                ),
                encoding="utf-8",
            )

            prior_params, prior_bounds, parameter_groups, parameter_order = (
                pest_runner._resolve_posterior_reference_inputs(
                    work_dir,
                    prior_params_path=str(explicit_params),
                    bounds_preview_path=str(explicit_bounds),
                )
            )

            self.assertEqual(prior_params, {"g1": 31.0, "p1v": 11.0})
            self.assertEqual(prior_bounds, {"g1": (30.0, 40.0), "p1v": (10.0, 16.0)})
            self.assertEqual(parameter_groups, {"g1": "g_explicit", "p1v": "g_explicit"})
            self.assertEqual(parameter_order, ["g1", "p1v"])

    def test_resolve_posterior_reference_inputs_degrades_without_manifest_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            params_path = work_dir / "params.dat"
            params_path.write_text("g1 31.0\np1v 11.0\n", encoding="utf-8")

            prior_params, prior_bounds, parameter_groups, parameter_order = pest_runner._resolve_posterior_reference_inputs(
                work_dir,
                prior_params_path=str(params_path),
            )
            self.assertEqual(prior_params, {"g1": 31.0, "p1v": 11.0})
            self.assertEqual(prior_bounds, {})
            self.assertEqual(parameter_groups, {})
            self.assertEqual(parameter_order, ["g1", "p1v"])

            (work_dir / "run_manifest.json").write_text("{invalid json", encoding="utf-8")
            prior_params, prior_bounds, parameter_groups, parameter_order = pest_runner._resolve_posterior_reference_inputs(
                work_dir
            )
            self.assertEqual(prior_params, {})
            self.assertEqual(prior_bounds, {})
            self.assertEqual(parameter_groups, {})
            self.assertEqual(parameter_order, [])

    def test_resolve_posterior_reference_inputs_ignores_missing_manifest_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "paths": {
                            "params_path": str(work_dir / "missing_params.dat"),
                            "bounds_preview_path": str(work_dir / "missing_bounds.csv"),
                        }
                    }
                ),
                encoding="utf-8",
            )

            prior_params, prior_bounds, parameter_groups, parameter_order = pest_runner._resolve_posterior_reference_inputs(
                work_dir
            )

            self.assertEqual(prior_params, {})
            self.assertEqual(prior_bounds, {})
            self.assertEqual(parameter_groups, {})
            self.assertEqual(parameter_order, [])

    def test_resolve_posterior_reference_inputs_falls_back_when_bounds_preview_schema_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            params_path = work_dir / "params.dat"
            params_path.write_text("wtpsd 0.20\nppsen 0.05\n", encoding="utf-8")
            invalid_bounds_path = work_dir / "parameter_bounds_preview.csv"
            invalid_bounds_path.write_text(
                "name,minimum,maximum,cluster\n"
                "wtpsd,0.18,0.24,g_cul\n"
                "ppsen,0.01,0.10,g_cul\n",
                encoding="utf-8",
            )
            (work_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "paths": {
                            "params_path": str(params_path),
                            "bounds_preview_path": str(invalid_bounds_path),
                        }
                    }
                ),
                encoding="utf-8",
            )

            prior_params, prior_bounds, parameter_groups, parameter_order = pest_runner._resolve_posterior_reference_inputs(
                work_dir
            )

            self.assertEqual(prior_params, {"wtpsd": 0.2, "ppsen": 0.05})
            self.assertEqual(prior_bounds, {})
            self.assertEqual(parameter_groups, {})
            self.assertEqual(parameter_order, ["wtpsd", "ppsen"])

    def test_read_bounds_preview_metadata_ignores_invalid_values_and_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bounds_preview_path = Path(tmp) / "parameter_bounds_preview.csv"
            bounds_preview_path.write_text(
                "parameter,lower,upper,group\n"
                "wtpsd,0.18,0.24,g_cul\n"
                "ppsen,,0.10,g_cul\n"
                "xfrt,broken,0.90,g_cul\n"
                "wtpsd,invalid,0.30,g_cul\n",
                encoding="utf-8",
            )

            prior_bounds, parameter_groups, parameter_order = pest_runner._read_bounds_preview_metadata(
                bounds_preview_path
            )

            self.assertEqual(prior_bounds, {"wtpsd": (0.18, 0.24)})
            self.assertEqual(
                parameter_groups,
                {"wtpsd": "g_cul", "ppsen": "g_cul", "xfrt": "g_cul"},
            )
            self.assertEqual(parameter_order, ["wtpsd", "ppsen", "xfrt"])

    def test_pest_runner_main_exports_posterior_with_manifest_params_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,p1v,g1\nrealA,12.5,33.0\nrealB,14.0,35.0\n",
                encoding="utf-8",
            )
            prior_path = work_dir / "params.dat"
            prior_path.write_text("g1 31.0\np1v 11.0\n", encoding="utf-8")
            (work_dir / "run_manifest.json").write_text(
                json.dumps({"paths": {"params_path": str(prior_path)}}),
                encoding="utf-8",
            )
            buffer = io.StringIO()

            with patch.object(sys, "argv", ["pest_runner.py", "export-posterior", "--work-dir", str(work_dir)]):
                with redirect_stdout(buffer):
                    pest_runner.main()

            with (work_dir / "posterior_diagnostics" / "posterior_summary.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                summary_rows = list(csv.DictReader(handle))
            self.assertEqual([row["parameter"] for row in summary_rows], ["g1", "p1v"])
            self.assertEqual(summary_rows[0]["prior"], "31.0")
            self.assertEqual(summary_rows[0]["prior_lower"], "")
            self.assertEqual(summary_rows[1]["prior"], "11.0")
            self.assertEqual(summary_rows[1]["prior_upper"], "")
            self.assertIn("Posterior atlas saved to", buffer.getvalue())

    def test_pest_runner_main_exports_posterior_when_manifest_files_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,ppsen,wtpsd\nrealA,0.05,0.20\nrealB,0.08,0.23\n",
                encoding="utf-8",
            )
            (work_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "paths": {
                            "params_path": str(work_dir / "missing_params.dat"),
                            "bounds_preview_path": str(work_dir / "missing_bounds.csv"),
                        }
                    }
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()

            with patch.object(sys, "argv", ["pest_runner.py", "export-posterior", "--work-dir", str(work_dir)]):
                with redirect_stdout(buffer):
                    pest_runner.main()

            with (work_dir / "posterior_diagnostics" / "posterior_summary.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                summary_rows = list(csv.DictReader(handle))
            self.assertEqual([row["parameter"] for row in summary_rows], ["ppsen", "wtpsd"])
            self.assertEqual(summary_rows[0]["prior"], "")
            self.assertEqual(summary_rows[1]["prior_upper"], "")
            self.assertIn("Posterior summary saved to", buffer.getvalue())

    def test_pest_runner_main_exports_posterior_to_custom_output_dirs_without_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,ppsen,wtpsd\nrealA,0.05,0.20\nrealB,0.08,0.23\n",
                encoding="utf-8",
            )
            params_path = work_dir / "params.dat"
            params_path.write_text("wtpsd 0.20\nppsen 0.05\n", encoding="utf-8")
            bounds_preview_path = work_dir / "parameter_bounds_preview.csv"
            bounds_preview_path.write_text(
                "parameter,lower,upper,group\n"
                "wtpsd,0.18,0.24,g_cul\n"
                "ppsen,0.01,0.10,g_cul\n",
                encoding="utf-8",
            )
            (work_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "paths": {
                            "params_path": str(params_path),
                            "bounds_preview_path": str(bounds_preview_path),
                        }
                    }
                ),
                encoding="utf-8",
            )
            run_a_dir = work_dir / "batch_run_a" / "posterior_diagnostics"
            run_b_dir = work_dir / "batch_run_b" / "posterior_diagnostics"

            for output_dir in (run_a_dir, run_b_dir):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "pest_runner.py",
                        "export-posterior",
                        "--work-dir",
                        str(work_dir),
                        "--output-dir",
                        str(output_dir),
                    ],
                ):
                    pest_runner.main()

            default_output_dir = work_dir / "posterior_diagnostics"
            self.assertFalse(default_output_dir.exists())
            for output_dir in (run_a_dir, run_b_dir):
                summary_path = output_dir / "posterior_summary.csv"
                atlas_path = output_dir / "group_atlas" / "g_cul.html"
                self.assertTrue(summary_path.exists())
                self.assertTrue(atlas_path.exists())
                with summary_path.open("r", encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual([row["parameter"] for row in rows], ["wtpsd", "ppsen"])

    def test_export_posterior_diagnostics_cleans_stale_files_when_reusing_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            output_dir = work_dir / "posterior_diagnostics"
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,ppsen,g1\nrealA,0.05,33.0\nrealB,0.08,35.0\n",
                encoding="utf-8",
            )

            pest_runner.export_posterior_diagnostics(
                work_dir,
                output_dir=output_dir,
                prior_params={"ppsen": 0.05, "g1": 31.0},
                parameter_groups={"ppsen": "g_cul", "g1": "g_eco"},
                prior_bounds={"ppsen": (0.01, 0.10), "g1": (30.0, 40.0)},
                parameter_order=["g1", "ppsen"],
            )
            self.assertTrue((output_dir / "plots" / "g1.svg").exists())
            self.assertTrue((output_dir / "group_atlas" / "g_eco.html").exists())

            artifacts = pest_runner.export_posterior_diagnostics(
                work_dir,
                output_dir=output_dir,
                include_params=["ppsen"],
                prior_params={"ppsen": 0.05, "g1": 31.0},
                parameter_groups={"ppsen": "g_cul", "g1": "g_eco"},
                prior_bounds={"ppsen": (0.01, 0.10), "g1": (30.0, 40.0)},
                parameter_order=["g1", "ppsen"],
            )

            with artifacts["summary_csv"].open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["parameter"] for row in rows], ["ppsen"])
            self.assertTrue((artifacts["plots_dir"] / "ppsen.svg").exists())
            self.assertFalse((artifacts["plots_dir"] / "g1.svg").exists())
            with artifacts["manifest_csv"].open("r", encoding="utf-8", newline="") as handle:
                manifest_rows = list(csv.DictReader(handle))
            self.assertEqual([row["parameter"] for row in manifest_rows], ["ppsen"])
            self.assertTrue(manifest_rows[0]["plot_path"].endswith("plots\\ppsen.svg"))
            self.assertTrue((artifacts["atlas_dir"] / "g_cul.html").exists())
            self.assertFalse((artifacts["atlas_dir"] / "g_eco.html").exists())

    def test_export_posterior_diagnostics_reuses_output_dir_across_stems_and_iterations_without_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            output_dir = work_dir / "posterior_diagnostics"
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,ppsen,g1\nrealA,0.05,33.0\nrealB,0.08,35.0\n",
                encoding="utf-8",
            )
            (work_dir / "alt_case.phi.actual.csv").write_text(
                "iteration,base,real1,real2\n5,2.0,0.8,1.0\n",
                encoding="utf-8",
            )
            (work_dir / "alt_case.5.par.csv").write_text(
                "real_name,xfrt,p1v\nreal1,0.72,12.0\nreal2,0.81,13.0\n",
                encoding="utf-8",
            )

            pest_runner.export_posterior_diagnostics(
                work_dir,
                output_dir=output_dir,
                prior_params={"ppsen": 0.05, "g1": 31.0},
                parameter_groups={"ppsen": "g_cul", "g1": "g_eco"},
                prior_bounds={"ppsen": (0.01, 0.10), "g1": (30.0, 40.0)},
                parameter_order=["g1", "ppsen"],
            )

            artifacts = pest_runner.export_posterior_diagnostics(
                work_dir,
                stem="alt_case",
                iteration=5,
                output_dir=output_dir,
                prior_params={"xfrt": 0.65, "p1v": 11.0},
                parameter_groups={"xfrt": "g_cul", "p1v": "g_cul"},
                prior_bounds={"xfrt": (0.55, 0.90), "p1v": (10.0, 16.0)},
                parameter_order=["xfrt", "p1v"],
            )

            with artifacts["summary_csv"].open("r", encoding="utf-8", newline="") as handle:
                summary_rows = list(csv.DictReader(handle))
            with artifacts["manifest_csv"].open("r", encoding="utf-8", newline="") as handle:
                manifest_rows = list(csv.DictReader(handle))

            self.assertEqual([row["parameter"] for row in summary_rows], ["xfrt", "p1v"])
            self.assertEqual([row["iteration"] for row in summary_rows], ["5", "5"])
            self.assertEqual([row["parameter"] for row in manifest_rows], ["xfrt", "p1v"])
            self.assertTrue((artifacts["plots_dir"] / "xfrt.svg").exists())
            self.assertTrue((artifacts["plots_dir"] / "p1v.svg").exists())
            self.assertFalse((artifacts["plots_dir"] / "ppsen.svg").exists())
            self.assertFalse((artifacts["plots_dir"] / "g1.svg").exists())
            self.assertTrue((artifacts["atlas_dir"] / "g_cul.html").exists())
            self.assertFalse((artifacts["atlas_dir"] / "g_eco.html").exists())

    def test_compare_and_posterior_outputs_coexist_in_shared_work_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            cfg = {
                "paths": {
                    "dssat_case_dir": str(work_dir),
                    "wha_path": "obs.WHA",
                    "wht_path": "obs.WHT",
                },
                "metrics": {"yield_var": "HWAM", "laix_var": "LAIX"},
                "scenario": {"trts": [1]},
            }
            compare_rows = [
                {"scenario": "baseline", "n_trt": 1, "phi_w": 2.5},
                {"scenario": "mgda", "n_trt": 1, "phi_w": 1.5},
            ]
            (work_dir / "ksas_mvp.phi.actual.csv").write_text(
                "iteration,base,realA,realB\n2,3.5,1.5,2.5\n",
                encoding="utf-8",
            )
            (work_dir / "ksas_mvp.2.par.csv").write_text(
                "real_name,ppsen,wtpsd\nrealA,0.05,0.20\nrealB,0.08,0.23\n",
                encoding="utf-8",
            )
            bounds_preview_path = work_dir / "parameter_bounds_preview.csv"
            bounds_preview_path.write_text(
                "parameter,lower,upper,group\n"
                "wtpsd,0.18,0.24,g_cul\n"
                "ppsen,0.01,0.10,g_cul\n",
                encoding="utf-8",
            )
            params_path = work_dir / "params.dat"
            params_path.write_text("wtpsd 0.20\nppsen 0.05\n", encoding="utf-8")
            (work_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "paths": {
                            "params_path": str(params_path),
                            "bounds_preview_path": str(bounds_preview_path),
                        }
                    }
                ),
                encoding="utf-8",
            )

            previous_cwd = Path.cwd()
            try:
                os.chdir(work_dir)
                with (
                    patch.object(compare_three, "resolve_compare_param_files", return_value={"baseline": work_dir / "a.dat"}),
                    patch.object(compare_three, "run_compare_scenarios", return_value={"baseline": {"hwam_t01": 101.0}}),
                    patch.object(compare_three, "load_project_config", return_value=cfg),
                    patch.object(compare_three, "load_measurements", return_value=({}, {})),
                    patch.object(compare_three, "_read_obs_weights", return_value={}),
                    patch.object(compare_three, "build_trt_rows", return_value=[]),
                    patch.object(compare_three, "build_summary_rows", return_value=compare_rows),
                    patch.object(compare_three.sys, "argv", ["compare_three.py"]),
                ):
                    compare_three.main()
                with patch.object(sys, "argv", ["pest_runner.py", "export-posterior", "--work-dir", str(work_dir)]):
                    pest_runner.main()
            finally:
                os.chdir(previous_cwd)

            compare_path = work_dir / "compare_summary.csv"
            posterior_path = work_dir / "posterior_diagnostics" / "posterior_summary.csv"
            atlas_path = work_dir / "posterior_diagnostics" / "group_atlas" / "g_cul.html"
            self.assertTrue(compare_path.exists())
            self.assertTrue(posterior_path.exists())
            self.assertTrue(atlas_path.exists())
            with posterior_path.open("r", encoding="utf-8", newline="") as handle:
                posterior_rows = list(csv.DictReader(handle))
            self.assertEqual([row["parameter"] for row in posterior_rows], ["wtpsd", "ppsen"])
            self.assertIn("scenario,n_trt,rmse_yield,mae_yield", compare_path.read_text(encoding="utf-8"))
            self.assertIn("<h2>wtpsd</h2>", atlas_path.read_text(encoding="utf-8"))

    def test_pest_builder_cli_module_delegates_to_core_main(self) -> None:
        with patch.object(core_pest_builder, "main") as mock_main:
            pest_builder.main()

        mock_main.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
