from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SANDBOX = ROOT.parent / "autoresearch_sandbox"
for path in (SRC, SANDBOX):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

sys.modules.setdefault("pyemu", types.ModuleType("pyemu"))

build_pest_setup = importlib.import_module("build_pest_setup")
auto_evolve = importlib.import_module("auto_evolve")
sandbox_eval = importlib.import_module("eval")
pest_builder = importlib.import_module("calibration_core.pest_builder")
core_pest_runner = importlib.import_module("calibration_core.pest_runner")
crop_registry = importlib.import_module("crop_registry")
result_schema = importlib.import_module("result_schema")


class TestGroupingContract(unittest.TestCase):
    def test_evaluation_result_round_trip_exposes_aggregate_views(self) -> None:
        result = result_schema.build_evaluation_result(
            metrics_by_trt={
                1: {"hwam": 110.0, "laix": 3.0},
                2: {"hwam": 80.0, "laix": 2.0},
            },
            observations_by_trt={
                1: {"hwam": 100.0, "laix": 2.5},
                2: {"hwam": 100.0, "laix": 2.5},
            },
            split_by_trt={1: "train", 2: "valid"},
            comparable_metrics=["hwam", "laix"],
        )

        payload_line = result_schema.build_evaluation_result_line(result)
        recovered = result_schema.extract_evaluation_result(payload_line)
        aggregate_map = result_schema.aggregate_value_map(result)

        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.metrics_by_trt[1]["hwam"], 110.0)
        self.assertAlmostEqual(aggregate_map["TRAIN_MEAN_NRMSE"], 0.15, places=6)
        self.assertAlmostEqual(
            aggregate_map["VALID_MEAN_NRMSE"],
            result.aggregate_views["valid"].mean_nrmse,
            places=6,
        )
        self.assertAlmostEqual(
            aggregate_map["ALL_MEAN_NRMSE"],
            result.aggregate_views["all"].mean_nrmse,
            places=6,
        )
        self.assertEqual(aggregate_map["TRAIN_HWAM_N"], 1.0)
        self.assertEqual(aggregate_map["VALID_LAIX_N"], 1.0)

    def test_matrix_result_prefers_unified_result_schema_payload(self) -> None:
        result = result_schema.build_evaluation_result(
            metrics_by_trt={
                1: {"hwam": 105.0},
                2: {"hwam": 95.0},
            },
            observations_by_trt={
                1: {"hwam": 100.0},
                2: {"hwam": 100.0},
            },
            split_by_trt={1: "train", 2: "valid"},
            comparable_metrics=["hwam"],
        )
        stdout = "\n".join(
            [
                "Final_Train_Score: 999.000000",
                "Final_Valid_Score: 999.000000",
                "Final_All_Score: 999.000000",
                result_schema.build_evaluation_result_line(result),
            ]
        )
        weight = auto_evolve.WeightCandidate(
            name="w-test",
            description="test",
            weight_mode="schema",
        )

        matrix_result = auto_evolve.build_matrix_result(
            run_id="run-1",
            weight=weight,
            engine="default_dssat",
            budget="quick",
            sequence="s1_naive_joint",
            grouping="g1_flat_all_in_one",
            score=1.0,
            status="ok",
            stdout=stdout,
            negative_ref_profile="baseline",
            negative_ref_score=1.0,
            yield_metric="hwam",
        )

        self.assertAlmostEqual(matrix_result.train_mean_nrmse, 0.05, places=6)
        self.assertAlmostEqual(matrix_result.valid_mean_nrmse, 0.05, places=6)
        self.assertAlmostEqual(matrix_result.all_mean_nrmse, 0.05, places=6)
        self.assertAlmostEqual(matrix_result.train_yield_bias, 0.05, places=6)
        self.assertAlmostEqual(matrix_result.valid_yield_nrmse, 0.05, places=6)

    def test_candidate_result_prefers_unified_result_schema_payload(self) -> None:
        result = result_schema.build_evaluation_result(
            metrics_by_trt={
                1: {"hwam": 105.0},
                2: {"hwam": 95.0},
            },
            observations_by_trt={
                1: {"hwam": 100.0},
                2: {"hwam": 100.0},
            },
            split_by_trt={1: "train", 2: "valid"},
            comparable_metrics=["hwam"],
        )
        stdout = "\n".join(
            [
                "Final_Train_Score: 999.000000",
                "Final_Valid_Score: 999.000000",
                "Final_All_Score: 999.000000",
                result_schema.build_evaluation_result_line(result),
            ]
        )

        with mock.patch.object(auto_evolve, "project_yield_metric", return_value="HWAM"):
            candidate = auto_evolve.build_candidate_result(
                name="schema-candidate",
                description="test",
                score=0.05,
                status="ok",
                source="unit",
                stdout=stdout,
                negative_ref_score=0.04,
            )

        self.assertAlmostEqual(candidate.train_score, 0.05, places=6)
        self.assertAlmostEqual(candidate.valid_score, 0.05, places=6)
        self.assertAlmostEqual(candidate.all_mean_nrmse, 0.05, places=6)
        self.assertAlmostEqual(candidate.valid_yield_nrmse, 0.05, places=6)
        self.assertAlmostEqual(candidate.valid_yield_bias, -0.05, places=6)

    def test_matrix_summary_view_exposes_primary_metric_fields(self) -> None:
        result = result_schema.build_evaluation_result(
            metrics_by_trt={
                1: {"hwam": 105.0, "laix": 3.0},
                2: {"hwam": 95.0, "laix": 2.0},
            },
            observations_by_trt={
                1: {"hwam": 100.0, "laix": 2.5},
                2: {"hwam": 100.0, "laix": 2.5},
            },
            split_by_trt={1: "train", 2: "valid"},
            comparable_metrics=["hwam", "laix"],
        )

        summary_view = result_schema.build_matrix_summary_view(result, "HWAM")

        self.assertEqual(summary_view.primary_metric, "hwam")
        self.assertAlmostEqual(summary_view.train_mean_nrmse, 0.125, places=6)
        self.assertAlmostEqual(summary_view.valid_mean_nrmse, 0.125, places=6)
        self.assertAlmostEqual(summary_view.train_primary_bias, 0.05, places=6)
        self.assertAlmostEqual(summary_view.valid_primary_nrmse, 0.05, places=6)

    def test_extract_matrix_summary_view_reads_shared_payload(self) -> None:
        result = result_schema.build_evaluation_result(
            metrics_by_trt={
                1: {"hwam": 105.0, "laix": 3.0},
                2: {"hwam": 95.0, "laix": 2.0},
            },
            observations_by_trt={
                1: {"hwam": 100.0, "laix": 2.5},
                2: {"hwam": 100.0, "laix": 2.5},
            },
            split_by_trt={1: "train", 2: "valid"},
            comparable_metrics=["hwam", "laix"],
        )

        summary_view = result_schema.extract_matrix_summary_view(
            result_schema.build_evaluation_result_line(result),
            "HWAM",
        )

        self.assertIsNotNone(summary_view)
        self.assertEqual(summary_view.primary_metric, "hwam")
        self.assertAlmostEqual(summary_view.train_mean_nrmse, 0.125, places=6)
        self.assertAlmostEqual(summary_view.valid_primary_bias, -0.05, places=6)

    def test_build_treatment_comparison_records_uses_shared_result_schema(self) -> None:
        result = result_schema.build_evaluation_result(
            metrics_by_trt={
                1: {"hwam": 105.0, "laix": 3.0},
                2: {"hwam": 95.0, "laix": 2.0},
            },
            observations_by_trt={
                1: {"hwam": 100.0, "laix": 2.5},
                2: {"hwam": 100.0, "laix": 2.5},
            },
            split_by_trt={1: "train", 2: "valid"},
            comparable_metrics=["hwam", "laix"],
        )

        rows = result_schema.build_treatment_comparison_records(
            result,
            observations_by_trt={
                1: {"hwam": 100.0, "laix": 2.5},
                2: {"hwam": 100.0, "laix": 2.5},
            },
            split_by_trt={1: "train", 2: "valid"},
        )

        self.assertEqual(len(rows), 4)
        train_hwam = next(row for row in rows if row.metric == "hwam" and row.trt == 1)
        valid_laix = next(row for row in rows if row.metric == "laix" and row.trt == 2)
        self.assertEqual(train_hwam.split, "train")
        self.assertAlmostEqual(train_hwam.error, 5.0, places=6)
        self.assertAlmostEqual(train_hwam.relative_error, 0.05, places=6)
        self.assertEqual(valid_laix.split, "valid")
        self.assertAlmostEqual(valid_laix.simulated, 2.0, places=6)
        self.assertAlmostEqual(valid_laix.abs_error, 0.5, places=6)

    def test_build_export_rows_and_combo_key_use_shared_result_schema(self) -> None:
        export_context = result_schema.build_experiment_export_context(
            run_id="run-1",
            plan="matrix",
            weight_name="w-test",
            engine="o1_least_squares",
            budget="quick",
            sequence="s1_naive_joint",
            grouping="g1_flat_all_in_one",
            status="ok",
        )
        comparison_rows = result_schema.build_treatment_metric_export_rows(
            export_context,
            [
                result_schema.TreatmentComparisonRecord(
                    trt=2,
                    split="VALID",
                    metric="HWAM",
                    observed=100.0,
                    simulated=95.0,
                    error=-5.0,
                    abs_error=5.0,
                    relative_error=0.05,
                )
            ],
        )
        aggregate_rows = result_schema.build_aggregate_metric_export_rows(
            export_context,
            [
                result_schema.AggregateMetricRecord(
                    split="TRAIN",
                    metric="LAIX",
                    count=3,
                    nrmse=0.2,
                    bias=0.03,
                )
            ],
        )

        self.assertEqual(
            result_schema.build_combo_key(
                "w-test",
                "o1_least_squares",
                "quick",
                "s1_naive_joint",
                "g1_flat_all_in_one",
            ),
            "w-test|o1_least_squares|quick|s1_naive_joint|g1_flat_all_in_one",
        )
        self.assertEqual(len(comparison_rows), 1)
        self.assertEqual(comparison_rows[0].split, "valid")
        self.assertEqual(comparison_rows[0].metric, "hwam")
        self.assertEqual(comparison_rows[0].weight_name, "w-test")
        self.assertEqual(
            result_schema.TREATMENT_METRIC_EXPORT_FIELDNAMES,
            [
                "run_id",
                "plan",
                "weight",
                "engine",
                "budget",
                "sequence",
                "grouping",
                "status",
                "trt",
                "split",
                "metric",
                "observed",
                "simulated",
                "error",
                "abs_error",
                "relative_error",
            ],
        )
        self.assertEqual(
            result_schema.build_treatment_metric_export_value_map(comparison_rows[0])["weight"],
            "w-test",
        )
        self.assertEqual(len(aggregate_rows), 1)
        self.assertEqual(aggregate_rows[0].split, "train")
        self.assertEqual(aggregate_rows[0].metric, "laix")
        self.assertEqual(aggregate_rows[0].count, 3)
        self.assertEqual(
            result_schema.AGGREGATE_METRIC_EXPORT_FIELDNAMES,
            [
                "run_id",
                "plan",
                "weight",
                "engine",
                "budget",
                "sequence",
                "grouping",
                "status",
                "split",
                "metric",
                "count",
                "nrmse",
                "bias",
            ],
        )
        self.assertEqual(
            result_schema.build_aggregate_metric_export_value_map(aggregate_rows[0])["count"],
            3,
        )

    def test_build_reporting_export_rows_use_shared_result_schema(self) -> None:
        run_row = {
            "run_id": "run-7",
            "executed_at": "2026-03-28T12:00:00",
            "plan": "matrix",
            "weight": "w-test",
            "engine": "o1_least_squares",
            "budget": "quick",
            "sequence": "s1_naive_joint",
            "grouping": "g1_flat_all_in_one",
            "weight_mode": "direct",
            "status": "ok",
            "yield_metric": "HWAM",
            "duration_sec": "12.5",
            "max_workers": "4",
            "validation_enabled": "true",
            "train_trts": "1",
            "valid_trts": "2",
            "workspace_dir": "D:\\runs\\case-7",
        }
        metric_row = {
            "run_id": "run-7",
            "plan": "matrix",
            "weight": "w-test",
            "engine": "o1_least_squares",
            "budget": "quick",
            "sequence": "s1_naive_joint",
            "grouping": "g1_flat_all_in_one",
            "status": "ok",
            "split": "train",
            "metric": "hwam",
            "trt": "1",
            "observed": "100.000000",
            "simulated": "95.000000",
            "error": "-5.000000",
            "abs_error": "5.000000",
            "relative_error": "0.050000",
            "combo_key": "w-test|o1_least_squares|quick|s1_naive_joint|g1_flat_all_in_one",
        }
        aggregate_metric_row = {
            "count": "3",
            "nrmse": "0.200000",
            "bias": "0.030000",
        }
        summary_row = result_schema.build_summary_export_row(
            run_row,
            combo_key="w-test|o1_least_squares|quick|s1_naive_joint|g1_flat_all_in_one",
            score=0.25,
            baseline_b0_score=0.30,
            baseline_b1_score=0.27,
            negative_ref_score=0.40,
            schema_metrics={
                "train_mean_nrmse": 0.11,
                "valid_mean_nrmse": 0.22,
                "all_mean_nrmse": 0.18,
                "train_yield_nrmse": 0.15,
                "train_yield_bias": 0.02,
                "valid_yield_nrmse": 0.19,
                "valid_yield_bias": -0.01,
            },
        )
        scatter_row = result_schema.build_scatter_export_row(
            metric_row,
            aggregate_metric_row,
            combo_key=metric_row["combo_key"],
        )
        residual_row = result_schema.build_residual_export_row(
            {**summary_row, "score_rank": "1"},
            metric="hwam",
            split="train",
            aggregate_metric_row=aggregate_metric_row,
        )
        figure_ready_row = result_schema.build_figure_ready_export_row(
            {**summary_row, "score_rank": "1"},
            metric_row,
            aggregate_metric_row,
        )

        self.assertEqual(summary_row["score"], "0.250000")
        self.assertEqual(summary_row["train_mean_nrmse"], "0.110000")
        self.assertEqual(summary_row["better_than_b0"], "true")
        self.assertEqual(result_schema.SUMMARY_EXPORT_FIELDNAMES[0:4], ["combo_key", "run_id", "score_rank", "executed_at"])
        self.assertEqual(scatter_row["count"], "3")
        self.assertEqual(scatter_row["metric"], "hwam")
        self.assertEqual(result_schema.SCATTER_EXPORT_FIELDNAMES[-3:], ["count", "nrmse", "bias"])
        self.assertEqual(residual_row["score_rank"], "1")
        self.assertEqual(residual_row["nrmse"], "0.200000")
        self.assertEqual(
            result_schema.build_residual_export_fieldnames([1, 2]),
            result_schema.RESIDUAL_EXPORT_BASE_FIELDNAMES + ["trt_1", "trt_2"],
        )
        self.assertEqual(figure_ready_row["panel_key"], "hwam|train")
        self.assertEqual(figure_ready_row["point_key"], "run-7|hwam|t1")
        self.assertEqual(
            result_schema.FIGURE_READY_EXPORT_FIELDNAMES[-3:],
            ["panel_count", "panel_nrmse", "panel_bias"],
        )

    def test_build_aggregate_metric_rows_uses_shared_result_schema(self) -> None:
        result = result_schema.build_evaluation_result(
            metrics_by_trt={
                1: {"hwam": 105.0, "laix": 3.0},
                2: {"hwam": 95.0, "laix": 2.0},
            },
            observations_by_trt={
                1: {"hwam": 100.0, "laix": 2.5},
                2: {"hwam": 100.0, "laix": 2.5},
            },
            split_by_trt={1: "train", 2: "valid"},
            comparable_metrics=["hwam", "laix"],
        )

        rows = auto_evolve.build_aggregate_metric_rows(
            run_id="run-agg",
            plan="matrix",
            weight_name="w-test",
            engine="o1_least_squares",
            budget="quick",
            sequence="s1_naive_joint",
            grouping="g1_flat_all_in_one",
            status="ok",
            stdout=result_schema.build_evaluation_result_line(result),
        )

        self.assertEqual(len(rows), 6)
        train_hwam = next(row for row in rows if row.split == "train" and row.metric == "hwam")
        self.assertEqual(train_hwam.run_id, "run-agg")
        self.assertEqual(train_hwam.count, 1)
        self.assertAlmostEqual(train_hwam.nrmse, 0.05, places=6)
        self.assertAlmostEqual(train_hwam.bias, 0.05, places=6)

    def test_append_experiment_aggregate_metrics_tsv_writes_standardized_export(self) -> None:
        result = auto_evolve.MatrixResult(
            run_id="run-agg",
            weight_name="w-test",
            engine="o1_least_squares",
            budget="quick",
            sequence="s1_naive_joint",
            grouping="g1_flat_all_in_one",
            score=0.1,
            status="ok",
            weight_mode="schema",
            stdout="",
            negative_ref_profile="baseline",
            negative_ref_score=0.2,
            train_mean_nrmse=0.1,
            valid_mean_nrmse=0.2,
            all_mean_nrmse=0.15,
            yield_metric="HWAM",
            train_yield_nrmse=0.1,
            train_yield_bias=0.0,
            valid_yield_nrmse=0.2,
            valid_yield_bias=0.0,
            aggregate_rows=[
                auto_evolve.AggregateMetricRow(
                    run_id="run-agg",
                    plan="matrix",
                    weight_name="w-test",
                    engine="o1_least_squares",
                    budget="quick",
                    sequence="s1_naive_joint",
                    grouping="g1_flat_all_in_one",
                    status="ok",
                    split="train",
                    metric="hwam",
                    count=1,
                    nrmse=0.1,
                    bias=0.02,
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "experiment_aggregate_metrics.tsv"
            with mock.patch.object(auto_evolve, "EXPERIMENT_AGGREGATE_METRICS_TSV_PATH", export_path):
                auto_evolve.append_experiment_aggregate_metrics_tsv(result)

            content = export_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(
            content[0],
            "run_id\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tstatus\tsplit\tmetric\tcount\tnrmse\tbias",
        )
        self.assertEqual(
            content[1],
            "run-agg\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\ttrain\thwam\t1\t0.100000\t0.020000",
        )

    def test_rebuild_experiment_summary_exports_includes_schema_aggregate_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_path = tmp_path / "experiment_runs.tsv"
            aggregate_path = tmp_path / "experiment_aggregate_metrics.tsv"
            summary_path = tmp_path / "experiment_summary.tsv"
            scatter_path = tmp_path / "experiment_scatter_1to1.tsv"
            heatmap_path = tmp_path / "experiment_heatmap_wide.tsv"
            metric_split_path = tmp_path / "experiment_metric_split_heatmap.tsv"
            residuals_path = tmp_path / "experiment_residuals_wide.tsv"
            figure_ready_path = tmp_path / "experiment_figure_ready.tsv"

            runs_path.write_text(
                "\n".join(
                    [
                        "run_id\texecuted_at\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tweight_mode\tstatus\t"
                        "score\tnegative_ref_profile\tnegative_ref_score\tbaseline_b0_score\tbaseline_b1_score\t"
                        "yield_metric\ttrain_mean_nrmse\tvalid_mean_nrmse\tall_mean_nrmse\t"
                        "train_yield_nrmse\ttrain_yield_bias\tvalid_yield_nrmse\tvalid_yield_bias\t"
                        "duration_sec\tmax_workers\tvalidation_enabled\ttrain_trts\tvalid_trts\t"
                        "workspace_dir\tstrategy_hash\teval_hash\tauto_evolve_hash",
                        "run-agg\t2026-03-28T12:00:00\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\t"
                        "schema\tok\t0.100000\tbaseline\t0.150000\t0.120000\t0.110000\tHWAM\t0.100000\t0.200000\t0.150000\t"
                        "0.100000\t0.020000\t0.200000\t-0.010000\t1.000000\t1\ttrue\t1\t2\td:\\tmp\tstrategy\teval\tauto",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            aggregate_path.write_text(
                "\n".join(
                    [
                        "run_id\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tstatus\tsplit\tmetric\tcount\tnrmse\tbias",
                        "run-agg\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\ttrain\thwam\t1\t0.100000\t0.020000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(auto_evolve, "EXPERIMENT_RUNS_TSV_PATH", runs_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_AGGREGATE_METRICS_TSV_PATH", aggregate_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_METRICS_LONG_TSV_PATH", tmp_path / "experiment_metrics_long.tsv"),
                mock.patch.object(auto_evolve, "EXPERIMENT_SUMMARY_TSV_PATH", summary_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_SCATTER_1TO1_TSV_PATH", scatter_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_HEATMAP_WIDE_TSV_PATH", heatmap_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_METRIC_SPLIT_HEATMAP_TSV_PATH", metric_split_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_RESIDUALS_WIDE_TSV_PATH", residuals_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_FIGURE_READY_TSV_PATH", figure_ready_path),
                mock.patch.object(auto_evolve, "project_observation_bundle", return_value=([1, 2], {}, {})),
            ):
                auto_evolve.rebuild_experiment_summary_exports()

            with metric_split_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(auto_evolve.csv.DictReader(handle, delimiter="\t"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hwam|train|count"], "1")
        self.assertEqual(rows[0]["hwam|train|nrmse"], "0.100000")
        self.assertEqual(rows[0]["hwam|train|bias"], "0.020000")

    def test_rebuild_experiment_summary_exports_prefers_schema_aggregate_summary_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_path = tmp_path / "experiment_runs.tsv"
            aggregate_path = tmp_path / "experiment_aggregate_metrics.tsv"
            summary_path = tmp_path / "experiment_summary.tsv"

            runs_path.write_text(
                "\n".join(
                    [
                        "run_id\texecuted_at\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tweight_mode\tstatus\t"
                        "score\tnegative_ref_profile\tnegative_ref_score\tbaseline_b0_score\tbaseline_b1_score\t"
                        "yield_metric\ttrain_mean_nrmse\tvalid_mean_nrmse\tall_mean_nrmse\t"
                        "train_yield_nrmse\ttrain_yield_bias\tvalid_yield_nrmse\tvalid_yield_bias\t"
                        "duration_sec\tmax_workers\tvalidation_enabled\ttrain_trts\tvalid_trts\t"
                        "workspace_dir\tstrategy_hash\teval_hash\tauto_evolve_hash",
                        "run-agg\t2026-03-28T12:00:00\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\t"
                        "schema\tok\t0.100000\tbaseline\t0.150000\t0.120000\t0.110000\tHWAM\t9.900000\t9.800000\t9.700000\t"
                        "9.600000\t9.500000\t9.400000\t9.300000\t1.000000\t1\ttrue\t1\t2\td:\\tmp\tstrategy\teval\tauto",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            aggregate_path.write_text(
                "\n".join(
                    [
                        "run_id\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tstatus\tsplit\tmetric\tcount\tnrmse\tbias",
                        "run-agg\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\ttrain\thwam\t1\t0.100000\t0.020000",
                        "run-agg\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\ttrain\tlaix\t1\t0.300000\t0.040000",
                        "run-agg\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\tvalid\thwam\t1\t0.200000\t-0.010000",
                        "run-agg\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\tvalid\tlaix\t1\t0.400000\t0.030000",
                        "run-agg\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\tall\thwam\t2\t0.150000\t0.005000",
                        "run-agg\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\tall\tlaix\t2\t0.350000\t0.035000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(auto_evolve, "EXPERIMENT_RUNS_TSV_PATH", runs_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_AGGREGATE_METRICS_TSV_PATH", aggregate_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_METRICS_LONG_TSV_PATH", tmp_path / "experiment_metrics_long.tsv"),
                mock.patch.object(auto_evolve, "EXPERIMENT_SUMMARY_TSV_PATH", summary_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_SCATTER_1TO1_TSV_PATH", tmp_path / "experiment_scatter_1to1.tsv"),
                mock.patch.object(auto_evolve, "EXPERIMENT_HEATMAP_WIDE_TSV_PATH", tmp_path / "experiment_heatmap_wide.tsv"),
                mock.patch.object(
                    auto_evolve,
                    "EXPERIMENT_METRIC_SPLIT_HEATMAP_TSV_PATH",
                    tmp_path / "experiment_metric_split_heatmap.tsv",
                ),
                mock.patch.object(auto_evolve, "EXPERIMENT_RESIDUALS_WIDE_TSV_PATH", tmp_path / "experiment_residuals_wide.tsv"),
                mock.patch.object(auto_evolve, "EXPERIMENT_FIGURE_READY_TSV_PATH", tmp_path / "experiment_figure_ready.tsv"),
                mock.patch.object(auto_evolve, "project_observation_bundle", return_value=([1, 2], {}, {})),
            ):
                auto_evolve.rebuild_experiment_summary_exports()

            with summary_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(auto_evolve.csv.DictReader(handle, delimiter="\t"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["train_mean_nrmse"], "0.200000")
        self.assertEqual(rows[0]["valid_mean_nrmse"], "0.300000")
        self.assertEqual(rows[0]["all_mean_nrmse"], "0.250000")
        self.assertEqual(rows[0]["train_yield_nrmse"], "0.100000")
        self.assertEqual(rows[0]["train_yield_bias"], "0.020000")
        self.assertEqual(rows[0]["valid_yield_nrmse"], "0.200000")
        self.assertEqual(rows[0]["valid_yield_bias"], "-0.010000")

    def test_rebuild_experiment_summary_exports_propagates_schema_panel_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_path = tmp_path / "experiment_runs.tsv"
            aggregate_path = tmp_path / "experiment_aggregate_metrics.tsv"
            metrics_long_path = tmp_path / "experiment_metrics_long.tsv"
            summary_path = tmp_path / "experiment_summary.tsv"
            scatter_path = tmp_path / "experiment_scatter_1to1.tsv"
            residuals_path = tmp_path / "experiment_residuals_wide.tsv"
            figure_ready_path = tmp_path / "experiment_figure_ready.tsv"

            runs_path.write_text(
                "\n".join(
                    [
                        "run_id\texecuted_at\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tweight_mode\tstatus\t"
                        "score\tnegative_ref_profile\tnegative_ref_score\tbaseline_b0_score\tbaseline_b1_score\t"
                        "yield_metric\ttrain_mean_nrmse\tvalid_mean_nrmse\tall_mean_nrmse\t"
                        "train_yield_nrmse\ttrain_yield_bias\tvalid_yield_nrmse\tvalid_yield_bias\t"
                        "duration_sec\tmax_workers\tvalidation_enabled\ttrain_trts\tvalid_trts\t"
                        "workspace_dir\tstrategy_hash\teval_hash\tauto_evolve_hash",
                        "run-panel\t2026-03-28T12:00:00\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\t"
                        "schema\tok\t0.100000\tbaseline\t0.150000\t0.120000\t0.110000\tHWAM\t0.100000\t0.200000\t0.150000\t"
                        "0.100000\t0.020000\t0.200000\t-0.010000\t1.000000\t1\ttrue\t1\t2\td:\\tmp\tstrategy\teval\tauto",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            aggregate_path.write_text(
                "\n".join(
                    [
                        "run_id\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tstatus\tsplit\tmetric\tcount\tnrmse\tbias",
                        "run-panel\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\ttrain\thwam\t2\t0.100000\t0.020000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            metrics_long_path.write_text(
                "\n".join(
                    [
                        "run_id\tcombo_key\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tstatus\tmetric\tsplit\ttrt\tobserved\tsimulated\terror\tabs_error\trelative_error",
                        "run-panel\tmatrix|w-test|o1_least_squares|quick|s1_naive_joint|g1_flat_all_in_one\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\thwam\ttrain\t1\t100.000000\t98.000000\t-2.000000\t2.000000\t-0.020000",
                        "run-panel\tmatrix|w-test|o1_least_squares|quick|s1_naive_joint|g1_flat_all_in_one\tmatrix\tw-test\to1_least_squares\tquick\ts1_naive_joint\tg1_flat_all_in_one\tok\thwam\ttrain\t2\t110.000000\t112.000000\t2.000000\t2.000000\t0.018182",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(auto_evolve, "EXPERIMENT_RUNS_TSV_PATH", runs_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_AGGREGATE_METRICS_TSV_PATH", aggregate_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_METRICS_LONG_TSV_PATH", metrics_long_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_SUMMARY_TSV_PATH", summary_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_SCATTER_1TO1_TSV_PATH", scatter_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_HEATMAP_WIDE_TSV_PATH", tmp_path / "experiment_heatmap_wide.tsv"),
                mock.patch.object(
                    auto_evolve,
                    "EXPERIMENT_METRIC_SPLIT_HEATMAP_TSV_PATH",
                    tmp_path / "experiment_metric_split_heatmap.tsv",
                ),
                mock.patch.object(auto_evolve, "EXPERIMENT_RESIDUALS_WIDE_TSV_PATH", residuals_path),
                mock.patch.object(auto_evolve, "EXPERIMENT_FIGURE_READY_TSV_PATH", figure_ready_path),
                mock.patch.object(auto_evolve, "project_observation_bundle", return_value=([1, 2], {}, {})),
            ):
                auto_evolve.rebuild_experiment_summary_exports()

            with scatter_path.open("r", encoding="utf-8", newline="") as handle:
                scatter_rows = list(auto_evolve.csv.DictReader(handle, delimiter="\t"))
            with residuals_path.open("r", encoding="utf-8", newline="") as handle:
                residual_rows = list(auto_evolve.csv.DictReader(handle, delimiter="\t"))
            with figure_ready_path.open("r", encoding="utf-8", newline="") as handle:
                figure_ready_rows = list(auto_evolve.csv.DictReader(handle, delimiter="\t"))

        self.assertEqual(len(scatter_rows), 2)
        self.assertEqual(scatter_rows[0]["count"], "2")
        self.assertEqual(scatter_rows[0]["nrmse"], "0.100000")
        self.assertEqual(scatter_rows[0]["bias"], "0.020000")
        self.assertEqual(len(residual_rows), 1)
        self.assertEqual(residual_rows[0]["count"], "2")
        self.assertEqual(residual_rows[0]["nrmse"], "0.100000")
        self.assertEqual(residual_rows[0]["bias"], "0.020000")
        self.assertEqual(residual_rows[0]["trt_1"], "-2.000000")
        self.assertEqual(residual_rows[0]["trt_2"], "2.000000")
        self.assertEqual(len(figure_ready_rows), 2)
        self.assertEqual(figure_ready_rows[0]["panel_count"], "2")
        self.assertEqual(figure_ready_rows[0]["panel_nrmse"], "0.100000")
        self.assertEqual(figure_ready_rows[0]["panel_bias"], "0.020000")

    def test_build_pst_via_script_uses_shared_runner_contract(self) -> None:
        calls: list[tuple[list[str], Path, dict[str, str], str]] = []

        def fake_run_process(command, working_dir, env, label):
            calls.append((command, working_dir, env, label))
            return "ok"

        result = pest_builder.build_pst_via_script(
            script_path=Path(r"d:\tmp\build_pest_setup.py"),
            working_dir=Path(r"d:\tmp\sandbox"),
            env={"PEST_NOPTMAX": "2"},
            run_process_fn=fake_run_process,
            python_executable="python-custom",
            label="pest-build",
        )

        self.assertEqual(result, "ok")
        self.assertEqual(
            calls,
            [
                (
                    ["python-custom", r"d:\tmp\build_pest_setup.py"],
                    Path(r"d:\tmp\sandbox"),
                    {"PEST_NOPTMAX": "2"},
                    "pest-build",
                )
            ],
        )

    def test_run_build_pest_setup_resolves_shared_entrypoint(self) -> None:
        calls: list[tuple[str, Path, Path, dict[str, str], str]] = []

        def fake_run_python_entrypoint(python_executable, script_path, working_dir, env, label, args=None):
            calls.append((python_executable, script_path, working_dir, env, label))
            request_path = Path(env["AR_RUNTIME_REQUEST_PATH"])
            request_payload = json.loads(request_path.read_text(encoding="utf-8"))
            self.assertEqual(request_payload["purpose"], "build_pest_setup")
            self.assertEqual(request_payload["script_path"], str(script_path))
            self.assertEqual(request_payload["env"]["PEST_NOPTMAX"], "2")
            self.assertEqual(args, ["--runtime-request", str(request_path)])
            return "ok"

        with tempfile.TemporaryDirectory() as tmp:
            working_dir = Path(tmp)
            with mock.patch("calibration_core.pest_runner.run_python_entrypoint", side_effect=fake_run_python_entrypoint):
                result = pest_builder.run_build_pest_setup(
                    working_dir=working_dir,
                    env={"PEST_NOPTMAX": "2"},
                    python_executable="python-custom",
                )

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)
        python_executable, script_path, working_dir, env, label = calls[0]
        self.assertEqual(python_executable, "python-custom")
        self.assertEqual(script_path, pest_builder.resolve_build_pest_setup_script())
        self.assertEqual(working_dir, Path(tmp))
        self.assertIn("AR_RUNTIME_REQUEST_PATH", env)
        self.assertEqual(label, "build_pest_setup.py")

    def test_shared_script_resolvers_point_to_project_entrypoints(self) -> None:
        self.assertEqual(pest_builder.resolve_build_pest_setup_script().name, "build_pest_setup.py")
        self.assertEqual(core_pest_runner.resolve_run_model_script().name, "run_model.py")

    def test_g3_extended_group_names_follow_default_contract(self) -> None:
        group_defs = dict(build_pest_setup.DEFAULT_OBSERVATION_GROUPS)

        self.assertEqual(
            build_pest_setup._resolve_obs_group_name("adap_t01", group_defs, "hwam", "laix"),
            "obs_phenology",
        )
        self.assertEqual(
            build_pest_setup._resolve_obs_group_name("cwam_t01", group_defs, "hwam", "laix"),
            "obs_biomass",
        )
        self.assertEqual(
            build_pest_setup._resolve_obs_group_name("laix_t01", group_defs, "hwam", "laix"),
            "obs_canopy",
        )
        self.assertEqual(
            build_pest_setup._resolve_obs_group_name("hwam_t01", group_defs, "hwam", "laix"),
            "obs_yield",
        )
        self.assertEqual(
            build_pest_setup._resolve_obs_group_name("hwum_t01", group_defs, "hwam", "laix"),
            "obs_yield_unit_weight",
        )

    def test_build_pest_setup_defaults_now_come_from_crop_registry(self) -> None:
        wheat_profile = crop_registry.get_crop_profile("wheat")

        self.assertEqual(
            build_pest_setup.DEFAULT_OBSERVATION_GROUPS,
            wheat_profile.observation_groups_config(),
        )
        self.assertEqual(
            build_pest_setup.SUMMARY_AFILE_COLUMN_MAP,
            wheat_profile.summary_afile_column_map(),
        )

    def test_crop_registry_profiles_drive_auto_evolve_sequence_and_grouping_resolution(self) -> None:
        self.assertEqual(
            crop_registry.resolve_groupings_for_sequence("wheat", "s3_wls_joint"),
            ("g3_dssat_extended",),
        )
        self.assertEqual(
            crop_registry.resolve_phase_template("wheat", "phase2"),
            ("s2_sequential_phase", "s3_wls_joint"),
        )
        self.assertEqual(
            auto_evolve.compatible_groupings_for_sequence("s2_sequential_phase"),
            ["g1_flat_all_in_one", "g3_dssat_extended"],
        )
        self.assertEqual(
            auto_evolve.phase_sequences_for_plan("phase3"),
            ["s2_sequential_phase"],
        )

    def test_crop_registry_read_only_api_exposes_supported_families_and_aliases(self) -> None:
        self.assertEqual(
            crop_registry.iter_supported_crops(),
            ("wheat", "maize", "rice", "cabbage", "cassava", "potato", "soybean", "cotton", "sunflower"),
        )
        self.assertEqual(crop_registry.resolve_crop_alias("corn"), "maize")
        self.assertEqual(crop_registry.resolve_crop_alias("SB"), "soybean")
        self.assertEqual(crop_registry.resolve_crop_alias("co"), "cotton")
        self.assertEqual(crop_registry.iter_crop_aliases("corn"), ("maize", "mz", "corn"))
        self.assertEqual(crop_registry.iter_crop_aliases("soy"), ("soybean", "sb", "soy"))
        self.assertEqual(crop_registry.resolve_trial_prefixes("wheat"), ("WH",))
        self.assertEqual(crop_registry.resolve_trial_prefixes("rice"), ("RI",))

    def test_crop_registry_multi_crop_profiles_preserve_core_contract_fields(self) -> None:
        expected_profiles = {
            "wheat": ("WH", "WHCER048.CUL"),
            "maize": ("MZ", "MZCER048.CUL"),
            "rice": ("RI", "RICER048.CUL"),
            "cabbage": ("CB", "CBGRO048.CUL"),
            "cassava": ("CS", "CSCAS048.CUL"),
            "potato": ("PT", "PTSUB048.CUL"),
            "soybean": ("SB", "SBGRO048.CUL"),
            "cotton": ("CO", "COGRO048.CUL"),
        }

        for family, (trial_prefix, cultivar_file) in expected_profiles.items():
            with self.subTest(crop=family):
                profile = crop_registry.get_crop_profile(family)
                self.assertEqual(profile.family, family)
                self.assertIn(family, crop_registry.iter_crop_aliases(family))
                self.assertEqual(profile.trial_prefixes, (trial_prefix,))
                self.assertEqual(crop_registry.resolve_trial_prefixes(family), (trial_prefix,))
                self.assertEqual(profile.cultivar_file, cultivar_file)
                self.assertEqual(crop_registry.resolve_cultivar_file_by_trial_prefix(trial_prefix), cultivar_file)
                self.assertTrue(profile.yield_metric)
                self.assertTrue(profile.laix_metric)
                self.assertTrue(profile.timeseries_metrics)
                self.assertTrue(profile.summary_afile_columns)
                self.assertTrue(profile.grouping_profiles)
                self.assertTrue(profile.phase_templates)

    def test_crop_registry_profile_snapshots_expose_stable_cross_crop_contract(self) -> None:
        snapshots = {
            str(row["family"]): row
            for row in crop_registry.iter_crop_profile_snapshots()
        }

        self.assertEqual(tuple(snapshots), crop_registry.iter_supported_crops())
        self.assertEqual(
            tuple(next(iter(snapshots.values())).keys()),
            crop_registry.CROP_PROFILE_SNAPSHOT_FIELDNAMES,
        )
        self.assertEqual(snapshots["wheat"]["display_name"], "Wheat")
        self.assertEqual(snapshots["wheat"]["aliases"], ("wheat", "wh"))
        self.assertEqual(snapshots["wheat"]["trial_prefixes"], ("WH",))
        self.assertEqual(
            snapshots["wheat"]["summary_afile_columns"],
            (
                ("HWAM", "HWAM"),
                ("HWUM", "HWUM"),
                ("LAIX", "LAIX"),
                ("CWAM", "CWAM"),
                ("ADAP", "ADAT"),
                ("MDAP", "MDAT"),
            ),
        )
        self.assertEqual(snapshots["maize"]["display_name"], "Maize")
        self.assertEqual(snapshots["maize"]["trial_prefixes"], ("MZ",))
        self.assertEqual(snapshots["soybean"]["aliases"], ("soybean", "sb", "soy"))
        self.assertEqual(snapshots["cotton"]["display_name"], "Cotton")
        self.assertEqual(snapshots["cotton"]["trial_prefixes"], ("CO",))
        self.assertEqual(snapshots["cotton"]["cultivar_file"], "COGRO048.CUL")
        self.assertEqual(snapshots["sunflower"]["display_name"], "Sunflower")
        self.assertEqual(snapshots["sunflower"]["trial_prefixes"], ())
        self.assertEqual(snapshots["sunflower"]["cultivar_file"], "")
        self.assertEqual(
            snapshots["sunflower"]["parameter_order"],
            ("ppsen", "sfdur", "slavr", "wtpsd", "xfrt"),
        )
        self.assertEqual(
            snapshots["sunflower"]["grouping_profiles"],
            crop_registry.get_crop_profile("sunflower").grouping_profiles,
        )

    def test_crop_registry_profile_snapshot_golden_subset_remains_stable(self) -> None:
        golden_rows = tuple(
            (
                str(row["family"]),
                str(row["display_name"]),
                tuple(row["aliases"]),
                tuple(row["trial_prefixes"]),
                str(row["cultivar_file"]),
            )
            for row in crop_registry.iter_crop_profile_snapshots()
        )
        self.assertEqual(
            golden_rows,
            (
                ("wheat", "Wheat", ("wheat", "wh"), ("WH",), "WHCER048.CUL"),
                ("maize", "Maize", ("maize", "mz", "corn"), ("MZ",), "MZCER048.CUL"),
                ("rice", "Rice", ("rice", "ri"), ("RI",), "RICER048.CUL"),
                ("cabbage", "Cabbage", ("cabbage", "cb"), ("CB",), "CBGRO048.CUL"),
                ("cassava", "Cassava", ("cassava", "cs"), ("CS",), "CSCAS048.CUL"),
                ("potato", "Potato", ("potato", "pt"), ("PT",), "PTSUB048.CUL"),
                ("soybean", "Soybean", ("soybean", "sb", "soy"), ("SB",), "SBGRO048.CUL"),
                ("cotton", "Cotton", ("cotton", "co"), ("CO",), "COGRO048.CUL"),
                ("sunflower", "Sunflower", ("sunflower",), (), ""),
            ),
        )

    def test_multi_crop_project_configs_align_with_registry_filex_and_cultivar_contracts(self) -> None:
        config_dir = ROOT / "config" / "multi"
        for cfg_path in sorted(config_dir.glob("project_*.json")):
            payload = json.loads(cfg_path.read_text(encoding="utf-8"))
            family = crop_registry.resolve_crop_alias(payload["crop_family"])
            profile = crop_registry.get_crop_profile(family)
            scenario = payload.get("scenario", {})
            paths = payload.get("paths", {})
            filex_name = str(scenario.get("filex", "")).strip()
            base_filex_name = str(scenario.get("base_filex", "")).strip()
            cul_name = Path(str(paths.get("cul_path", "")).strip()).name
            bounds = payload.get("params", {}).get("bounds", {})

            with self.subTest(config=cfg_path.name, family=family):
                self.assertEqual(cul_name, profile.cultivar_file)
                self.assertTrue(filex_name.upper().endswith("X"))
                self.assertTrue(base_filex_name.upper().endswith("X"))
                self.assertEqual(filex_name[-3:-1].upper(), profile.trial_prefixes[0])
                self.assertEqual(base_filex_name[-3:-1].upper(), profile.trial_prefixes[0])
                self.assertIsInstance(bounds, dict)
                self.assertTrue(bounds)
                for name, raw_bound in bounds.items():
                    self.assertTrue(str(name).strip())
                    self.assertIsInstance(raw_bound, list)
                    self.assertGreaterEqual(len(raw_bound), 3)
                    self.assertLessEqual(float(raw_bound[0]), float(raw_bound[1]))
                    self.assertTrue(str(raw_bound[2]).strip())

    def test_main_matrix_appendix_contract_maps_follow_panel_specs(self) -> None:
        output_map = auto_evolve.build_main_matrix_appendix_output_map()
        row_map = auto_evolve.build_main_matrix_appendix_row_map(
            paper_rows=[{"panel": "paper"}],
            protocol_panel_rows=[{"panel": "protocol"}],
            protocol_reason_rows=[{"reason_kind": "dropped_group"}],
            topk_by_engine_rows=[{"panel": "engine"}],
            topk_by_weight_rows=[{"panel": "weight"}],
            topk_by_sequence_rows=[{"panel": "sequence"}],
            topk_by_grouping_rows=[{"panel": "grouping"}],
            validation_only_rows=[{"panel": "validation"}],
            topk_by_budget_rows=[{"panel": "budget"}],
            topk_by_validation_budget_rows=[{"panel": "validation_budget"}],
            topk_improvement_rows=[{"panel": "improvement"}],
        )
        panel_inputs = auto_evolve.build_main_matrix_appendix_panel_inputs(
            paper_rows=[{"panel": "paper"}],
            protocol_panel_rows=[{"panel": "protocol"}],
            protocol_reason_rows=[{"reason_kind": "dropped_group"}],
            topk_by_engine_rows=[{"panel": "engine"}],
            topk_by_weight_rows=[{"panel": "weight"}],
            topk_by_sequence_rows=[{"panel": "sequence"}],
            topk_by_grouping_rows=[{"panel": "grouping"}],
            validation_only_rows=[{"panel": "validation"}],
            topk_by_budget_rows=[{"panel": "budget"}],
            topk_by_validation_budget_rows=[{"panel": "validation_budget"}],
            topk_improvement_rows=[{"panel": "improvement"}],
        )

        self.assertEqual(tuple(output_map), auto_evolve.MAIN_MATRIX_APPENDIX_PANEL_KEYS)
        self.assertEqual(tuple(row_map), auto_evolve.MAIN_MATRIX_APPENDIX_PANEL_KEYS)
        self.assertEqual(
            auto_evolve.MAIN_MATRIX_APPENDIX_PANEL_KEYS,
            tuple(spec[0] for spec in auto_evolve.MAIN_MATRIX_APPENDIX_PANEL_SPECS),
        )
        self.assertEqual(output_map["paper_appendix_table"], auto_evolve.MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH)
        self.assertEqual(output_map["protocol_paper_table"], auto_evolve.MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH)
        self.assertEqual(
            output_map["protocol_reason_summary"],
            auto_evolve.MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH,
        )
        self.assertEqual(row_map["protocol_reason_summary"], [{"reason_kind": "dropped_group"}])
        self.assertEqual(row_map["topk_by_validation_budget"], [{"panel": "validation_budget"}])
        self.assertEqual(
            [panel_key for panel_key, *_ in panel_inputs],
            list(auto_evolve.MAIN_MATRIX_APPENDIX_PANEL_KEYS),
        )
        self.assertEqual(panel_inputs[0][3], auto_evolve.MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH)
        self.assertEqual(panel_inputs[0][4], [{"panel": "paper"}])
        self.assertEqual(panel_inputs[2][3], auto_evolve.MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH)
        self.assertEqual(panel_inputs[2][4], [{"reason_kind": "dropped_group"}])
        self.assertEqual(panel_inputs[-1][3], auto_evolve.MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH)
        self.assertEqual(panel_inputs[-1][4], [{"panel": "improvement"}])

    def test_protocol_reason_summary_rows_aggregate_reason_kind_and_examples(self) -> None:
        scoped_rows = [
            (
                "paper_selected",
                [
                    {"run_id": "run_a"},
                    {"run_id": "run_b"},
                    {"run_id": "run_c"},
                ],
            )
        ]
        protocol_rows_by_run_id = {
            "run_a": {
                "dropped_groups": "obs_biomass:no_train_observations",
                "weight_fallbacks": "obs_yield:variance_unavailable_used_sigma",
                "zero_weight_observations": "hwam_t01:missing_weight",
            },
            "run_b": {
                "dropped_groups": "obs_biomass:no_train_observations",
                "weight_fallbacks": "obs_canopy:variance_and_sigma_unavailable_used_configured_weight",
                "zero_weight_observations": "hwam_t01:missing_weight,laix_t01:zero_sigma",
            },
            "run_c": {
                "dropped_groups": "obs_stage:",
            },
        }

        rows = auto_evolve.build_main_matrix_protocol_reason_summary_rows(
            scoped_rows,
            protocol_rows_by_run_id,
        )

        row_map = {
            (str(row["reason_kind"]), str(row["reason"])): row
            for row in rows
        }
        dropped_row = row_map[("dropped_group", "no_train_observations")]
        self.assertEqual(dropped_row["affected_runs"], "2")
        self.assertEqual(dropped_row["total_occurrences"], "2")
        self.assertEqual(dropped_row["affected_entities"], "obs_biomass")
        self.assertEqual(dropped_row["example_run_ids"], "run_a,run_b")
        self.assertEqual(
            row_map[("dropped_group", "unspecified")]["affected_entities"],
            "obs_stage",
        )
        self.assertEqual(
            row_map[("weight_fallback", "variance_unavailable_used_sigma")]["affected_runs"],
            "1",
        )
        self.assertEqual(
            row_map[("zero_weight_observation", "missing_weight")]["affected_runs"],
            "2",
        )
        self.assertEqual(rows[0]["reason_kind"], "dropped_group")

    def test_render_main_matrix_report_includes_registry_summary_and_protocol_reason_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            report_text = auto_evolve.render_main_matrix_report_markdown(
                leaderboard_rows=[
                    {
                        "run_id": "run_001",
                        "status": "ok",
                        "sequence": "s2_sequential_phase",
                    }
                ],
                dimension_rows=[],
                baseline_summary_rows=[],
                baseline_detail_rows=[],
                key_indicator_rows=[],
                baseline_winner_rows=[],
                metric_snapshot_rows=[],
                paper_summary_rows=[],
                protocol_overview_rows=[],
                protocol_dimension_rows=[
                    {
                        "selection_scope": "leaderboard_all",
                        "dimension": "weight",
                        "value": "W1",
                        "total_runs": "1",
                        "ok_contract_runs": "0",
                        "degraded_contract_runs": "1",
                        "missing_contract_runs": "0",
                        "rows_with_dropped_groups": "1",
                        "rows_with_weight_fallbacks": "0",
                        "rows_with_zero_weight_observations": "0",
                        "total_dropped_group_count": "1",
                        "total_weight_fallback_count": "0",
                        "total_zero_weight_observation_count": "0",
                    }
                ],
                protocol_nested_dimension_rows=[
                    {
                        "selection_scope": "leaderboard_all",
                        "dimension_depth": "4",
                        "dimensions": "weight|engine|sequence|grouping",
                        "values": "W1|o2|s2_sequential_phase|g3_dssat_extended",
                        "total_runs": "1",
                        "ok_contract_runs": "0",
                        "degraded_contract_runs": "1",
                        "missing_contract_runs": "0",
                        "total_dropped_group_count": "1",
                        "total_weight_fallback_count": "0",
                        "total_zero_weight_observation_count": "2",
                    }
                ],
                protocol_reason_rows=[
                    {
                        "selection_scope": "paper_selected",
                        "reason_kind": "dropped_group",
                        "reason": "no_train_observations",
                        "affected_runs": "1",
                        "total_occurrences": "1",
                        "affected_entities": "obs_biomass",
                        "example_run_ids": "run_001",
                    }
                ],
                quality_gate_rows=[],
                appendix_index_rows=[],
                protocol_panel_rows=[],
                paper_main_rows=[],
                paper_rows=[],
                topk_overall_rows=[],
                topk_by_engine_rows=[],
                topk_by_weight_rows=[],
                topk_by_sequence_rows=[],
                topk_by_grouping_rows=[],
                validation_only_rows=[],
                topk_by_budget_rows=[],
                topk_by_validation_budget_rows=[],
                topk_improvement_rows=[],
                summary_source=base / "summary.tsv",
                protocol_source=base / "protocol.tsv",
                report_plan="phase3",
                paper_plan="phase3",
                paper_budget="all",
                paper_status="ok",
                paper_yield_metric="HWAM",
                paper_require_validation=True,
                paper_require_better_than="b0",
                paper_protocol_status="auto",
                paper_max_rows=10,
                top_n=5,
                top_k_per_panel=3,
            )

        self.assertIn("- crop_family: wheat", report_text)
        self.assertIn("- crop_display_name: Wheat", report_text)
        self.assertIn("- registry_plan_sequences: s2_sequential_phase", report_text)
        self.assertIn("- registry_default_groupings: s2_sequential_phase:g3_dssat_extended", report_text)
        self.assertIn("## Protocol Risk Hotspots", report_text)
        self.assertIn(
            "weight\\|engine\\|sequence\\|grouping=W1\\|o2\\|s2_sequential_phase\\|g3_dssat_extended",
            report_text,
        )
        self.assertIn("## Protocol Detail Reason Breakdown", report_text)
        self.assertIn("protocol_detail_reasons", report_text)
        self.assertIn("no_train_observations", report_text)

    def test_build_protocol_hotspot_preview_rows_prioritizes_high_risk_slices(self) -> None:
        rows = auto_evolve.build_protocol_hotspot_preview_rows(
            protocol_dimension_rows=[
                {
                    "selection_scope": "leaderboard_all",
                    "dimension": "weight",
                    "value": "W1",
                    "total_runs": "3",
                    "missing_contract_runs": "0",
                    "degraded_contract_runs": "1",
                    "total_dropped_group_count": "2",
                    "total_weight_fallback_count": "1",
                    "total_zero_weight_observation_count": "3",
                },
                {
                    "selection_scope": "leaderboard_all",
                    "dimension": "engine",
                    "value": "o2",
                    "total_runs": "2",
                    "missing_contract_runs": "0",
                    "degraded_contract_runs": "0",
                    "total_dropped_group_count": "0",
                    "total_weight_fallback_count": "0",
                    "total_zero_weight_observation_count": "0",
                },
            ],
            protocol_nested_dimension_rows=[
                {
                    "selection_scope": "leaderboard_all",
                    "dimension_depth": "4",
                    "dimensions": "weight|engine|sequence|grouping",
                    "values": "W2|o1|s2|g3",
                    "total_runs": "1",
                    "missing_contract_runs": "1",
                    "degraded_contract_runs": "0",
                    "total_dropped_group_count": "1",
                    "total_weight_fallback_count": "0",
                    "total_zero_weight_observation_count": "4",
                },
                {
                    "selection_scope": "paper_selected",
                    "dimension_depth": "2",
                    "dimensions": "weight|sequence",
                    "values": "W1|s2",
                    "total_runs": "1",
                    "missing_contract_runs": "0",
                    "degraded_contract_runs": "1",
                    "total_dropped_group_count": "1",
                    "total_weight_fallback_count": "2",
                    "total_zero_weight_observation_count": "1",
                },
            ],
            top_n=3,
        )

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["source"], "nested_d4")
        self.assertEqual(rows[0]["slice_label"], "weight|engine|sequence|grouping=W2|o1|s2|g3")
        self.assertEqual(rows[1]["source"], "dimension")
        self.assertEqual(rows[1]["slice_label"], "weight=W1")
        self.assertEqual(rows[2]["source"], "nested_d2")
        self.assertEqual(rows[2]["slice_label"], "weight|sequence=W1|s2")

    def test_contract_detail_records_capture_drop_fallback_and_zero_weight_reasons(self) -> None:
        group_defs = {
            "obs_yield": {"patterns": ["hwam_"], "weight": 1.0, "sigma": 2.0},
            "obs_canopy": {"patterns": ["laix_"], "weight": 1.0, "sigma": 0.0},
            "obs_biomass": {"patterns": ["cwam_"], "weight": 1.0, "sigma": 1.0},
        }
        dropped_groups = build_pest_setup._build_dropped_group_records(
            group_defs,
            {"obs_yield": 0.5, "obs_canopy": 1.0},
        )
        weight_fallbacks = build_pest_setup._build_weight_fallback_records(
            group_defs,
            {"obs_yield": float("nan"), "obs_canopy": float("nan")},
            {},
            {"obs_yield": 0.5, "obs_canopy": 1.0},
            "w1_inverse_variance",
        )
        zero_weight_observations = build_pest_setup._build_zero_weight_observation_records(
            {
                "hwam_t01": 100.0,
                "hwam_t02": 95.0,
                "laix_t01": 3.0,
            },
            group_defs,
            {"obs_yield": 0.5, "obs_canopy": 1.0},
            {"hwam_t01": 0.0},
            {1: "train", 2: "valid"},
            {"hwam"},
            "hwam",
            "laix",
        )

        self.assertEqual(
            dropped_groups,
            [{"group": "obs_biomass", "reason": "no_train_observations"}],
        )
        self.assertEqual(
            weight_fallbacks,
            [
                {
                    "group": "obs_canopy",
                    "reason": "variance_and_sigma_unavailable_used_configured_weight",
                    "configured_weight": 1.0,
                    "applied_weight": 1.0,
                },
                {
                    "group": "obs_yield",
                    "reason": "variance_unavailable_used_sigma",
                    "sigma": 2.0,
                    "applied_weight": 0.5,
                },
            ],
        )
        self.assertEqual(
            zero_weight_observations,
            [
                {
                    "obs_name": "hwam_t01",
                    "group": "obs_yield",
                    "metric": "hwam",
                    "reason": "explicit_weight_override",
                    "trt": 1,
                },
                {
                    "obs_name": "hwam_t02",
                    "group": "obs_yield",
                    "metric": "hwam",
                    "reason": "validation_split",
                    "trt": 2,
                },
                {
                    "obs_name": "laix_t01",
                    "group": "obs_canopy",
                    "metric": "laix",
                    "reason": "inactive_metric",
                    "trt": 1,
                },
            ],
        )

    def test_w8_group_maxima_uses_train_only_and_absolute_values(self) -> None:
        meas = {
            "hwam_t01": 100.0,
            "hwam_t02": -250.0,
            "laix_t01": 3.0,
            "laix_t02": 4.0,
            "hwum_t03": -7.0,
        }
        split_by_trt = {1: "train", 2: "valid", 3: "train"}

        maxima = build_pest_setup._calc_group_maxima(
            meas,
            split_by_trt,
            dict(build_pest_setup.DEFAULT_OBSERVATION_GROUPS),
            "hwam",
            "laix",
        )

        self.assertEqual(maxima["obs_yield"], 100.0)
        self.assertEqual(maxima["obs_canopy"], 3.0)
        self.assertEqual(maxima["obs_yield_unit_weight"], 7.0)
        self.assertNotIn("obs", maxima)

    def test_phase0_and_phase2_matrix_cells_follow_contract(self) -> None:
        self.assertTrue(
            auto_evolve.plan_allows_cell(
                "phase0",
                "w8_dssat_group_max",
                "s1_naive_joint",
                "g1_flat_all_in_one",
            )
        )
        self.assertTrue(
            auto_evolve.plan_allows_cell(
                "phase0",
                "w8_dssat_group_max",
                "s2_sequential_phase",
                "g3_dssat_extended",
            )
        )
        self.assertFalse(
            auto_evolve.plan_allows_cell(
                "phase0",
                "w8_dssat_group_max",
                "s1_naive_joint",
                "g3_dssat_extended",
            )
        )

        self.assertTrue(
            auto_evolve.plan_allows_cell(
                "phase2",
                "w8_dssat_group_max",
                "s2_sequential_phase",
                "g3_dssat_extended",
            )
        )
        self.assertFalse(
            auto_evolve.plan_allows_cell(
                "phase2",
                "w8_dssat_group_max",
                "s3_wls_joint",
                "g3_dssat_extended",
            )
        )
        self.assertTrue(
            auto_evolve.plan_allows_cell(
                "phase2",
                "w7_equal_contribution",
                "s3_wls_joint",
                "g3_dssat_extended",
            )
        )
        self.assertFalse(
            auto_evolve.plan_allows_cell(
                "phase2",
                "w7_equal_contribution",
                "s3_wls_joint",
                "g1_flat_all_in_one",
            )
        )
        self.assertTrue(
            auto_evolve.plan_allows_cell(
                "phase2",
                "w1_inverse_variance",
                "s3_wls_joint",
                "g3_dssat_extended",
            )
        )
        self.assertFalse(
            auto_evolve.plan_allows_cell(
                "phase2",
                "w1_inverse_variance",
                "s2_sequential_phase",
                "g3_dssat_extended",
            )
        )

    def test_g1_g3_and_s3_inference_remain_stable(self) -> None:
        self.assertEqual(auto_evolve.normalize_sequence_name("agmip_two_step"), "s3_wls_joint")
        self.assertEqual(auto_evolve.infer_grouping("s1_naive_joint", "w0_raw_identity"), "g1_flat_all_in_one")
        self.assertEqual(auto_evolve.infer_grouping("s3_wls_joint", "w1_inverse_variance"), "g3_dssat_extended")
        self.assertEqual(auto_evolve.infer_grouping("s1_naive_joint", "w8_dssat_group_max"), "g3_dssat_extended")

    def test_build_sandbox_paths_routes_runs_and_artifacts_to_dedicated_directories(self) -> None:
        sandbox_dir = Path(r"d:\tmp\autoresearch_sandbox")
        mvp_root = Path(r"d:\tmp\mvp_pest_mgda")

        paths = auto_evolve.build_sandbox_paths(sandbox_dir=sandbox_dir, mvp_root=mvp_root)

        self.assertEqual(paths.runs_dir, sandbox_dir / "runs")
        self.assertEqual(paths.artifacts_dir, sandbox_dir / "artifacts")
        self.assertEqual(paths.parallel_workers_dir, sandbox_dir / "runs" / "parallel_workers")
        self.assertEqual(paths.log_path, sandbox_dir / "artifacts" / "evolution_log.md")
        self.assertEqual(paths.matrix_tsv_path, sandbox_dir / "artifacts" / "matrix_results.tsv")
        self.assertEqual(paths.case_template_dir, mvp_root / "scripts" / "dssat_case")

    def test_prepare_matrix_workspace_uses_runs_parallel_workers_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sandbox_dir = Path(tmp_dir) / "autoresearch_sandbox"
            sandbox_dir.mkdir(parents=True, exist_ok=True)
            (sandbox_dir / "eval.py").write_text("print('ok')\n", encoding="utf-8")
            (sandbox_dir / "project.json").write_text("{}", encoding="utf-8")
            (sandbox_dir / "dssat_trts.txt").write_text("1\n", encoding="utf-8")

            sandbox_case = sandbox_dir / "dssat_case"
            (sandbox_case / "GENOTYPE").mkdir(parents=True, exist_ok=True)
            (sandbox_case / "DSSAT48.INP").write_text("inp\n", encoding="utf-8")
            (sandbox_case / "DSSAT48.INH").write_text("inh\n", encoding="utf-8")
            (sandbox_case / "GENOTYPE" / "WHCER048.CUL").write_text("cul\n", encoding="utf-8")

            with mock.patch.object(auto_evolve, "SANDBOX_DIR", sandbox_dir), mock.patch.object(
                auto_evolve, "EVAL_PATH", sandbox_dir / "eval.py"
            ), mock.patch.object(
                auto_evolve, "PROJECT_CONFIG_PATH", sandbox_dir / "project.json"
            ), mock.patch.object(
                auto_evolve, "DSSAT_TRTS_PATH", sandbox_dir / "dssat_trts.txt"
            ), mock.patch.object(
                auto_evolve, "PARALLEL_WORKERS_DIR", sandbox_dir / "runs" / "parallel_workers"
            ):
                workspace = auto_evolve.prepare_matrix_workspace(0, "def calculate_loss(*args):\n    return 0.0\n")

            self.assertEqual(workspace, sandbox_dir / "runs" / "parallel_workers" / "job_000")
            self.assertTrue((workspace / "eval.py").exists())
            self.assertTrue((workspace / "project.json").exists())
            self.assertTrue((workspace / "dssat_trts.txt").exists())
            self.assertTrue((workspace / "strategy.py").exists())
            self.assertTrue((workspace / "dssat_case" / "DSSAT48.INP").exists())
            self.assertTrue((workspace / "dssat_case" / "DSSAT48.INH").exists())
            self.assertTrue((workspace / "dssat_case" / "GENOTYPE" / "WHCER048.CUL").exists())

    def test_sandbox_config_resolver_prefers_generic_project_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sandbox_dir = Path(tmp_dir) / "autoresearch_sandbox"
            sandbox_dir.mkdir(parents=True, exist_ok=True)
            generic_cfg = sandbox_dir / "project.json"
            legacy_cfg = sandbox_dir / "project_wheat.json"
            generic_cfg.write_text("{}", encoding="utf-8")
            legacy_cfg.write_text("{}", encoding="utf-8")

            self.assertEqual(auto_evolve.resolve_sandbox_project_config_path(sandbox_dir), generic_cfg.resolve())
            self.assertEqual(sandbox_eval.resolve_sandbox_project_config_path(sandbox_dir), generic_cfg.resolve())

    def test_build_eval_paths_falls_back_to_generic_project_json_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sandbox_dir = Path(tmp_dir) / "autoresearch_sandbox"
            sandbox_dir.mkdir(parents=True, exist_ok=True)
            mvp_root = sandbox_dir.parent / "mvp_pest_mgda"
            paths = sandbox_eval.build_eval_paths(sandbox_dir=sandbox_dir, mvp_root=mvp_root)

            self.assertEqual(paths.project_config_path, (sandbox_dir / "project.json").resolve())

    def test_eval_module_resolves_repo_relative_paths_without_hardcoded_install_root(self) -> None:
        module_name = "sandbox_eval_repo_probe"
        spec = importlib.util.spec_from_file_location(module_name, SANDBOX / "eval.py")

        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)

        module = importlib.util.module_from_spec(spec)
        sys.modules.pop(module_name, None)
        spec.loader.exec_module(module)

        self.assertEqual(module.SANDBOX_DIR, SANDBOX)
        self.assertEqual(module.PESTPP_ROOT, ROOT)
        self.assertEqual(module.SRC_DIR, SRC)
        self.assertEqual(module.PROJECT_CONFIG_PATH, ROOT / "config" / "multi" / "project_wheat.json")
        self.assertEqual(module.CASE_TEMPLATE_DIR, ROOT / "scripts" / "dssat_case")
        self.assertEqual(module.RUN_MODEL_PATH.name, "run_model.py")
        self.assertIs(module.run_build_pest_setup, pest_builder.run_build_pest_setup)


if __name__ == "__main__":
    unittest.main()
