from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
import uuid
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT.parent / "autoresearch_sandbox"
FIXTURE_CASE = ROOT / "tests" / "fixtures" / "mini_case" / "phase1_case"
if str(SANDBOX) not in sys.path:
    sys.path.insert(0, str(SANDBOX))

import phase1_runner


def load_eval_module():
    sys.modules.setdefault("pyemu", types.ModuleType("pyemu"))
    module_name = f"test_eval_protocol_matrix_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, SANDBOX / "eval.py")
    if spec is None or spec.loader is None:
        raise ImportError("Unable to load eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class TestProtocolMatrixOffline(unittest.TestCase):
    def test_batch_d_build_jobs_covers_full_w_o_s_g_matrix_for_single_crop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_root = Path(tmpdir)
            project_config = session_root / "project.wheat.json"
            project_config.write_text("{}", encoding="utf-8")

            with (
                patch.object(phase1_runner, "resolve_crop_configs", return_value={"Wheat": project_config}),
                patch.object(phase1_runner, "phase0_readiness_reason", return_value=None),
            ):
                jobs, skipped = phase1_runner.build_jobs(
                    session_root=session_root,
                    batch="BatchD",
                    repetitions=1,
                    budget="standard",
                    crops=["Wheat"],
                    train_only=True,
                )

        self.assertEqual(skipped, {})
        self.assertEqual(len(jobs), 32)
        combo_keys = {job["combo_key"] for job in jobs}
        self.assertEqual(len(combo_keys), 32)
        self.assertIn("W0_O1_S1_G1", combo_keys)
        self.assertIn("W4_O2_S2_G3", combo_keys)
        self.assertIn("W6_O2_S1_G1", combo_keys)
        self.assertIn("W8_O1_S2_G3", combo_keys)

    def test_selected_cells_map_to_expected_weight_engine_sequence_and_grouping_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_root = Path(tmpdir)
            project_config = session_root / "project.wheat.json"
            project_config.write_text("{}", encoding="utf-8")

            with (
                patch.object(phase1_runner, "resolve_crop_configs", return_value={"Wheat": project_config}),
                patch.object(phase1_runner, "phase0_readiness_reason", return_value=None),
            ):
                jobs, _ = phase1_runner.build_jobs(
                    session_root=session_root,
                    batch="BatchD",
                    repetitions=1,
                    budget="standard",
                    crops=["Wheat"],
                    combo_keys={"W0_O1_S1_G1", "W8_O1_S2_G3", "W4_O2_S2_G3"},
                    train_only=False,
                )

        by_combo = {job["combo_key"]: job for job in jobs}
        self.assertEqual(by_combo["W0_O1_S1_G1"]["weight"], "w0_raw_identity")
        self.assertEqual(by_combo["W0_O1_S1_G1"]["engine"], "o6_pestpp_glm")
        self.assertEqual(by_combo["W0_O1_S1_G1"]["sequence"], "s1_naive_joint")
        self.assertEqual(by_combo["W0_O1_S1_G1"]["grouping"], "g1_flat_all_in_one")
        self.assertFalse(by_combo["W0_O1_S1_G1"]["train_only"])

        self.assertEqual(by_combo["W8_O1_S2_G3"]["weight"], "w8_dssat_group_max")
        self.assertEqual(by_combo["W8_O1_S2_G3"]["engine"], "o6_pestpp_glm")
        self.assertEqual(by_combo["W8_O1_S2_G3"]["sequence"], "s2_sequential_phase")
        self.assertEqual(by_combo["W8_O1_S2_G3"]["grouping"], "g3_dssat_extended")

        self.assertEqual(by_combo["W4_O2_S2_G3"]["weight"], "w4_min_max_equal")
        self.assertEqual(by_combo["W4_O2_S2_G3"]["engine"], "o2_pestpp_ies")
        self.assertEqual(by_combo["W4_O2_S2_G3"]["sequence"], "s2_sequential_phase")
        self.assertEqual(by_combo["W4_O2_S2_G3"]["grouping"], "g3_dssat_extended")

    def test_incompatible_protocol_cells_are_rejected_by_eval_contract(self) -> None:
        eval_module = load_eval_module()

        incompatible_cases = [
            ("w7_equal_contribution", "s2_sequential_phase", "g1_flat_all_in_one", "o1_least_squares"),
            ("w1_inverse_variance", "s3_wls_joint", "g1_flat_all_in_one", "o1_least_squares"),
            ("w9_pareto_no_preweight", "s2_sequential_phase", "g3_dssat_extended", "o1_least_squares"),
        ]

        for weight_mode, sequence, grouping, optimizer_mode in incompatible_cases:
            with self.subTest(weight_mode=weight_mode, sequence=sequence, grouping=grouping, optimizer_mode=optimizer_mode):
                with (
                    patch.object(eval_module, "WEIGHT_MODE", weight_mode),
                    patch.object(eval_module, "CALIBRATION_SEQUENCE", sequence),
                    patch.object(eval_module, "GROUPING_MODE", grouping),
                    patch.object(eval_module, "resolve_optimizer_mode", return_value=optimizer_mode),
                ):
                    error = eval_module.validate_experiment_configuration()

                self.assertIsInstance(error, str)
                self.assertTrue(error)

    def test_primary_protocol_cells_generate_expected_workspace_and_contract_outputs(self) -> None:
        protocol_cases = [
            ("W8", "w8_dssat_group_max", "o6_pestpp_glm", "s2_sequential_phase", "g3_dssat_extended"),
            ("W4", "w4_min_max_equal", "o2_pestpp_ies", "s2_sequential_phase", "g3_dssat_extended"),
        ]

        for weight_code, weight_mode, engine, sequence, grouping in protocol_cases:
            with self.subTest(weight_code=weight_code, engine=engine, sequence=sequence, grouping=grouping):
                with tempfile.TemporaryDirectory() as tmpdir:
                    session_root = Path(tmpdir) / "phase1_session"
                    config_path = Path(tmpdir) / f"project_{weight_code.lower()}.json"
                    config_path.write_text(
                        json.dumps({"paths": {"dssat_case_dir": str(FIXTURE_CASE.resolve())}}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    job = {
                        "run_id": f"{weight_code}_protocol_run",
                        "combo_key": f"{weight_code}_{'O1' if engine == 'o6_pestpp_glm' else 'O2'}_S2_G3",
                        "crop": "Wheat",
                        "config_path": str(config_path),
                        "weight_code": weight_code,
                        "weight": weight_mode,
                        "engine": engine,
                        "sequence": sequence,
                        "grouping": grouping,
                        "plan": "BatchB",
                        "baseline_source": None,
                        "budget": "standard",
                        "random_seed": 42,
                        "train_only": True,
                    }

                    def fake_subprocess_run(command, env=None, cwd=None, capture_output=False, text=False):
                        workspace_dir = Path(str(cwd))
                        (workspace_dir / "run_manifest.json").write_text(
                            json.dumps(
                                {
                                    "run_id": env["AR_RUN_ID"],
                                    "requested": {
                                        "weight": env["AR_WEIGHTING"],
                                        "engine": env["AR_ENGINE"],
                                        "sequence": env["AR_SEQUENCE"],
                                        "grouping": env["AR_GROUPING"],
                                    },
                                    "resolved": {
                                        "weight": env["AR_WEIGHTING"],
                                        "engine": env["AR_ENGINE"],
                                        "sequence": env["AR_SEQUENCE"],
                                        "grouping": env["AR_GROUPING"],
                                    },
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                        (workspace_dir / "contract_report.json").write_text(
                            json.dumps(
                                {
                                    "run_id": env["AR_RUN_ID"],
                                    "requested": {"weight": env["AR_WEIGHTING"], "engine": env["AR_ENGINE"]},
                                    "resolved": {"sequence": env["AR_SEQUENCE"], "grouping": env["AR_GROUPING"]},
                                    "protocol": {
                                        "active_groups": ["obs_yield", "obs_phenology", "obs_canopy"],
                                        "primary_metric": "hwam",
                                    },
                                    "summary": {"active_groups": ["obs_yield", "obs_phenology", "obs_canopy"]},
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                        return CompletedProcess(command, 0, stdout="ok", stderr="")

                    with (
                        patch.object(phase1_runner, "python_executable", return_value="python"),
                        patch.object(phase1_runner.subprocess, "run", side_effect=fake_subprocess_run),
                    ):
                        result = phase1_runner.run_job(job, session_root)

                    workspace_dir = session_root / "workspaces" / job["run_id"]
                    self.assertEqual(result["status"], "success")
                    self.assertTrue((workspace_dir / "eval.py").exists())
                    self.assertTrue((workspace_dir / config_path.name).exists())
                    self.assertTrue((workspace_dir / "dssat_case" / "SAMPLE.WHX").exists())
                    self.assertTrue((workspace_dir / "dssat_case" / "GENOTYPE" / "SAMPLE.CUL").exists())

                    run_manifest = json.loads((workspace_dir / "run_manifest.json").read_text(encoding="utf-8"))
                    contract_report = json.loads((workspace_dir / "contract_report.json").read_text(encoding="utf-8"))
                    self.assertEqual(run_manifest["requested"]["weight"], weight_mode)
                    self.assertEqual(run_manifest["requested"]["engine"], engine)
                    self.assertEqual(run_manifest["requested"]["sequence"], sequence)
                    self.assertEqual(run_manifest["requested"]["grouping"], grouping)
                    self.assertEqual(contract_report["resolved"]["sequence"], sequence)
                    self.assertEqual(contract_report["resolved"]["grouping"], grouping)
                    self.assertEqual(contract_report["protocol"]["active_groups"], ["obs_yield", "obs_phenology", "obs_canopy"])

                    strategy_text = (workspace_dir / "strategy.py").read_text(encoding="utf-8")
                    if weight_code == "W4":
                        self.assertIn("max_err_y", strategy_text)
                    else:
                        self.assertEqual(strategy_text, phase1_runner.CURRENT_STRATEGY_SOURCE)


if __name__ == "__main__":
    unittest.main()
