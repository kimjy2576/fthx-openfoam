"""열 폐합 — core 의 closure 를 그대로 쓰고 OpenFOAM 단위로만 변환.

Fluent M4 와 동일한 물리:
    포러스 코어 체적 열원   q‴ = hv · (T_ref − T),   hv = η_o · h · a_v
    (냉매 등온 가정 — 단상·관내 온도변화 작음)

엔탈피 방정식(buoyantSimpleFoam)용 변환:
    h = cp·T  →  q‴ = hv·T_ref − (hv/cp)·h
    fvOptions semiImplicitSource:  Su = hv·T_ref [W/m³],  Sp = −hv/cp [kg/m³s]

관벽은 셀로 풀지 않음 (B안). Bi = h·t/k ≈ 6e-4 이므로 두께 저항을
externalWallHeatFluxTemperature 의 thicknessLayers/kappaLayers 로 넘김.
"""
from __future__ import annotations

import math

from fthx import closure
from fthx.params import FTHXParams

T_STD = 298.15      # OpenFOAM sensibleEnthalpy 기준온도 [K]


def thermal_closure(p: FTHXParams, n_circuit: int = 1) -> dict:
    s = closure.summary(p, n_circuit)
    a, fin, ref = s["air"], s["fin"], s["ref"]
    od = p.operating_derived()["air"]
    cp, mu = od["cp"], od["mu"]
    k_air = 0.0263
    hv = fin["eta_overall"] * a["h_W_m2K"] * a["a_v_1perm"]      # W/m³K
    T_ref = p.operating.ref.T_sat_in + 273.15

    # 관내 냉매측 열전달계수 — Dittus-Boelter (단상, 냉각)
    Re, D = ref["Re"], p.tube.Di / 1000.0
    Pr_r = 3.0        # R410A 액상 근사 (2상 확장 시 대체)
    k_r = 0.09        # W/mK
    h_ref = 0.023 * Re ** 0.8 * Pr_r ** 0.3 * k_r / D
    t_wall = (p.tube.Do - p.tube.Di) / 2000.0                     # [m]
    k_tube = getattr(p.tube, "k_tube", 386.0)
    Bi = h_ref * t_wall / k_tube

    return {
        "hv_W_m3K": hv, "T_ref_K": T_ref, "T_air_in_K": p.operating.air.T_in + 273.15,
        # ⚠ OpenFOAM sensibleEnthalpy: h = cp·(T − T_std), T_std = 298.15 K
        #   S = hv·(T_ref − T) = hv·(T_ref − T_std) − (hv/cp)·h
        #   T_std 오프셋을 빼먹으면 목표온도가 T_ref+T_std 가 되어 가열됨
        #   (실측: T_out 412 K 로 상승)
        "T_std_K": T_STD,
        "Su": hv * (T_ref - T_STD), "Sp": -hv / cp,
        "eta_overall": fin["eta_overall"], "h_air_W_m2K": a["h_W_m2K"],
        "a_v_1perm": a["a_v_1perm"],
        "h_ref_W_m2K": h_ref, "Re_ref": Re, "t_wall_m": t_wall,
        "k_tube": k_tube, "Bi": Bi,
        "cp": cp, "mu": mu, "Pr": cp * mu / k_air,
        "m_dot_air_kgs": od["m_dot_kgs"],
        "note": "Fluent M4 equilibrium 과 동일 폐합. 관벽은 B안(두께=물성)",
    }


def ua_predicted(p: FTHXParams, n_circuit: int = 1) -> dict:
    """예측 UA — CFD 결과와 대조할 게이트값."""
    tc = thermal_closure(p, n_circuit)
    d = p.derived()
    cb = p.core_bbox                      # (x0,x1,y0,y1,z0,z1) [mm]
    V_core = ((cb[1] - cb[0]) * (cb[3] - cb[2]) * (cb[5] - cb[4])) / 1e9   # [m³]
    L_fin = cb[5] - cb[4]                 # 스팬 [mm]
    UA_air = tc["hv_W_m3K"] * V_core
    n_t = len(p.tube_centers()) if hasattr(p, "tube_centers") else 1
    A_tube = math.pi * p.tube.Di / 1000.0 * L_fin / 1000.0 * n_t
    UA_ref = tc["h_ref_W_m2K"] * A_tube
    UA = 1.0 / (1.0 / UA_air + 1.0 / max(UA_ref, 1e-9))
    return {"V_core_m3": V_core, "UA_air_W_K": UA_air,
            "UA_ref_W_K": UA_ref, "UA_W_K": UA,
            "hv_W_m3K": tc["hv_W_m3K"], "Bi": tc["Bi"]}
