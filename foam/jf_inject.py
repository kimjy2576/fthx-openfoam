"""
D → B 주입 — 주기 단위셀에서 뽑은 j/f 로 풀사이즈 포러스 계수를 대체.

계획서의 멀티스케일 규약을 닫는 지점:
    D(주기셀, 핀 실형상) ──j/f──▶ B(풀사이즈 포러스)

구현 방식은 **비율 스케일**. closure.air_side() 가 이미
    C2 ∝ f,   h ∝ j,   hv = h·a_v
로 산출하므로, 상관식 j/f 대신 단위셀 j/f 를 쓰려면 그 비율만 곱하면 됨.
같은 공식을 다시 쓰지 않으므로 중복 구현이 아니고, closure 가 갱신되면
그대로 따라감.

j/f 출처는 JSON 한 장:
    {"j": 0.0424, "f": 0.0566, "Re_Dc": 1772.7, "source": "openfoam_cell",
     "note": "...", "effectiveness": 0.967}
`scripts/make_jf.py` 가 단위셀 결과에서 이 파일을 만들고,
`write_case(..., jf=...)` 가 읽어 씀.
"""
from __future__ import annotations

import json
from pathlib import Path

from fthx import closure
from fthx.params import FTHXParams


def load_jf(path: str | Path) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    for k in ("j", "f"):
        if k not in d:
            raise ValueError(f"j/f 파일에 '{k}' 없음: {path}")
    return d


def scaled_air_side(p: FTHXParams, jf: dict | None = None) -> dict:
    """closure.air_side() 결과에 단위셀 j/f 비율을 적용.

    jf=None 이면 상관식 그대로 (기존 동작 유지).
    """
    a = dict(closure.air_side(p))
    a["jf_source"] = "closure"
    if not jf:
        return a

    j_c, f_c = a["j"], a["f"]
    if j_c <= 0 or f_c <= 0:
        raise ValueError("상관식 j/f 가 0 이하 — 비율 스케일 불가")
    rj, rf = jf["j"] / j_c, jf["f"] / f_c

    a["j_correlation"], a["f_correlation"] = j_c, f_c
    a["j"], a["f"] = jf["j"], jf["f"]
    a["ratio_j"], a["ratio_f"] = rj, rf
    a["C2_1perm"] *= rf                       # dp ∝ f
    a["dp_core_Pa"] *= rf
    if a.get("alpha_m2"):
        a["alpha_m2"] /= rf                   # dp ∝ 1/alpha
    a["h_W_m2K"] *= rj                        # h ∝ j
    a["hv_W_m3K"] *= rj
    a["jf_source"] = jf.get("source", "cell")
    a["jf_note"] = jf.get("note", "")
    a["correlation"] = f"unit cell CFD (j×{rj:.2f}, f×{rf:.2f} vs plain)"
    return a


def compare(p: FTHXParams, jf: dict) -> dict:
    """상관식 기반 vs 단위셀 기반 — 무엇이 얼마나 바뀌는지."""
    base = scaled_air_side(p, None)
    cell = scaled_air_side(p, jf)
    keys = ("j", "f", "C2_1perm", "dp_core_Pa", "h_W_m2K", "hv_W_m3K")
    return {k: {"closure": base[k], "cell": cell[k],
                "ratio": (cell[k] / base[k]) if base[k] else None}
            for k in keys}
