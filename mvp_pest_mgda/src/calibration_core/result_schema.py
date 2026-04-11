from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
import re


MetricValue = float
TreatmentMetrics = dict[str, MetricValue]
MetricsByTreatment = dict[int, TreatmentMetrics]


@dataclass(frozen=True)
class PestOutputContext:
    trts: list[int]
    trts_env: str
    var_codes: list[str]
    wht_dates_by_trt: dict[int, list[int]]


@dataclass(frozen=True)
class PestOutputRecord:
    name: str
    value: float


@dataclass(frozen=True)
class AggregateMetricRecord:
    split: str
    metric: str
    count: int
    rmse: float
    mae: float
    nrmse: float
    bias: float
    pearson_r: float
    nse: float
    d1: float
    wcs: float


@dataclass(frozen=True)
class AggregateView:
    split: str
    mean_nrmse: float
    wcs: float


@dataclass(frozen=True)
class EvaluationResult:
    metrics_by_trt: MetricsByTreatment
    aggregate_views: dict[str, AggregateView]
    aggregate_metrics: list[AggregateMetricRecord]
    comparable_metrics: list[str]


@dataclass(frozen=True)
class MatrixSummaryView:
    primary_metric: str
    train_mean_nrmse: float
    valid_mean_nrmse: float
    all_mean_nrmse: float
    train_wcs: float
    valid_wcs: float
    all_wcs: float
    train_primary_nrmse: float
    train_primary_bias: float
    valid_primary_nrmse: float
    valid_primary_bias: float


@dataclass(frozen=True)
class TreatmentComparisonRecord:
    trt: int
    split: str
    metric: str
    observed: float
    simulated: float
    error: float
    abs_error: float
    relative_error: float


@dataclass(frozen=True)
class ExperimentExportContext:
    run_id: str
    plan: str
    weight_name: str
    engine: str
    budget: str
    sequence: str
    grouping: str
    status: str


@dataclass(frozen=True)
class TreatmentMetricExportRow:
    run_id: str
    plan: str
    weight_name: str
    engine: str
    budget: str
    sequence: str
    grouping: str
    status: str
    trt: int
    split: str
    metric: str
    observed: float
    simulated: float
    error: float
    abs_error: float
    relative_error: float


@dataclass(frozen=True)
class AggregateMetricExportRow:
    run_id: str
    plan: str
    weight_name: str
    engine: str
    budget: str
    sequence: str
    grouping: str
    status: str
    split: str
    metric: str
    count: int
    rmse: float
    mae: float
    nrmse: float
    bias: float
    pearson_r: float
    nse: float
    d1: float
    wcs: float


TREATMENT_METRIC_EXPORT_FIELDNAMES = [
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
]


AGGREGATE_METRIC_EXPORT_FIELDNAMES = [
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
    "rmse",
    "mae",
    "nrmse",
    "bias",
    "pearson_r",
    "nse",
    "d1",
    "wcs",
]


SUMMARY_EXPORT_FIELDNAMES = [
    "combo_key",
    "run_id",
    "score_rank",
    "executed_at",
    "plan",
    "weight",
    "engine",
    "budget",
    "sequence",
    "grouping",
    "weight_mode",
    "status",
    "score",
    "delta_vs_b0",
    "delta_vs_b1",
    "delta_vs_negative_ref",
    "better_than_b0",
    "better_than_b1",
    "better_than_negative_ref",
    "yield_metric",
    "train_mean_nrmse",
    "valid_mean_nrmse",
    "all_mean_nrmse",
    "train_yield_nrmse",
    "train_yield_bias",
    "valid_yield_nrmse",
    "valid_yield_bias",
    "duration_sec",
    "max_workers",
    "validation_enabled",
    "train_trts",
    "valid_trts",
    "workspace_dir",
]


SCATTER_EXPORT_FIELDNAMES = [
    "combo_key",
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
    "trt",
    "observed",
    "simulated",
    "error",
    "abs_error",
    "relative_error",
    "count",
    "nrmse",
    "bias",
]


RESIDUAL_EXPORT_BASE_FIELDNAMES = [
    "run_id",
    "score_rank",
    "combo_key",
    "weight",
    "engine",
    "budget",
    "sequence",
    "grouping",
    "status",
    "score",
    "metric",
    "split",
    "count",
    "nrmse",
    "bias",
]


FIGURE_READY_EXPORT_FIELDNAMES = [
    "run_id",
    "score_rank",
    "combo_key",
    "plan",
    "weight",
    "engine",
    "budget",
    "sequence",
    "grouping",
    "status",
    "score",
    "metric",
    "split",
    "trt",
    "panel_key",
    "series_key",
    "point_key",
    "x_observed",
    "y_simulated",
    "residual",
    "abs_residual",
    "relative_error",
    "panel_count",
    "panel_nrmse",
    "panel_bias",
]


COMPARE_SUMMARY_FIELDNAMES = [
    "scenario",
    "n_trt",
    "rmse_yield",
    "mae_yield",
    "bias_yield",
    "re_yield",
    "rmse_laix",
    "mae_laix",
    "bias_laix",
    "re_laix",
    "phi",
    "phi_w",
    "n_wht",
]


