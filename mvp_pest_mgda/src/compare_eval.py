from __future__ import annotations

import math
from pathlib import Path
from typing import TypedDict

from observations import read_wht_dates_by_trt


class TrtRow(TypedDict):
    scenario: str
    trt: int
    obs_yield: float
    sim_yield: float
    obs_laix: float
    sim_laix: float
    phi: float
    phi_w: float
    n_wht_dates: int
    phi_laid: float
    n_wht_swad: int


def _read_summary_measurements(
    a_path: Path,
    trts: list[int],
    yield_var: str,
    laix_var: str,
) -> dict[str, float]:
    if not a_path.exists():
        return {}
    lines = a_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = next((line for line in lines if line.startswith("@TRNO")), None)
    if not header:
        return {}
    columns = [column.lstrip("@").upper() for column in header.split()]
    if "TRNO" not in columns or yield_var.upper() not in columns:
        return {}
    i_trno = columns.index("TRNO")
    i_yield = columns.index(yield_var.upper())
    i_laix = columns.index(laix_var.upper()) if laix_var.upper() in columns else -1
    measurements: dict[str, float] = {}
    wanted = {int(trt) for trt in trts}
    for line in lines:
        if not line.strip() or line.startswith(("@", "*", "!")):
            continue
        parts = line.split()
        if len(parts) <= max(i_trno, i_yield, i_laix):
            continue
        try:
            trno = int(parts[i_trno])
        except ValueError:
            continue
        if trno not in wanted:
            continue
        try:
            measurements[f"{yield_var.lower()}_t{trno:02d}"] = float(parts[i_yield])
        except ValueError:
            pass
        if i_laix >= 0:
            try:
                measurements[f"{laix_var.lower()}_t{trno:02d}"] = float(parts[i_laix])
            except ValueError:
                pass
    return measurements


def _read_wht_measurements(
    wht_path: Path,
    trts: list[int],
) -> tuple[dict[str, float], dict[int, list[int]]]:
    if not wht_path.exists():
        return {}, {}
    lines = wht_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = next((line for line in lines if line.startswith("@TRNO")), None)
    if not header:
        return {}, {}
    columns = [column.lstrip("@").upper() for column in header.split()]
    if "TRNO" not in columns or "DATE" not in columns or "LAID" not in columns:
        return {}, read_wht_dates_by_trt(wht_path, trts)
    i_trno = columns.index("TRNO")
    i_date = columns.index("DATE")
    i_laid = columns.index("LAID")
    wanted = {int(trt) for trt in trts}
    measurements: dict[str, float] = {}
    dates_by_trt = read_wht_dates_by_trt(wht_path, trts)
    for line in lines:
        if not line.strip() or line.startswith(("@", "*", "!")):
            continue
        parts = line.split()
        if len(parts) <= max(i_trno, i_date, i_laid):
            continue
        try:
            trno = int(parts[i_trno])
            date = int(parts[i_date])
            laid = float(parts[i_laid])
        except ValueError:
            continue
        if trno not in wanted:
            continue
        measurements[f"laid_t{trno:02d}_d{date}"] = laid
    return measurements, dates_by_trt


def load_measurements(
    a_path: Path,
    wht_path: Path | None,
    trts: list[int],
    yield_var: str,
    laix_var: str,
) -> tuple[dict[str, float], dict[int, list[int]]]:
    measurements = _read_summary_measurements(a_path, trts, yield_var, laix_var)
    if wht_path is None:
        return measurements, {}
    wht_measurements, wht_dates = _read_wht_measurements(wht_path, trts)
    measurements.update(wht_measurements)
    return measurements, wht_dates


