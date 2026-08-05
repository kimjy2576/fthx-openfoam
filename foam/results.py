"""
F5 후처리 — OpenFOAM 케이스 → `results.csv` (기존 스키마 그대로)

지표 계산·CSV 스키마는 core 의 `fthx.post` 를 그대로 씀. 이 모듈이 하는 일은
**OpenFOAM 의 postProcessing 디렉터리를 post.FIELDS 계약으로 번역**하는 것뿐.
Fluent 저널이 results.csv 를 직접 쓰는 것과 같은 자리에 놓임.

    postProcessing/{pIn,pOut,Tout}/<시각>/surfaceFieldValue.dat
        →  {"p_air_in", "p_air_out", "t_air_out"}
        →  post.metrics() → post.to_row() → results.csv

thermal 케이스는 p 가 절대압[Pa] 이라 그대로, 등온 케이스는 kinematic
(p/rho) 이라 rho 를 곱해 Pa 로 맞춘다.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from fthx import post
from fthx.params import FTHXParams

from ._thermal_closure import core_volume_m3
from .jf_inject import load_jf


def _latest(case: Path, name: str) -> float | None:
    """postProcessing/<name>/<가장 늦은 시각>/*.dat 의 마지막 값."""
    root = case / "postProcessing" / name
    if not root.is_dir():
        return None
    dirs = sorted((d for d in root.iterdir() if d.is_dir()),
                  key=lambda d: float(d.name))
    for d in reversed(dirs):
        for f in d.glob("*.dat"):
            rows = [l for l in f.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.startswith("#")]
            if rows:
                return float(rows[-1].split()[-1])
    return None


def read_case(case_dir: str | Path, p: FTHXParams) -> dict:
    """OpenFOAM 결과 → post.FIELDS 계약의 raw dict."""
    case = Path(case_dir)
    thermal = (case / "0" / "T").exists()
    rho = p.operating_derived()["air"]["rho"]
    scale = 1.0 if thermal else rho          # 등온은 kinematic p

    pin, pout = _latest(case, "pIn"), _latest(case, "pOut")
    raw: dict = {}
    if pin is not None:
        raw["p_air_in"] = pin * scale
        raw["p_air_out"] = (pout or 0.0) * scale
    tout = _latest(case, "Tout")
    if tout is not None:
        raw["t_air_out"] = tout
    raw["_thermal"] = thermal
    log = case / "log.solver"
    if log.exists():
        txt = log.read_text(encoding="utf-8", errors="ignore")
        # residualControl 도달이면 converged, endTime 도달이면 미수렴 종료
        raw["_converged"] = "SIMPLE solution converged" in txt
        raw["_end_reached"] = txt.rstrip().endswith("End")
    else:
        raw["_converged"] = None
    return raw


def _cells(case: Path) -> dict:
    """메시 규모 — 재현성 추적용 (Fluent 경로에서 코어 수가 셀을 바꿨던 교훈)."""
    out = {}
    owner = case / "constant" / "polyMesh" / "owner"
    if owner.exists():
        head = owner.read_text(encoding="utf-8", errors="ignore")[:2000]
        for tag in ("nCells", "nPoints", "nFaces"):
            i = head.find(tag)
            if i > 0:
                out[tag] = int(head[i + len(tag):].split(":")[1].split()[0]
                               if ":" in head[i:i + 40] else 0) or None
    z = case / "constant" / "polyMesh" / "cellZones"
    if z.exists():
        t = z.read_text(encoding="utf-8", errors="ignore")
        if "names" in t:
            out["cellZones"] = t.split("names")[1].split("(")[1].split(")")[0].split()
    return out


def write_results(case_dir: str | Path, p: FTHXParams,
                  csv_path: str | Path = None, jf: dict | None = None,
                  n_circuit: int = 1) -> dict:
    """케이스 → 지표 + results.csv 한 행. 기존 행이 있으면 이어붙임."""
    case = Path(case_dir)
    raw = read_case(case, p)
    m = post.metrics(p, raw, n_circuit)

    # 예측 대비 — 상관식/단위셀 어느 기준인지 함께 기록
    from ._thermal_closure import ua_predicted
    pred = ua_predicted(p, n_circuit, jf=jf)
    extra = {
        "solver": "buoyantSimpleFoam" if raw.get("_thermal") else "simpleFoam",
        "path": "openfoam",
        "jf_source": (jf or {}).get("source", "closure"),
        "j_used": (jf or {}).get("j"), "f_used": (jf or {}).get("f"),
        "UA_pred_W_K": pred["UA_W_K"],
        "UA_air_pred_W_K": pred["UA_air_W_K"],
        "UA_ref_pred_W_K": pred["UA_ref_W_K"],
        "V_core_m3": core_volume_m3(p),
        "converged": raw.get("_converged"),
        "end_reached": raw.get("_end_reached"),
    }
    if "UA_W_K" in m and pred["UA_W_K"]:
        extra["UA_err_pct"] = (m["UA_W_K"] - pred["UA_W_K"]) / pred["UA_W_K"] * 100.0
    extra.update({k: v for k, v in _cells(case).items() if k != "cellZones"})

    row = post.to_row(p, m, extra)
    out = Path(csv_path or (case / "results.csv"))
    exists = out.exists()
    prev = list(csv.DictReader(out.open(encoding="utf-8"))) if exists else []
    fields = list(dict.fromkeys(
        [k for r in prev for k in r] + list(row)))
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in prev + [row]:
            w.writerow(r)
    return {"row": row, "metrics": m, "csv": str(out)}