def metric_key(code: str) -> str:
    return str(code).strip().lower()


def is_single_treatment_layout(context: PestOutputContext) -> bool:
    return len(context.trts) == 1 and not str(context.trts_env).strip()


def build_summary_metric_name(code: str, trt: int, single_treatment: bool) -> str:
    key = metric_key(code)
    if single_treatment:
        return key
    return f"{key}_t{int(trt):02d}"


def build_timeseries_metric_name(code: str, trt: int, date: int) -> str:
    return f"{metric_key(code)}_t{int(trt):02d}_d{int(date)}"


def build_split_mean_name(split: str) -> str:
    return f"{str(split).strip().upper()}_MEAN_NRMSE"


def build_split_score_name(split: str, stat: str) -> str:
    return f"{str(split).strip().upper()}_{str(stat).strip().upper()}"


def build_split_metric_name(split: str, metric: str, stat: str) -> str:
    return f"{str(split).strip().upper()}_{metric_key(metric).upper()}_{str(stat).strip().upper()}"


def build_combo_key(weight_name: str, engine: str, budget: str, sequence: str, grouping: str) -> str:
    return "|".join(
        [
            str(weight_name).strip(),
            str(engine).strip(),
            str(budget).strip(),
            str(sequence).strip(),
            str(grouping).strip(),
        ]
    )


def build_experiment_export_context(
    run_id: str,
    plan: str,
    weight_name: str,
    engine: str,
    budget: str,
    sequence: str,
    grouping: str,
    status: str,
) -> ExperimentExportContext:
    return ExperimentExportContext(
        run_id=str(run_id).strip(),
        plan=str(plan).strip(),
        weight_name=str(weight_name).strip(),
        engine=str(engine).strip(),
        budget=str(budget).strip(),
        sequence=str(sequence).strip(),
        grouping=str(grouping).strip(),
        status=str(status).strip(),
    )


def resolve_output_context(
    trts: list[int],
    trts_env: str,
    var_codes: list[str],
    wht_dates_by_trt: dict[int, list[int]],
) -> PestOutputContext:
    return PestOutputContext(
        trts=[int(trt) for trt in trts],
        trts_env=str(trts_env),
        var_codes=[str(code).strip().upper() for code in var_codes if str(code).strip()],
        wht_dates_by_trt={int(trt): [int(date) for date in dates] for trt, dates in wht_dates_by_trt.items()},
    )


def iter_pest_output_records(metrics_by_trt: MetricsByTreatment, context: PestOutputContext) -> list[PestOutputRecord]:
    records: list[PestOutputRecord] = []
    single_treatment = is_single_treatment_layout(context)
    for trt_value in context.trts:
        trt = int(trt_value)
        metrics = metrics_by_trt[trt]
        for code in context.var_codes:
            key = metric_key(code)
            if key in metrics:
                records.append(
                    PestOutputRecord(
                        name=build_summary_metric_name(code, trt, single_treatment),
                        value=float(metrics[key]),
                    )
                )
        if single_treatment:
            continue
        for date in context.wht_dates_by_trt.get(trt, []):
            for code in ("laid", "lwad", "swad"):
                key = f"{metric_key(code)}_d{int(date)}"
                if key in metrics:
                    records.append(
                        PestOutputRecord(
                            name=build_timeseries_metric_name(code, trt, date),
                            value=float(metrics[key]),
                        )
                    )
    return records


def build_pest_output_text_from_context(metrics_by_trt: MetricsByTreatment, context: PestOutputContext) -> str:
    return "\n".join(f"{record.name} {record.value:.6f} " for record in iter_pest_output_records(metrics_by_trt, context)) + "\n"


def _safe_mean(values: list[float]) -> float:
    if not values:
        return float("nan")
    return float(sum(values) / len(values))


def _clip01(value: float) -> float:
    v = float(value)
    if not math.isfinite(v):
        return float("nan")
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _single_metric_rmse(obs_values: list[float], sim_values: list[float]) -> float:
    if not obs_values:
        return float("nan")
    mse = sum((obs - sim) ** 2 for obs, sim in zip(obs_values, sim_values)) / len(obs_values)
    return float(math.sqrt(mse))


def _single_metric_mae(obs_values: list[float], sim_values: list[float]) -> float:
    if not obs_values:
        return float("nan")
    return float(sum(abs(obs - sim) for obs, sim in zip(obs_values, sim_values)) / len(obs_values))


def _single_metric_pearson_r(obs_values: list[float], sim_values: list[float]) -> float:
    if len(obs_values) < 2:
        return float("nan")
    mean_obs = _safe_mean(obs_values)
    mean_sim = _safe_mean(sim_values)
    x = [obs - mean_obs for obs in obs_values]
    y = [sim - mean_sim for sim in sim_values]
    var_x = sum(v * v for v in x)
    var_y = sum(v * v for v in y)
    if var_x <= 0.0 or var_y <= 0.0:
        return float("nan")
    cov = sum(a * b for a, b in zip(x, y))
    return float(cov / math.sqrt(var_x * var_y))