def build_trt_rows(
    sim_results: dict[str, dict[str, float]],
    measurements: dict[str, float],
    weights: dict[str, float],
    trts: list[int],
    yield_var: str,
    laix_var: str,
    wht_dates: dict[int, list[int]],
) -> list[TrtRow]:
    rows: list[TrtRow] = []
    for scenario, sim in sim_results.items():
        if not sim:
            continue
        for trt in trts:
            yield_key = f"{yield_var.lower()}_t{trt:02d}"
            laix_key = f"{laix_var.lower()}_t{trt:02d}"
            obs_yield = measurements.get(yield_key, float("nan"))
            sim_yield = sim.get(yield_key, float("nan"))
            obs_laix = measurements.get(laix_key, float("nan"))
            sim_laix = sim.get(laix_key, float("nan"))
            weight_yield = weights.get(yield_key, 1.0)
            weight_laix = weights.get(laix_key, 1.0)
            phi_yield_weighted = ((sim_yield - obs_yield) * weight_yield) ** 2 if math.isfinite(sim_yield - obs_yield) else 0.0
            phi_laix_weighted = ((sim_laix - obs_laix) * weight_laix) ** 2 if math.isfinite(sim_laix - obs_laix) else 0.0
            phi_laid = 0.0
            phi_laid_weighted = 0.0
            n_wht_dates = 0
            for date in wht_dates.get(trt, []):
                laid_key = f"laid_t{trt:02d}_d{date}"
                if laid_key not in sim or laid_key not in measurements:
                    continue
                error = sim[laid_key] - measurements[laid_key]
                weight = weights.get(laid_key, 1.0)
                phi_laid += error * error
                phi_laid_weighted += (error * weight) ** 2
                n_wht_dates += 1
            phi_yield = (sim_yield - obs_yield) ** 2 if math.isfinite(sim_yield - obs_yield) else 0.0
            phi_laix = (sim_laix - obs_laix) ** 2 if math.isfinite(sim_laix - obs_laix) else 0.0
            rows.append(
                {
                    "scenario": scenario,
                    "trt": trt,
                    "obs_yield": obs_yield,
                    "sim_yield": sim_yield,
                    "obs_laix": obs_laix,
                    "sim_laix": sim_laix,
                    "phi": phi_yield + phi_laix + phi_laid,
                    "phi_w": phi_yield_weighted + phi_laix_weighted + phi_laid_weighted,
                    "n_wht_dates": n_wht_dates,
                    "phi_laid": phi_laid,
                    "n_wht_swad": 0,
                }
            )
    return rows


def calc_summary(rows: list[TrtRow]) -> dict[str, float | int]:
    if not rows:
        return {
            "n_trt": 0,
            "rmse_yield": float("nan"),
            "mae_yield": float("nan"),
            "bias_yield": float("nan"),
            "rmse_laix": float("nan"),
            "mae_laix": float("nan"),
            "bias_laix": float("nan"),
            "phi_w": 0.0,
        }
    yield_rows = [row for row in rows if math.isfinite(row["obs_yield"]) and math.isfinite(row["sim_yield"])]
    laix_rows = [row for row in rows if math.isfinite(row["obs_laix"]) and math.isfinite(row["sim_laix"])]
    rmse_yield = (
        sum((row["sim_yield"] - row["obs_yield"]) ** 2 for row in yield_rows) / len(yield_rows)
    ) ** 0.5 if yield_rows else float("nan")
    mae_yield = (
        sum(abs(row["sim_yield"] - row["obs_yield"]) for row in yield_rows) / len(yield_rows)
    ) if yield_rows else float("nan")
    bias_yield = (
        sum(row["sim_yield"] - row["obs_yield"] for row in yield_rows) / len(yield_rows)
    ) if yield_rows else float("nan")
    mean_obs_yield = (
        sum(row["obs_yield"] for row in yield_rows) / len(yield_rows)
    ) if yield_rows else 0.0
    re_yield = (mae_yield / mean_obs_yield * 100.0) if (yield_rows and mean_obs_yield != 0) else float("nan")
    rmse_laix = (
        sum((row["sim_laix"] - row["obs_laix"]) ** 2 for row in laix_rows) / len(laix_rows)
    ) ** 0.5 if laix_rows else float("nan")
    mae_laix = (
        sum(abs(row["sim_laix"] - row["obs_laix"]) for row in laix_rows) / len(laix_rows)
    ) if laix_rows else float("nan")
    bias_laix = (
        sum(row["sim_laix"] - row["obs_laix"] for row in laix_rows) / len(laix_rows)
    ) if laix_rows else float("nan")
    mean_obs_laix = (
        sum(row["obs_laix"] for row in laix_rows) / len(laix_rows)
    ) if laix_rows else 0.0
    re_laix = (mae_laix / mean_obs_laix * 100.0) if (laix_rows and mean_obs_laix != 0) else float("nan")
    return {
        "n_trt": len(rows),
        "rmse_yield": rmse_yield,
        "mae_yield": mae_yield,
        "bias_yield": bias_yield,
        "re_yield": re_yield,
        "rmse_laix": rmse_laix,
        "mae_laix": mae_laix,
        "bias_laix": bias_laix,
        "re_laix": re_laix,
        "phi": sum(row["phi"] for row in rows),
        "phi_w": sum(row["phi_w"] for row in rows),
        "n_wht": sum(row["n_wht_dates"] for row in rows),
    }


def build_summary_rows(
    scenarios: list[str],
    rows: list[TrtRow],
) -> list[dict[str, str | float | int]]:
    summary_rows: list[dict[str, str | float | int]] = []
    for scenario in scenarios:
        scenario_rows = [row for row in rows if row["scenario"] == scenario]
        if not scenario_rows:
            continue
        summary = calc_summary(scenario_rows)
        summary_rows.append({**summary, "scenario": scenario})
    return summary_rows
