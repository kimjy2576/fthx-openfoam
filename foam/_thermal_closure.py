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


def thermal_closure(p: FTHXParams, n_circuit: int = 1,
                    jf: dict | None = None) -> dict:
    from .jf_inject import scaled_air_side
    s = closure.summary(p, n_circuit)
    fin, ref = s["fin"], s["ref"]
    a = scaled_air_side(p, jf)          # 공기측만 단위셀 j/f 로 대체
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
    cb = p.core_bbox
    V_core = ((cb[1] - cb[0]) * (cb[3] - cb[2]) * (cb[5] - cb[4])) / 1e9
    L_span = (cb[5] - cb[4]) / 1000.0
    n_tube = len(p.tube_centers()) if hasattr(p, "tube_centers") else 1
    t_wall = (p.tube.Do - p.tube.Di) / 2000.0                     # [m]
    k_tube = getattr(p.tube, "k_tube", 386.0)
    Bi = h_ref * t_wall / k_tube

    # ⚠ 체적 열원 q‴ = hv·(T_ref − T) 는 냉매온도를 직접 참조하므로
    #   관측(냉매측) 열저항을 통과하지 않음. hv 를 공기측 값 그대로 쓰면
    #   CFD 가 직렬 합성 UA 보다 큰 값을 냄 (실측: 예측 8.25 vs CFD 9.84,
    #   19% — 상관식 기준에서는 두 값 차이가 13% 라 안 드러났음).
    #   → 관측 저항을 합성한 유효 hv 를 쓴다: UA_series/V_core
    A_tube_all = math.pi * p.tube.Di / 1000.0 * L_span * n_tube
    UA_ref_tot = h_ref * A_tube_all
    UA_air_tot = hv * V_core
    hv_eff = (1.0 / (1.0 / UA_air_tot + 1.0 / UA_ref_tot) / V_core
              if UA_air_tot > 0 and UA_ref_tot > 0 and V_core > 0 else hv)

    return {
        "hv_air_W_m3K": hv, "hv_W_m3K": hv_eff,
        "UA_air_W_K": UA_air_tot, "UA_ref_W_K": UA_ref_tot,
        "T_ref_K": T_ref, "T_air_in_K": p.operating.air.T_in + 273.15,
        # ⚠ OpenFOAM sensibleEnthalpy: h = cp·(T − T_std), T_std = 298.15 K
        #   S = hv·(T_ref − T) = hv·(T_ref − T_std) − (hv/cp)·h
        #   T_std 오프셋을 빼먹으면 목표온도가 T_ref+T_std 가 되어 가열됨
        #   (실측: T_out 412 K 로 상승)
        "T_std_K": T_STD,
        "Su": hv_eff * (T_ref - T_STD), "Sp": -hv_eff / cp,
        "eta_overall": fin["eta_overall"], "h_air_W_m2K": a["h_W_m2K"],
        "a_v_1perm": a["a_v_1perm"],
        "h_ref_W_m2K": h_ref, "Re_ref": Re, "t_wall_m": t_wall,
        "k_tube": k_tube, "Bi": Bi,
        "cp": cp, "mu": mu, "Pr": cp * mu / k_air,
        "m_dot_air_kgs": od["m_dot_kgs"],
        "jf_source": a.get("jf_source", "closure"),
        "note": "Fluent M4 equilibrium 과 동일 폐합. 관벽은 B안(두께=물성)",
    }


def ua_predicted(p: FTHXParams, n_circuit: int = 1,
                 jf: dict | None = None) -> dict:
    """예측 UA — CFD 결과와 대조할 게이트값 (공기측·냉매측 직렬)."""
    tc = thermal_closure(p, n_circuit, jf=jf)
    cb = p.core_bbox
    V_core = ((cb[1] - cb[0]) * (cb[3] - cb[2]) * (cb[5] - cb[4])) / 1e9
    UA = 1.0 / (1.0 / tc["UA_air_W_K"] + 1.0 / tc["UA_ref_W_K"])
    return {"V_core_m3": V_core, "UA_air_W_K": tc["UA_air_W_K"],
            "UA_ref_W_K": tc["UA_ref_W_K"], "UA_W_K": UA,
            "hv_air_W_m3K": tc["hv_air_W_m3K"], "hv_W_m3K": tc["hv_W_m3K"],
            "Bi": tc["Bi"]}