def _single_metric_nse(obs_values: list[float], sim_values: list[float]) -> float:
    if len(obs_values) < 2:
        return float("nan")
    mean_obs = _safe_mean(obs_values)
    sse = sum((sim - obs) ** 2 for obs, sim in zip(obs_values, sim_values))
    sst = sum((obs - mean_obs) ** 2 for obs in obs_values)
    if sst <= 0.0:
        return float("nan")
    return float(1.0 - (sse / sst))


def _single_metric_d1(obs_values: list[float], sim_values: list[float]) -> float:
    if not obs_values:
        return float("nan")
    mean_obs = _safe_mean(obs_values)
    num = sum(abs(sim - obs) for obs, sim in zip(obs_values, sim_values))
    denom = sum(abs(sim - mean_obs) + abs(obs - mean_obs) for obs, sim in zip(obs_values, sim_values))
    if denom <= 1e-12:
        return 1.0 if num <= 1e-12 else float("nan")
    return float(1.0 - (num / denom))


def _metric_wcs_score(pearson_r: float, nse: float, d1: float) -> float:
    parts: list[float] = []
    r_norm = _clip01(max(0.0, float(pearson_r))) if math.isfinite(float(pearson_r)) else float("nan")
    nse_norm = _clip01(max(0.0, float(nse))) if math.isfinite(float(nse)) else float("nan")
    d1_norm = _clip01(float(d1)) if math.isfinite(float(d1)) else float("nan")
    for v in (r_norm, nse_norm, d1_norm):
        if math.isfinite(float(v)):
            parts.append(float(v))
    if not parts:
        return float("nan")
    return float(sum(parts) / len(parts))


def _single_metric_nrmse(obs_values: list[float], sim_values: list[float]) -> float:
    if not obs_values:
        return float("nan")
    mse = sum((obs - sim) ** 2 for obs, sim in zip(obs_values, sim_values)) / len(obs_values)
    denom = abs(_safe_mean(obs_values)) + 1e-8
    return float(math.sqrt(mse) / denom)


def _single_metric_bias(obs_values: list[float], sim_values: list[float]) -> float:
    if not obs_values:
        return float("nan")
    denom = _safe_mean([abs(value) for value in obs_values]) + 1e-8
    return float(_safe_mean([sim - obs for obs, sim in zip(obs_values, sim_values)]) / denom)


def _split_trts(metrics_by_trt: MetricsByTreatment, split_by_trt: dict[int, str], split: str) -> list[int]:
    if str(split).strip().lower() == "all":
        return sorted(int(trt) for trt in metrics_by_trt.keys())
    wanted = str(split).strip().lower()
    return sorted(int(trt) for trt in metrics_by_trt.keys() if str(split_by_trt.get(int(trt), "train")).strip().lower() == wanted)


def build_evaluation_result(
    metrics_by_trt: MetricsByTreatment,
    observations_by_trt: MetricsByTreatment,
    split_by_trt: dict[int, str],
    comparable_metrics: list[str],
) -> EvaluationResult:
    normalized_metrics: MetricsByTreatment = {
        int(trt): {metric_key(name): float(value) for name, value in metrics.items()}
        for trt, metrics in metrics_by_trt.items()
    }
    normalized_observations: MetricsByTreatment = {
        int(trt): {metric_key(name): float(value) for name, value in metrics.items()}
        for trt, metrics in observations_by_trt.items()
    }
    comparable = [metric_key(name) for name in comparable_metrics if metric_key(name)]
    aggregate_metrics: list[AggregateMetricRecord] = []
    aggregate_views: dict[str, AggregateView] = {}
    weight_bucket_phenology = {"adap", "mdap"}
    weight_bucket_yield = {"hwam", "hwum"}
    weight_bucket_biomass = {"laix", "cwam"}
    comparable_set = set(comparable)
    weights_by_metric: dict[str, float] = {}
    phenology_present = sorted(comparable_set.intersection(weight_bucket_phenology))
    yield_present = sorted(comparable_set.intersection(weight_bucket_yield))
    biomass_present = sorted(comparable_set.intersection(weight_bucket_biomass))
    if phenology_present:
        for m in phenology_present:
            weights_by_metric[m] = 0.40 / len(phenology_present)
    if yield_present:
        for m in yield_present:
            weights_by_metric[m] = 0.35 / len(yield_present)
    if biomass_present:
        for m in biomass_present:
            weights_by_metric[m] = 0.25 / len(biomass_present)
    for split in ("train", "valid", "all"):
        metric_scores: list[float] = []
        wcs_num = 0.0
        wcs_den = 0.0
        split_trts = _split_trts(normalized_metrics, split_by_trt, split)
        for metric in comparable:
            obs_values: list[float] = []
            sim_values: list[float] = []
            for trt in split_trts:
                obs_value = normalized_observations.get(int(trt), {}).get(metric)
                sim_value = normalized_metrics.get(int(trt), {}).get(metric)
                if obs_value is None or sim_value is None:
                    continue
                if not math.isfinite(float(obs_value)) or not math.isfinite(float(sim_value)):
                    continue
                obs_values.append(float(obs_value))
                sim_values.append(float(sim_value))
            rmse = _single_metric_rmse(obs_values, sim_values)
            mae = _single_metric_mae(obs_values, sim_values)
            nrmse = _single_metric_nrmse(obs_values, sim_values)
            bias = _single_metric_bias(obs_values, sim_values)
            pearson_r = _single_metric_pearson_r(obs_values, sim_values)
            nse = _single_metric_nse(obs_values, sim_values)
            d1 = _clip01(_single_metric_d1(obs_values, sim_values))
            wcs = _metric_wcs_score(pearson_r, nse, d1)
            if math.isfinite(nrmse):
                metric_scores.append(float(nrmse))
            w = float(weights_by_metric.get(metric, 0.0))
            if w > 0.0 and math.isfinite(float(wcs)):
                wcs_num += w * float(wcs)
                wcs_den += w
            aggregate_metrics.append(
                AggregateMetricRecord(
                    split=split,
                    metric=metric,
                    count=len(obs_values),
                    rmse=rmse,
                    mae=mae,
                    nrmse=nrmse,
                    bias=bias,
                    pearson_r=pearson_r,
                    nse=nse,
                    d1=d1,
                    wcs=wcs,
                )
            )
        mean_nrmse = float(_safe_mean(metric_scores)) if metric_scores else 999.0
        split_wcs = float(wcs_num / wcs_den) if wcs_den > 0.0 else float("nan")
        aggregate_views[split] = AggregateView(split=split, mean_nrmse=mean_nrmse, wcs=split_wcs)
    return EvaluationResult(
        metrics_by_trt=normalized_metrics,
        aggregate_views=aggregate_views,
        aggregate_metrics=aggregate_metrics,
        comparable_metrics=comparable,
    )


