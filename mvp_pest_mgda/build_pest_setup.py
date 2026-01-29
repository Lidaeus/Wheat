from __future__ import annotations

import subprocess
from pathlib import Path

import pyemu


def _read_params(params_path: Path) -> dict[str, float]:
    params: dict[str, float] = {}
    for raw in params_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        params[parts[0].strip().lower()] = float(parts[1])
    return params


def _extract_measured(eval_path: Path) -> dict[str, float]:
    lines = eval_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = None
    last_row = None
    for line in lines:
        if line.startswith("@RUN"):
            header = line
            continue
        if header and line.strip() and line.lstrip()[0].isdigit():
            last_row = line
    if not header or not last_row:
        raise RuntimeError("Evaluate.OUT did not contain expected table")
    cols = header.split()
    vals = last_row.split()
    row = dict(zip(cols, vals))
    return {"hwam": float(row["HWAMM"]), "laix": float(row["LAIXM"]) }


def main() -> None:
    cwd = Path.cwd()
    dssat_dir = Path(__file__).resolve().parents[1]

    subprocess.run(["python", "run_model.py"], cwd=str(cwd), check=True)
    obs = _extract_measured(dssat_dir / "Evaluate.OUT")
    params = _read_params(cwd / "params.dat")

    pst = pyemu.utils.helpers.pst_from_io_files(
        tpl_files=["params.tpl"],
        in_files=["params.dat"],
        ins_files=["pest_out.ins"],
        out_files=["pest_out.dat"],
        pst_filename="ksas_mvp.pst",
    )

    pst.model_commandline = ["python run_model.py"]
    pst.control_data.noptmax = -1
    pst.control_data.pestmode = "estimation"

    pst.parameter_data.loc["sh2o_15", "parlbnd"] = 0.05
    pst.parameter_data.loc["sh2o_15", "parubnd"] = 0.40
    pst.parameter_data.loc["sh2o_30", "parlbnd"] = 0.05
    pst.parameter_data.loc["sh2o_30", "parubnd"] = 0.40

    pst.parameter_data.loc["sh2o_15", "pargp"] = "g_sh2o"
    pst.parameter_data.loc["sh2o_30", "pargp"] = "g_sh2o"

    pst.parameter_data.loc["sh2o_15", "partrans"] = "none"
    pst.parameter_data.loc["sh2o_30", "partrans"] = "none"

    pst.parameter_data.loc["sh2o_15", "parval1"] = float(params.get("sh2o_15", 0.205))
    pst.parameter_data.loc["sh2o_30", "parval1"] = float(params.get("sh2o_30", 0.170))

    pst.parameter_groups.index = pst.parameter_groups.pargpnme
    if "g_sh2o" not in pst.parameter_groups.index and "pargp" in pst.parameter_groups.index:
        pst.parameter_groups.rename(index={"pargp": "g_sh2o"}, inplace=True)
        pst.parameter_groups.loc["g_sh2o", "pargpnme"] = "g_sh2o"
    pst.parameter_groups.loc["g_sh2o", "inctyp"] = "absolute"
    pst.parameter_groups.loc["g_sh2o", "derinc"] = 0.05

    pst.observation_data.loc["hwam", "obsval"] = obs["hwam"]
    pst.observation_data.loc["laix", "obsval"] = obs["laix"]

    pst.observation_data.loc["hwam", "obgnme"] = "obs_yield"
    pst.observation_data.loc["laix", "obgnme"] = "obs_laix"

    pst.write(cwd / "ksas_mvp.pst")


if __name__ == "__main__":
    main()
