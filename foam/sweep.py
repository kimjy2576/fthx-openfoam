"""
파라미터 스윕 — 조합별 케이스를 무인으로 생성·실행·수확.

Fluent 경로의 36조합 100% 무인 성공에 대응하는 OpenFOAM 판.
라이선스·큐가 없으므로 대기 없이 순차 실행되고, 실패한 조합은 건너뛰고
계속 진행하되 사유를 기록한다 (한 조합 실패로 전체가 멈추지 않게).

각 조합은 프리셋을 복제한 뒤 지정된 필드만 덮어쓴다. 결과는 한 CSV 에
누적되므로 `results.csv` 한 장이 곧 설계공간 표가 된다.
"""
from __future__ import annotations

import itertools
import json
import shutil
import subprocess
import time
from pathlib import Path

from fthx.params import FTHXParams

from .openfoam import write_case
from .results import write_results


def expand(grid: dict) -> list[dict]:
    """{"V_face":[1,2], "FPI":[12,14]} → 4 조합"""
    keys = list(grid)
    return [dict(zip(keys, v)) for v in itertools.product(*(grid[k] for k in keys))]


def apply_overrides(p: FTHXParams, ov: dict) -> FTHXParams:
    """점 표기('operating.air.V_face')와 단축키를 모두 지원."""
    alias = {"V_face": "operating.air.V_face",
             "T_air_in": "operating.air.T_in",
             "T_sat": "operating.ref.T_sat_in",
             "FPI": "fin.FPI", "fin_type": "fin.fin_type",
             "Pt": "tube.Pt", "Pl": "tube.Pl",
             "Do": "tube.Do", "Nr": "tube.Nr", "Nt": "tube.Nt"}
    d = p.model_dump()
    for k, v in ov.items():
        path = alias.get(k, k).split(".")
        node = d
        for s in path[:-1]:
            node = node[s]
        node[path[-1]] = v
    return FTHXParams(**d)


def case_label(ov: dict) -> str:
    def fmt(v):
        return (f"{v:g}".replace(".", "p") if isinstance(v, (int, float))
                else str(v))
    return "_".join(f"{k}{fmt(v)}" for k, v in ov.items()) or "base"


def run_sweep(base: FTHXParams, grid: dict, workdir: str | Path,
              csv_path: str | Path, jf: dict | None = None,
              np_cores: int = 8, solve: bool = True,
              keep_cases: bool = False, timeout_s: int = 3600) -> dict:
    """조합 전부를 순차 실행하고 요약을 반환.

    실패해도 다음 조합으로 진행 — 사유는 결과의 'failed' 에 쌓임.
    """
    work = Path(workdir).expanduser()
    work.mkdir(parents=True, exist_ok=True)
    combos = expand(grid)
    done, failed = [], []

    for i, ov in enumerate(combos, 1):
        label = case_label(ov)
        cdir = work / f"case_{label}"
        t0 = time.time()
        try:
            p = apply_overrides(base, ov)
            p.name = f"{base.name}__{label}"
            write_case(p, str(cdir), force=True, jf=jf)
            if solve:
                for script in ("Allrun.mesh", "Allrun.solve"):
                    env = {"FTHX_NP": str(np_cores)}
                    r = subprocess.run(["bash", f"./{script}"], cwd=cdir,
                                       capture_output=True, text=True,
                                       timeout=timeout_s,
                                       env={**_env(), **env})
                    if r.returncode != 0:
                        raise RuntimeError(
                            f"{script} 실패: {(r.stdout or r.stderr)[-400:]}")
                res = write_results(cdir, p, csv_path, jf=jf)
                row = res["row"]
            else:
                row = {"case": p.name, "note": "solve=False"}
            done.append({"label": label, "overrides": ov,
                         "UA_W_K": row.get("UA_W_K"),
                         "dP_air_Pa": row.get("dP_air_Pa"),
                         "UA_err_pct": row.get("UA_err_pct"),
                         "sec": round(time.time() - t0, 1)})
            print(f"[{i}/{len(combos)}] {label}  UA={row.get('UA_W_K')}  "
                  f"({time.time() - t0:.0f}s)", flush=True)
        except Exception as e:  # 한 조합 실패가 전체를 멈추지 않게
            failed.append({"label": label, "overrides": ov,
                           "error": f"{type(e).__name__}: {e}"[:500]})
            print(f"[{i}/{len(combos)}] {label}  실패 — {type(e).__name__}",
                  flush=True)
        finally:
            if not keep_cases and cdir.exists():
                shutil.rmtree(cdir, ignore_errors=True)

    summary = {"n": len(combos), "ok": len(done), "failed": len(failed),
               "csv": str(csv_path), "done": done, "errors": failed}
    (work / "sweep_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def _env() -> dict:
    import os
    return dict(os.environ)