def build_treatment_comparison_records(
    result: EvaluationResult,
    observations_by_trt: MetricsByTreatment,
    split_by_trt: dict[int, str],
    comparable_metrics: list[str] | None = None,
) -> list[TreatmentComparisonRecord]:
    normalized_observations: MetricsByTreatment = {
        int(trt): {metric_key(name): float(value) for name, value in metrics.items()}
        for trt, metrics in observations_by_trt.items()
    }
    metric_names = [
        metric_key(name)
        for name in (
            comparable_metrics
            if comparable_metrics is not None
            else result.comparable_metrics
        )
        if metric_key(name)
    ]
    records: list[TreatmentComparisonRecord] = []
    for metric in metric_names:
        for trt in sorted(int(value) for value in result.metrics_by_trt.keys()):
            observed = normalized_observations.get(int(trt), {}).get(metric)
            simulated = result.metrics_by_trt.get(int(trt), {}).get(metric)
            if observed is None or simulated is None:
                continue
            if not math.isfinite(float(observed)) or not math.isfinite(float(simulated)):
                continue
            error = float(simulated) - float(observed)
            abs_error = abs(error)
            records.append(
                TreatmentComparisonRecord(
                    trt=int(trt),
                    split=str(split_by_trt.get(int(trt), "train")).strip().lower(),
                    metric=metric,
                    observed=float(observed),
                    simulated=float(simulated),
                    error=float(error),
                    abs_error=float(abs_error),
                    relative_error=float(abs_error / (abs(float(observed)) + 1e-8)),
                )
            )
    return records


def build_treatment_metric_export_rows(
    context: ExperimentExportContext,
    records: list[TreatmentComparisonRecord],
) -> list[TreatmentMetricExportRow]:
    return [
        TreatmentMetricExportRow(
            run_id=context.run_id,
            plan=context.plan,
            weight_name=context.weight_name,
            engine=context.engine,
            budget=context.budget,
            sequence=context.sequence,
            grouping=context.grouping,
            status=context.status,
            trt=int(record.trt),
            split=str(record.split).strip().lower(),
            metric=metric_key(record.metric),
            observed=float(record.observed),
            simulated=float(record.simulated),
            error=float(record.error),
            abs_error=float(record.abs_error),
            relative_error=float(record.relative_error),
        )
        for record in records
    ]


def build_aggregate_metric_export_rows(
    context: ExperimentExportContext,
    records: list[AggregateMetricRecord],
) -> list[AggregateMetricExportRow]:
    return [
        AggregateMetricExportRow(
            run_id=context.run_id,
            plan=context.plan,
            weight_name=context.weight_name,
            engine=context.engine,
            budget=context.budget,
            sequence=context.sequence,
            grouping=context.grouping,
            status=context.status,
            split=str(record.split).strip().lower(),
            metric=metric_key(record.metric),
            count=int(record.count),
            rmse=float(record.rmse),
            mae=float(record.mae),
            nrmse=float(record.nrmse),
            bias=float(record.bias),
            pearson_r=float(record.pearson_r),
            nse=float(record.nse),
            d1=float(record.d1),
            wcs=float(record.wcs),
        )
        for record in records
    ]


