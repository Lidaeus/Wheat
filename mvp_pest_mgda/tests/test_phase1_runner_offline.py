from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT.parent / "autoresearch_sandbox"
FIXTURE_CASE = Path(__file__).resolve().parent / "fixtures" / "mini_case" / "phase1_case"
if str(SANDBOX) not in sys.path:
    sys.path.insert(0, str(SANDBOX))

import phase1_runner


class TestPhase1RunnerOffline(unittest.TestCase):
    def test_build_jobs_batch_a_filters_combo_keys_and_repetitions(self) -> None:
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
                    batch="BatchA",
                    repetitions=2,
                    budget="standard",
                    crops=["Wheat"],
                    combo_keys={"W0_O1_S1_G1"},
                    train_only=False,
                )

        self.assertEqual(skipped, {})
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(job["combo_key"] == "W0_O1_S1_G1" for job in jobs))
        self.assertTrue(all(job["train_only"] is False for job in jobs))
        self.assertEqual({job["random_seed"] for job in jobs}, {42, 43})

    def test_build_jobs_all_includes_baselines_and_upgrades_b2_budget(self) -> None:
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
                    batch="All",
                    repetitions=1,
                    budget="quick",
                    crops=["Wheat"],
                    combo_keys={"B0", "B2", "W8_O1_S2_G3"},
                    train_only=True,
                )

        self.assertEqual(skipped, {})
        self.assertEqual({job["combo_key"] for job in jobs}, {"B0", "B2", "W8_O1_S2_G3"})
        budgets = {job["combo_key"]: job["budget"] for job in jobs}
        self.assertEqual(budgets["B0"], "quick")
        self.assertEqual(budgets["B2"], "standard")
        self.assertEqual(budgets["W8_O1_S2_G3"], "quick")
        self.assertTrue(all(job["train_only"] for job in jobs))

    def test_main_writes_manifest_and_invokes_postprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_root = Path(tmpdir) / "phase1_session"

            with (
                patch.object(phase1_runner, "create_session_root", return_value=session_root),
                patch.object(phase1_runner, "build_jobs", return_value=([], {"Maize": "missing_project_config"})),
                patch.object(phase1_runner.subprocess, "run") as subprocess_run_mock,
                patch.object(
                    sys,
                    "argv",
                    [
                        "phase1_runner.py",
                        "--batch",
                        "BatchA",
                        "--repetitions",
                        "1",
                        "--budget",
                        "standard",
                        "--crops",
                        "Wheat,Maize",
                        "--workers",
                        "1",
                    ],
                ),
            ):
                phase1_runner.main()

            manifest = json.loads((session_root / "phase1_run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["batch"], "BatchA")
            self.assertEqual(manifest["workers"], 1)
            self.assertEqual(manifest["job_count"], 0)
            self.assertEqual(manifest["skipped_crops"], {"Maize": "missing_project_config"})
            subprocess_run_mock.assert_called_once()

    def test_run_job_injects_env_creates_workspace_and_writes_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_root = Path(tmpdir) / "phase1_session"
            config_path = Path(tmpdir) / "project_wheat.json"
            config_path.write_text(
                json.dumps({"paths": {"dssat_case_dir": str(FIXTURE_CASE.resolve())}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            job = {
                "run_id": "W0_O1_S1_G1_wheat_rep0_abcdef",
                "combo_key": "W0_O1_S1_G1",
                "crop": "Wheat",
                "config_path": str(config_path),
                "weight_code": "W0",
                "weight": "w0_raw_identity",
                "engine": "o6_pestpp_glm",
                "sequence": "s1_naive_joint",
                "grouping": "g1_flat_all_in_one",
                "plan": "BatchA",
                "baseline_source": "external",
                "budget": "standard",
                "random_seed": 42,
                "train_only": False,
            }
            captured: dict[str, object] = {}

            def fake_subprocess_run(command, env=None, cwd=None, capture_output=False, text=False):
                captured["command"] = command
                captured["env"] = env
                captured["cwd"] = cwd
                return CompletedProcess(command, 0, stdout="fake stdout", stderr="fake stderr")

            with (
                patch.object(phase1_runner, "python_executable", return_value="python"),
                patch.object(phase1_runner.subprocess, "run", side_effect=fake_subprocess_run),
            ):
                result = phase1_runner.run_job(job, session_root)

            workspace_dir = session_root / "workspaces" / job["run_id"]
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(captured["cwd"], str(workspace_dir))
            self.assertEqual(captured["command"], ["python", str(workspace_dir / "eval.py")])
            self.assertTrue((workspace_dir / "eval.py").exists())
            self.assertTrue((workspace_dir / "project_wheat.json").exists())
            self.assertTrue((workspace_dir / "strategy.py").exists())
            self.assertTrue((workspace_dir / "dssat_case" / "SAMPLE.WHX").exists())
            self.assertTrue((workspace_dir / "dssat_case" / "GENOTYPE" / "SAMPLE.CUL").exists())
            self.assertEqual((session_root / "logs" / f"{job['run_id']}.stdout.log").read_text(encoding="utf-8"), "fake stdout")
            self.assertEqual((session_root / "logs" / f"{job['run_id']}.stderr.log").read_text(encoding="utf-8"), "fake stderr")
            env = captured["env"]
            self.assertIsInstance(env, dict)
            self.assertEqual(env["AR_WEIGHTING"], "w0_raw_identity")
            self.assertEqual(env["AR_ENGINE"], "o6_pestpp_glm")
            self.assertEqual(env["AR_SEQUENCE"], "s1_naive_joint")
            self.assertEqual(env["AR_GROUPING"], "g1_flat_all_in_one")
            self.assertEqual(env["AR_FORCE_TRAIN_ONLY"], "0")
            self.assertEqual(env["AR_BASELINE_PARAM_SOURCE"], "external")
            self.assertEqual(env["DSSAT_CASE_DIR"], str(workspace_dir / "dssat_case"))

    def test_run_job_marks_failure_and_writes_logs_when_eval_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_root = Path(tmpdir) / "phase1_session"
            config_path = Path(tmpdir) / "project_wheat.json"
            config_path.write_text(
                json.dumps({"paths": {"dssat_case_dir": str(FIXTURE_CASE.resolve())}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            job = {
                "run_id": "W0_O1_S1_G1_wheat_rep0_failed",
                "combo_key": "W0_O1_S1_G1",
                "crop": "Wheat",
                "config_path": str(config_path),
                "weight_code": "W0",
                "weight": "w0_raw_identity",
                "engine": "o6_pestpp_glm",
                "sequence": "s1_naive_joint",
                "grouping": "g1_flat_all_in_one",
                "plan": "BatchA",
                "baseline_source": None,
                "budget": "standard",
                "random_seed": 42,
                "train_only": True,
            }

            with (
                patch.object(phase1_runner, "python_executable", return_value="python"),
                patch.object(
                    phase1_runner.subprocess,
                    "run",
                    return_value=CompletedProcess(["python", "eval.py"], 2, stdout="partial", stderr="boom"),
                ),
            ):
                result = phase1_runner.run_job(job, session_root)

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["returncode"], 2)
            self.assertEqual((session_root / "logs" / f"{job['run_id']}.stdout.log").read_text(encoding="utf-8"), "partial")
            self.assertEqual((session_root / "logs" / f"{job['run_id']}.stderr.log").read_text(encoding="utf-8"), "boom")


if __name__ == "__main__":
    unittest.main()
