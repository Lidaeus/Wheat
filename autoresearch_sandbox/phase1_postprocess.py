import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path


def safe_float(value: str | None, default: float = 999.0) -> float:
    try:
        return float(value) if value not in ("", None) else default
    except (TypeError, ValueError):
        return default


def infer_crop(row: dict) -> str:
    run_id = str(row.get("run_id", "")).lower()
    workspace_name = Path(str(row.get("workspace_dir", "")).strip()).parent.name.lower()
    for crop in ("wheat", "maize", "soybean", "rice", "cotton"):
        if workspace_name.startswith(f"{crop}_") or f"_{crop}_" in run_id or run_id.startswith(f"b0_{crop}") or run_id.startswith(f"b1_{crop}") or run_id.startswith(f"b2_{crop}"):
            return crop
    return "unknown"


def load_tsv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def finite_population_std(values: list[float]) -> float:
    finite_values = [float(value) for value in values if math.isfinite(float(value))]
    if len(finite_values) <= 1:
        return 0.0
    mean_value = sum(finite_values) / len(finite_values)
    variance = sum((value - mean_value) ** 2 for value in finite_values) / len(finite_values)
    return math.sqrt(max(variance, 0.0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()

    output_dir = Path(args.input_dir).resolve()
    summary_path = output_dir / "phase1_experiment_summary.tsv"
    if not summary_path.exists():
        print("Summary TSV not found. Please run experiments first.")
        return

    runs = load_tsv_rows(summary_path)
    if not runs:
        print("Summary TSV is empty.")
        return

    for row in runs:
        row["crop"] = infer_crop(row)

    param_rows = load_tsv_rows(output_dir / "phase1_parameters.tsv")
    agg_rows = load_tsv_rows(output_dir / "phase1_aggregate_metrics.tsv")

    run_params: dict[str, list[dict]] = defaultdict(list)
    for row in param_rows:
        run_id = row.get("run_id", "")
        run_params[run_id].append({
            "name": row.get("param_name", ""),
            "distance_to_b0": safe_float(row.get("normalized_distance_to_b0"), 0.0),
            "hit_bound": str(row.get("is_at_lower_bound", "")).lower() == "true" or str(row.get("is_at_upper_bound", "")).lower() == "true",
        })

    run_aggs: dict[str, list[dict]] = defaultdict(list)
    for row in agg_rows:
        run_aggs[row.get("run_id", "")].append(row)

    b0_scores: dict[str, float] = {}
    b1_scores: dict[str, float] = {}
    for row in runs:
        crop = row["crop"]
        combo_key = row.get("combo_key", "")
        score = safe_float(row.get("score"))
        if combo_key == "B0":
            b0_scores[crop] = score
        elif combo_key == "B1":
            b1_scores[crop] = score

    derived_rows: list[dict] = []
    for row in runs:
        crop = row["crop"]
        run_id = row.get("run_id", "")
        score = safe_float(row.get("score"))
        train_mean = safe_float(row.get("train_mean_nrmse"))
        valid_mean = safe_float(row.get("valid_mean_nrmse"))
        all_mean = safe_float(row.get("all_mean_nrmse"))
        b0 = b0_scores.get(crop, 999.0)
        b1 = b1_scores.get(crop, 999.0)
        params = run_params.get(run_id, [])
        train_aggs = [item for item in run_aggs.get(run_id, []) if item.get("split") == "train"]
        valid_aggs = [item for item in run_aggs.get(run_id, []) if item.get("split") == "valid"]
        balance_pool = valid_aggs if valid_aggs else train_aggs
        balance_values = [safe_float(item.get("nrmse"), float("nan")) for item in balance_pool if item.get("metric")]
        generalization_gap = valid_mean - train_mean if valid_mean != 999.0 and train_mean != 999.0 else 0.0
        boundary_hit_rate = (sum(1 for item in params if item["hit_bound"]) / len(params)) if params else 0.0
        param_shift_norm = (sum(item["distance_to_b0"] for item in params) / len(params)) if params else 0.0
        group_balance_index = finite_population_std(balance_values)
        derived = dict(row)
        derived["delta_vs_b0"] = f"{(score - b0):.6f}" if b0 != 999.0 else ""
        derived["delta_vs_b1"] = f"{(score - b1):.6f}" if b1 != 999.0 else ""
        derived["better_than_b0"] = "True" if b0 != 999.0 and score < b0 else "False"
        derived["generalization_gap"] = f"{generalization_gap:.6f}"
        derived["boundary_hit_rate"] = f"{boundary_hit_rate:.6f}"
        derived["param_shift_norm"] = f"{param_shift_norm:.6f}"
        derived["group_balance_index"] = f"{group_balance_index:.6f}"
        derived["primary_score"] = f"{(valid_mean if valid_mean != 999.0 else all_mean):.6f}" if (valid_mean != 999.0 or all_mean != 999.0) else ""
        derived["eval_call_count"] = f"{safe_float(row.get('eval_call_count'), 0.0):.0f}"
        derived["run_model_invocations"] = f"{safe_float(row.get('run_model_invocations'), 0.0):.0f}"
        derived["dssat_treatment_calls"] = f"{safe_float(row.get('dssat_treatment_calls'), 0.0):.0f}"
        derived["dssat_wall_sec"] = f"{safe_float(row.get('dssat_wall_sec'), 0.0):.6f}"
        derived_rows.append(derived)

    derived_fields = list(derived_rows[0].keys())
    write_tsv(output_dir / "phase1_derived_metrics.tsv", derived_rows, derived_fields)

    combo_groups: dict[tuple[str, str, str, str, str, str, str], list[dict]] = defaultdict(list)
    for row in derived_rows:
        key = (
            row.get("crop", ""),
            row.get("combo_key", ""),
            row.get("plan", ""),
            row.get("weight", ""),
            row.get("engine", ""),
            row.get("sequence", ""),
            row.get("grouping", ""),
        )
        combo_groups[key].append(row)

    combo_summary_rows: list[dict] = []
    for key, rows in combo_groups.items():
        crop, combo_key, plan, weight, engine, sequence, grouping = key
        scores = [safe_float(row.get("score")) for row in rows if safe_float(row.get("score")) != 999.0]
        primary_scores = [safe_float(row.get("primary_score")) for row in rows if safe_float(row.get("primary_score")) != 999.0]
        boundary_hits = [safe_float(row.get("boundary_hit_rate"), 0.0) for row in rows]
        param_shifts = [safe_float(row.get("param_shift_norm"), 0.0) for row in rows]
        balance_values = [safe_float(row.get("group_balance_index"), 0.0) for row in rows]
        eval_calls = [safe_float(row.get("eval_call_count"), 0.0) for row in rows]
        run_model_calls = [safe_float(row.get("run_model_invocations"), 0.0) for row in rows]
        dssat_calls = [safe_float(row.get("dssat_treatment_calls"), 0.0) for row in rows]
        dssat_wall_secs = [safe_float(row.get("dssat_wall_sec"), 0.0) for row in rows]
        success_count = sum(1 for row in rows if row.get("status") == "success")
        better_than_b0_count = sum(1 for row in rows if row.get("better_than_b0") == "True")
        combo_summary_rows.append({
            "crop": crop,
            "combo_key": combo_key,
            "plan": plan,
            "weight": weight,
            "engine": engine,
            "sequence": sequence,
            "grouping": grouping,
            "run_count": len(rows),
            "success_count": success_count,
            "failure_rate": f"{(1 - (success_count / len(rows))):.6f}" if rows else "0.000000",
            "score_mean": f"{statistics.mean(scores):.6f}" if scores else "",
            "score_std": f"{finite_population_std(scores):.6f}",
            "primary_score_mean": f"{statistics.mean(primary_scores):.6f}" if primary_scores else "",
            "primary_score_std": f"{finite_population_std(primary_scores):.6f}",
            "better_than_b0_rate": f"{(better_than_b0_count / len(rows)):.6f}" if rows else "0.000000",
            "boundary_hit_rate_mean": f"{statistics.mean(boundary_hits):.6f}" if boundary_hits else "0.000000",
            "param_shift_norm_mean": f"{statistics.mean(param_shifts):.6f}" if param_shifts else "0.000000",
            "group_balance_index_mean": f"{statistics.mean(balance_values):.6f}" if balance_values else "0.000000",
            "eval_call_count_mean": f"{statistics.mean(eval_calls):.6f}" if eval_calls else "0.000000",
            "run_model_invocations_mean": f"{statistics.mean(run_model_calls):.6f}" if run_model_calls else "0.000000",
            "dssat_treatment_calls_mean": f"{statistics.mean(dssat_calls):.6f}" if dssat_calls else "0.000000",
            "dssat_wall_sec_mean": f"{statistics.mean(dssat_wall_secs):.6f}" if dssat_wall_secs else "0.000000",
        })

    if combo_summary_rows:
        combo_fields = list(combo_summary_rows[0].keys())
        write_tsv(output_dir / "phase1_combo_summary.tsv", combo_summary_rows, combo_fields)

    print(f"Derived metrics persisted to {output_dir}")


if __name__ == "__main__":
    main()