def build_treatment_metric_export_value_map(row: TreatmentMetricExportRow) -> dict[str, str | int | float]:
    return {
        "run_id": row.run_id,
        "plan": row.plan,
        "weight": row.weight_name,
        "engine": row.engine,
        "budget": row.budget,
        "sequence": row.sequence,
        "grouping": row.grouping,
        "status": row.status,
        "trt": int(row.trt),
        "split": row.split,
        "metric": row.metric,
        "observed": float(row.observed),
        "simulated": float(row.simulated),
        "error": float(row.error),
        "abs_error": float(row.abs_error),
        "relative_error": float(row.relative_error),
    }


def build_aggregate_metric_export_value_map(row: AggregateMetricExportRow) -> dict[str, str | int | float]:
    return {
        "run_id": row.run_id,
        "plan": row.plan,
        "weight": row.weight_name,
        "engine": row.engine,
        "budget": row.budget,
        "sequence": row.sequence,
        "grouping": row.grouping,
        "status": row.status,
        "split": row.split,
        "metric": row.metric,
        "count": int(row.count),
        "rmse": float(row.rmse),
        "mae": float(row.mae),
        "nrmse": float(row.nrmse),
        "bias": float(row.bias),
        "pearson_r": float(row.pearson_r),
        "nse": float(row.nse),
        "d1": float(row.d1),
        "wcs": float(row.wcs),
    }


def format_export_float(value: float) -> str:
    return f"{float(value):.6f}" if math.isfinite(float(value)) else ""


def format_summary_schema_value(fallback: str, value: float) -> str:
    return format_export_float(value) if math.isfinite(value) else str(fallback).strip()


def build_summary_export_row(
    row: Mapping[str, str],
    combo_key: str,
    score: float,
    baseline_b0_score: float,
    baseline_b1_score: float,
    negative_ref_score: float,
    schema_metrics: Mapping[str, float],
) -> dict[str, str]:
    return {
        "combo_key": str(combo_key).strip(),
        "run_id": str(row.get("run_id", "")).strip(),
        "executed_at": str(row.get("executed_at", "")).strip(),
        "plan": str(row.get("plan", "")).strip(),
        "weight": str(row.get("weight", "")).strip(),
        "engine": str(row.get("engine", "")).strip(),
        "budget": str(row.get("budget", "")).strip(),
        "sequence": str(row.get("sequence", "")).strip(),
        "grouping": str(row.get("grouping", "")).strip(),
        "weight_mode": str(row.get("weight_mode", "")).strip(),
        "status": str(row.get("status", "")).strip(),
        "score": format_export_float(score),
        "delta_vs_b0": format_export_float(score - baseline_b0_score),
        "delta_vs_b1": format_export_float(score - baseline_b1_score),
        "delta_vs_negative_ref": format_export_float(score - negative_ref_score),
        "better_than_b0": (
            "true"
            if math.isfinite(score) and math.isfinite(baseline_b0_score) and score <= baseline_b0_score
            else "false"
        ),
        "better_than_b1": (
            "true"
            if math.isfinite(score) and math.isfinite(baseline_b1_score) and score <= baseline_b1_score
            else "false"
        ),
        "better_than_negative_ref": (
            "true"
            if math.isfinite(score) and math.isfinite(negative_ref_score) and score <= negative_ref_score
            else "false"
        ),
        "yield_metric": str(row.get("yield_metric", "")).strip(),
        "train_mean_nrmse": format_summary_schema_value(
            str(row.get("train_mean_nrmse", "")).strip(),
            float(schema_metrics.get("train_mean_nrmse", float("nan"))),
        ),
        "valid_mean_nrmse": format_summary_schema_value(
            str(row.get("valid_mean_nrmse", "")).strip(),
            float(schema_metrics.get("valid_mean_nrmse", float("nan"))),
        ),
        "all_mean_nrmse": format_summary_schema_value(
            str(row.get("all_mean_nrmse", "")).strip(),
            float(schema_metrics.get("all_mean_nrmse", float("nan"))),
        ),
        "train_yield_nrmse": format_summary_schema_value(
            str(row.get("train_yield_nrmse", "")).strip(),
            float(schema_metrics.get("train_yield_nrmse", float("nan"))),
        ),
        "train_yield_bias": format_summary_schema_value(
            str(row.get("train_yield_bias", "")).strip(),
            float(schema_metrics.get("train_yield_bias", float("nan"))),
        ),
        "valid_yield_nrmse": format_summary_schema_value(
            str(row.get("valid_yield_nrmse", "")).strip(),
            float(schema_metrics.get("valid_yield_nrmse", float("nan"))),
        ),
        "valid_yield_bias": format_summary_schema_value(
            str(row.get("valid_yield_bias", "")).strip(),
            float(schema_metrics.get("valid_yield_bias", float("nan"))),
        ),
        "duration_sec": str(row.get("duration_sec", "")).strip(),
        "max_workers": str(row.get("max_workers", "")).strip(),
        "validation_enabled": str(row.get("validation_enabled", "")).strip(),
        "train_trts": str(row.get("train_trts", "")).strip(),
        "valid_trts": str(row.get("valid_trts", "")).strip(),
        "workspace_dir": str(row.get("workspace_dir", "")).strip(),
    }


def build_scatter_export_row(
    row: Mapping[str, str],
    aggregate_metric_row: Mapping[str, str],
    combo_key: str,
) -> dict[str, str]:
    return {
        "combo_key": str(combo_key).strip(),
        "run_id": str(row.get("run_id", "")).strip(),
        "plan": str(row.get("plan", "")).strip(),
        "weight": str(row.get("weight", "")).strip(),
        "engine": str(row.get("engine", "")).strip(),
        "budget": str(row.get("budget", "")).strip(),
        "sequence": str(row.get("sequence", "")).strip(),
        "grouping": str(row.get("grouping", "")).strip(),
        "status": str(row.get("status", "")).strip(),
        "split": str(row.get("split", "")).strip(),
        "metric": str(row.get("metric", "")).strip(),
        "trt": str(row.get("trt", "")).strip(),
        "observed": str(row.get("observed", "")).strip(),
        "simulated": str(row.get("simulated", "")).strip(),
        "error": str(row.get("error", "")).strip(),
        "abs_error": str(row.get("abs_error", "")).strip(),
        "relative_error": str(row.get("relative_error", "")).strip(),
        "count": str(aggregate_metric_row.get("count", "")).strip(),
        "nrmse": str(aggregate_metric_row.get("nrmse", "")).strip(),
        "bias": str(aggregate_metric_row.get("bias", "")).strip(),
    }


def build_residual_export_row(
    summary_row: Mapping[str, str],
    metric: str,
    split: str,
    aggregate_metric_row: Mapping[str, str],
) -> dict[str, str]:
    return {
        "run_id": str(summary_row.get("run_id", "")).strip(),
        "score_rank": str(summary_row.get("score_rank", "")).strip(),
        "combo_key": str(summary_row.get("combo_key", "")).strip(),
        "weight": str(summary_row.get("weight", "")).strip(),
        "engine": str(summary_row.get("engine", "")).strip(),
        "budget": str(summary_row.get("budget", "")).strip(),
        "sequence": str(summary_row.get("sequence", "")).strip(),
        "grouping": str(summary_row.get("grouping", "")).strip(),
        "status": str(summary_row.get("status", "")).strip(),
        "score": str(summary_row.get("score", "")).strip(),
        "metric": str(metric).strip(),
        "split": str(split).strip(),
        "count": str(aggregate_metric_row.get("count", "")).strip(),
        "nrmse": str(aggregate_metric_row.get("nrmse", "")).strip(),
        "bias": str(aggregate_metric_row.get("bias", "")).strip(),
    }


def build_residual_export_fieldnames(trts: list[int]) -> list[str]:
    return RESIDUAL_EXPORT_BASE_FIELDNAMES + [f"trt_{int(trt)}" for trt in trts]


def build_figure_ready_export_row(
    summary_row: Mapping[str, str],
    row: Mapping[str, str],
    aggregate_metric_row: Mapping[str, str],
) -> dict[str, str]:
    metric = str(row.get("metric", "")).strip()
    split = str(row.get("split", "")).strip()
    trt = str(row.get("trt", "")).strip()
    combo_key = str(row.get("combo_key", "")).strip()
    run_id = str(row.get("run_id", "")).strip()
    return {
        "run_id": run_id,
        "score_rank": str(summary_row.get("score_rank", "")).strip(),
        "combo_key": combo_key,
        "plan": str(row.get("plan", "")).strip(),
        "weight": str(row.get("weight", "")).strip(),
        "engine": str(row.get("engine", "")).strip(),
        "budget": str(row.get("budget", "")).strip(),
        "sequence": str(row.get("sequence", "")).strip(),
        "grouping": str(row.get("grouping", "")).strip(),
        "status": str(row.get("status", "")).strip(),
        "score": str(summary_row.get("score", "")).strip(),
        "metric": metric,
        "split": split,
        "trt": trt,
        "panel_key": f"{metric}|{split}",
        "series_key": combo_key,
        "point_key": f"{run_id}|{metric}|t{trt}",
        "x_observed": str(row.get("observed", "")).strip(),
        "y_simulated": str(row.get("simulated", "")).strip(),
        "residual": str(row.get("error", "")).strip(),
        "abs_residual": str(row.get("abs_error", "")).strip(),
        "relative_error": str(row.get("relative_error", "")).strip(),
        "panel_count": str(aggregate_metric_row.get("count", "")).strip(),
        "panel_nrmse": str(aggregate_metric_row.get("nrmse", "")).strip(),
        "panel_bias": str(aggregate_metric_row.get("bias", "")).strip(),
    }


def build_compare_summary_fieldnames(rows: Sequence[Mapping[str, object]]) -> list[str]:
    fieldnames = list(COMPARE_SUMMARY_FIELDNAMES)
    for row in rows:
        for key in row.keys():
            normalized = str(key).strip()
            if normalized and normalized not in fieldnames:
                fieldnames.append(normalized)
    return fieldnames


def iter_aggregate_value_records(result: EvaluationResult) -> list[PestOutputRecord]:
    records: list[PestOutputRecord] = []
    for split in ("train", "valid", "all"):
        view = result.aggregate_views.get(split)
        if view is not None:
            records.append(PestOutputRecord(name=build_split_mean_name(split), value=float(view.mean_nrmse)))
            records.append(PestOutputRecord(name=build_split_score_name(split, "WCS"), value=float(view.wcs)))
    for metric_record in result.aggregate_metrics:
        records.append(
            PestOutputRecord(
                name=build_split_metric_name(metric_record.split, metric_record.metric, "N"),
                value=float(metric_record.count),
            )
        )
        records.append(
            PestOutputRecord(
                name=build_split_metric_name(metric_record.split, metric_record.metric, "RMSE"),
                value=float(metric_record.rmse),
            )
        )
        records.append(
            PestOutputRecord(
                name=build_split_metric_name(metric_record.split, metric_record.metric, "MAE"),
                value=float(metric_record.mae),
            )
        )
        records.append(
            PestOutputRecord(
                name=build_split_metric_name(metric_record.split, metric_record.metric, "NRMSE"),
                value=float(metric_record.nrmse),
            )
        )
        records.append(
            PestOutputRecord(
                name=build_split_metric_name(metric_record.split, metric_record.metric, "BIAS"),
                value=float(metric_record.bias),
            )
        )
        records.append(
            PestOutputRecord(
                name=build_split_metric_name(metric_record.split, metric_record.metric, "R"),
                value=float(metric_record.pearson_r),
            )
        )
        records.append(
            PestOutputRecord(
                name=build_split_metric_name(metric_record.split, metric_record.metric, "NSE"),
                value=float(metric_record.nse),
            )
        )
        records.append(
            PestOutputRecord(
                name=build_split_metric_name(metric_record.split, metric_record.metric, "D1"),
                value=float(metric_record.d1),
            )
        )
        records.append(
            PestOutputRecord(
                name=build_split_metric_name(metric_record.split, metric_record.metric, "WCS"),
                value=float(metric_record.wcs),
            )
        )
    return records


def aggregate_value_map(result: EvaluationResult) -> dict[str, float]:
    return {record.name: float(record.value) for record in iter_aggregate_value_records(result)}


def resolve_aggregate_value(result: EvaluationResult, name: str, default: float = float("nan")) -> float:
    return float(aggregate_value_map(result).get(str(name), default))


def build_matrix_summary_view(result: EvaluationResult, primary_metric: str) -> MatrixSummaryView:
    metric = metric_key(primary_metric)
    return MatrixSummaryView(
        primary_metric=metric,
        train_mean_nrmse=resolve_aggregate_value(result, build_split_mean_name("train")),
        valid_mean_nrmse=resolve_aggregate_value(result, build_split_mean_name("valid")),
        all_mean_nrmse=resolve_aggregate_value(result, build_split_mean_name("all")),
        train_wcs=resolve_aggregate_value(result, build_split_score_name("train", "WCS")),
        valid_wcs=resolve_aggregate_value(result, build_split_score_name("valid", "WCS")),
        all_wcs=resolve_aggregate_value(result, build_split_score_name("all", "WCS")),
        train_primary_nrmse=resolve_aggregate_value(result, build_split_metric_name("train", metric, "NRMSE")),
        train_primary_bias=resolve_aggregate_value(result, build_split_metric_name("train", metric, "BIAS")),
        valid_primary_nrmse=resolve_aggregate_value(result, build_split_metric_name("valid", metric, "NRMSE")),
        valid_primary_bias=resolve_aggregate_value(result, build_split_metric_name("valid", metric, "BIAS")),
    )


def extract_matrix_summary_view(
    text: str,
    primary_metric: str,
    prefix: str = "RESULT_SCHEMA_JSON",
) -> MatrixSummaryView | None:
    result = extract_evaluation_result(text, prefix=prefix)
    if result is None:
        return None
    return build_matrix_summary_view(result, primary_metric)


def serialize_evaluation_result(result: EvaluationResult) -> dict:
    return {
        "metrics_by_trt": {
            str(int(trt)): {metric_key(name): float(value) for name, value in metrics.items()}
            for trt, metrics in result.metrics_by_trt.items()
        },
        "aggregate_views": {
            split: {"split": view.split, "mean_nrmse": float(view.mean_nrmse), "wcs": float(view.wcs)}
            for split, view in result.aggregate_views.items()
        },
        "aggregate_metrics": [
            {
                "split": record.split,
                "metric": metric_key(record.metric),
                "count": int(record.count),
                "rmse": float(record.rmse),
                "mae": float(record.mae),
                "nrmse": float(record.nrmse),
                "bias": float(record.bias),
                "pearson_r": float(record.pearson_r),
                "nse": float(record.nse),
                "d1": float(record.d1),
                "wcs": float(record.wcs),
            }
            for record in result.aggregate_metrics
        ],
        "comparable_metrics": [metric_key(name) for name in result.comparable_metrics],
    }


def deserialize_evaluation_result(payload: dict) -> EvaluationResult:
    aggregate_views = {
        str(split): AggregateView(
            split=str(item.get("split", split)),
            mean_nrmse=float(item.get("mean_nrmse", float("nan"))),
            wcs=float(item.get("wcs", float("nan"))),
        )
        for split, item in dict(payload.get("aggregate_views", {})).items()
    }
    aggregate_metrics = [
        AggregateMetricRecord(
            split=str(item.get("split", "")),
            metric=metric_key(item.get("metric", "")),
            count=int(item.get("count", 0)),
            rmse=float(item.get("rmse", float("nan"))),
            mae=float(item.get("mae", float("nan"))),
            nrmse=float(item.get("nrmse", float("nan"))),
            bias=float(item.get("bias", float("nan"))),
            pearson_r=float(item.get("pearson_r", float("nan"))),
            nse=float(item.get("nse", float("nan"))),
            d1=float(item.get("d1", float("nan"))),
            wcs=float(item.get("wcs", float("nan"))),
        )
        for item in list(payload.get("aggregate_metrics", []))
    ]
    metrics_by_trt = {
        int(trt): {metric_key(name): float(value) for name, value in dict(metrics).items()}
        for trt, metrics in dict(payload.get("metrics_by_trt", {})).items()
    }
    comparable_metrics = [metric_key(name) for name in list(payload.get("comparable_metrics", []))]
    return EvaluationResult(
        metrics_by_trt=metrics_by_trt,
        aggregate_views=aggregate_views,
        aggregate_metrics=aggregate_metrics,
        comparable_metrics=comparable_metrics,
    )


def build_evaluation_result_line(result: EvaluationResult, prefix: str = "RESULT_SCHEMA_JSON") -> str:
    return f"{str(prefix).strip()}: {json.dumps(serialize_evaluation_result(result), sort_keys=True)}"


def extract_evaluation_result(text: str, prefix: str = "RESULT_SCHEMA_JSON") -> EvaluationResult | None:
    pattern = re.compile(rf"^{re.escape(str(prefix).strip())}:\s*(\{{.*\}})\s*$")
    for raw_line in str(text).splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        return deserialize_evaluation_result(json.loads(match.group(1)))
    return None


def build_pest_output_text(
    metrics_by_trt: MetricsByTreatment,
    trts: list[int],
    trts_env: str,
    var_codes: list[str],
    wht_dates_by_trt: dict[int, list[int]],
) -> str:
    context = resolve_output_context(trts, trts_env, var_codes, wht_dates_by_trt)
    return build_pest_output_text_from_context(metrics_by_trt, context)


__all__ = [
    "AggregateMetricRecord",
    "AggregateMetricExportRow",
    "AGGREGATE_METRIC_EXPORT_FIELDNAMES",
    "COMPARE_SUMMARY_FIELDNAMES",
    "AggregateView",
    "EvaluationResult",
    "ExperimentExportContext",
    "FIGURE_READY_EXPORT_FIELDNAMES",
    "MatrixSummaryView",
    "MetricValue",
    "MetricsByTreatment",
    "PestOutputContext",
    "PestOutputRecord",
    "RESIDUAL_EXPORT_BASE_FIELDNAMES",
    "SCATTER_EXPORT_FIELDNAMES",
    "SUMMARY_EXPORT_FIELDNAMES",
    "TREATMENT_METRIC_EXPORT_FIELDNAMES",
    "TreatmentMetricExportRow",
    "TreatmentMetrics",
    "TreatmentComparisonRecord",
    "build_aggregate_metric_export_value_map",
    "aggregate_value_map",
    "build_aggregate_metric_export_rows",
    "build_combo_key",
    "build_compare_summary_fieldnames",
    "build_evaluation_result",
    "build_evaluation_result_line",
    "build_experiment_export_context",
    "build_figure_ready_export_row",
    "build_matrix_summary_view",
    "build_pest_output_text",
    "build_pest_output_text_from_context",
    "build_residual_export_fieldnames",
    "build_residual_export_row",
    "build_scatter_export_row",
    "build_summary_export_row",
    "build_treatment_metric_export_value_map",
    "build_treatment_metric_export_rows",
    "build_treatment_comparison_records",
    "build_split_mean_name",
    "build_split_metric_name",
    "build_summary_metric_name",
    "build_timeseries_metric_name",
    "deserialize_evaluation_result",
    "extract_evaluation_result",
    "extract_matrix_summary_view",
    "format_export_float",
    "format_summary_schema_value",
    "is_single_treatment_layout",
    "iter_aggregate_value_records",
    "iter_pest_output_records",
    "metric_key",
    "resolve_aggregate_value",
    "resolve_output_context",
    "serialize_evaluation_result",
]
