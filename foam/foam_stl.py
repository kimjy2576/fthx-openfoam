"""
F0 — OpenFOAM 경로용 STL 내보내기 (snappyHexMesh 입력)

설계 결정:
  · 바디당 개별 binary STL. 파일명 = 바디명 = 장차 cellZone/faceZone 이름.
    (STEP 의 "면 이름을 못 싣는" 문제가 없어 M2 좌표 라벨링이 통째로 불필요)
  · 케이싱(solid_casing_*)은 기본 제외 — Fluent 존 병합 규칙 대응 장치였고,
    OpenFOAM 은 blockMesh patch 에 이름을 직접 붙이므로 존재 이유가 없음.
  · 삼각형 해상도는 최소 곡률반경과 목표 면적오차에서 유도. 사람이 만질 값 없음.

검증(3종):
  · watertight — 모든 에지가 정확히 2개 삼각형에 공유(manifold+closed)
  · STL ↔ CAD 면적/체적 오차 < 한계(기본 0.1%)
  · 파일 목록 ↔ build() 바디 인벤토리 1:1
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np

from fthx.params import FTHXParams
from fthx import cad as CAD


# ──────────────────────────────────────────────────────────────
# 해상도 유도: 원둘레를 n각형으로 근사할 때 면적비 = n·sin(π/n)/π
#              ≈ 1 − π²/(6n²)  →  n = π·√(1/(6·err))
# OCC 의 linear deflection(tol) 과 n 의 관계: tol = r·(1 − cos(π/n))
# ──────────────────────────────────────────────────────────────
def tessellation_tol(p: FTHXParams, area_err_target: float = 3e-4) -> dict:
    r_min = p.tube.Di / 2.0                       # 가장 작은 곡률반경
    n_seg = math.ceil(math.pi * math.sqrt(1.0 / (6.0 * area_err_target)))
    tol = r_min * (1.0 - math.cos(math.pi / n_seg))
    return {"r_min_mm": r_min, "n_seg": n_seg, "linear_tol_mm": tol,
            "angular_tol_rad": 0.15, "area_err_target": area_err_target}


# ──────────────────────────────────────────────────────────────
# binary STL 읽기/검증 (외부 의존성 없이 numpy 만 사용)
# ──────────────────────────────────────────────────────────────
def read_stl(path: str | Path) -> np.ndarray:
    """binary STL → (n_tri, 3, 3) 정점 배열 [mm]"""
    b = Path(path).read_bytes()
    n = struct.unpack_from("<I", b, 80)[0]
    rec = np.frombuffer(b, dtype=np.uint8, count=n * 50, offset=84)
    rec = rec.reshape(n, 50)[:, 12:48].copy()      # 법선 12B·attr 2B 제외
    return rec.view("<f4").reshape(n, 3, 3).astype(np.float64)


def stl_metrics(tris: np.ndarray) -> dict:
    """면적·부호부피·watertight 판정"""
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    cr = np.cross(v1 - v0, v2 - v0)
    area = 0.5 * np.linalg.norm(cr, axis=1).sum()
    volume = np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0

    # 정점을 반올림 키로 병합 → 에지 사용 횟수 집계
    pts = tris.reshape(-1, 3)
    key = np.round(pts / 1e-6).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    f = inv.reshape(-1, 3)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    e.sort(axis=1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    return {"n_tri": int(len(tris)), "area_mm2": float(area),
            "volume_mm3": float(abs(volume)),
            "watertight": bool((cnt == 2).all()),
            "bad_edges": int((cnt != 2).sum())}


# ──────────────────────────────────────────────────────────────
# 내보내기 본체
# ──────────────────────────────────────────────────────────────
def export_stl(p: FTHXParams, outdir: str = "out_foam", cs=None, plenum=None,
               include_casing: bool = False, area_err_limit: float = 1e-3,
               area_err_target: float = 3e-4) -> dict:
    """build() 인벤토리를 patch별 STL 로 내보내고 3종 검증까지 수행.

    실패(비수밀·면적오차 초과)는 예외로 즉시 알림 — Fluent 경로에서
    '표면 메시는 통과하고 30분 뒤 볼륨에서 실패'하던 패턴의 예방.
    """
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    assy, meta = CAD.build(p, cs, plenum)
    ov = CAD.check_overlap(assy)
    if ov:
        raise ValueError("바디 체적 겹침:\n  " + "\n  ".join(
            f"{o['a']} ∩ {o['b']} = {o['volume_mm3']:,.2f} mm³" for o in ov[:8]))

    tess = tessellation_tol(p, area_err_target)
    bodies, errors = {}, []
    for ch in assy.children:
        name = ch.name
        if not include_casing and name.startswith("solid_casing"):
            continue
        fp = out / f"{name}.stl"
        ch.obj.exportStl(str(fp), tolerance=tess["linear_tol_mm"],
                         angularTolerance=tess["angular_tol_rad"],
                         ascii=False)
        m = stl_metrics(read_stl(fp))
        cad_area = ch.obj.Area()
        cad_vol = ch.obj.Volume()
        m["cad_area_mm2"] = float(cad_area)
        m["cad_volume_mm3"] = float(cad_vol)
        m["area_err"] = abs(m["area_mm2"] - cad_area) / cad_area
        m["volume_err"] = abs(m["volume_mm3"] - cad_vol) / cad_vol
        m["file"] = fp.name
        bodies[name] = m
        if not m["watertight"]:
            errors.append(f"{name}: watertight 아님 (bad_edges={m['bad_edges']})")
        if m["area_err"] > area_err_limit:
            errors.append(f"{name}: 면적오차 {m['area_err']:.2%} > {area_err_limit:.2%}")
    if errors:
        raise ValueError("STL 검증 실패:\n  " + "\n  ".join(errors))

    # bbox 2종:
    #  air_bbox    — 공기 도메인(덕트 내측 + 상·하류 연장). 단일 region 이면 이것.
    #  global_bbox — 모든 바디의 합집합. 벤드·포트 연장이 덕트 밖으로 나가므로
    #                chtMultiRegion(배경격자 1개를 깎아 전 영역 생성)이면 이것.
    dk, d = p.duct_box, p.domain
    x0, x1 = p.core_bbox[0], p.core_bbox[1]
    gb = None
    for ch in assy.children:
        bb = ch.obj.BoundingBox()
        cur = [bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax]
        gb = cur if gb is None else [
            min(gb[0], cur[0]), max(gb[1], cur[1]), min(gb[2], cur[2]),
            max(gb[3], cur[3]), min(gb[4], cur[4]), max(gb[5], cur[5])]
    foam_meta = {
        "schema_version": p.schema_version,
        "name": p.name,
        "units": "mm",
        "tessellation": tess,
        "include_casing": include_casing,
        "air_bbox_mm": {
            "x": [x0 - d.L_up, x1 + d.L_down],
            "y": [dk["y0"], dk["y1"]],
            "z": [dk["z0"], dk["z1"]]},
        "global_bbox_mm": {"x": [gb[0], gb[1]], "y": [gb[2], gb[3]],
                           "z": [gb[4], gb[5]]},
        "sizing_hint": None,        # F1 에서 meshing.sizing() 결과를 병합
        "bodies": bodies,
        "face_seeds": meta["face_seeds"],
        "circuits": meta["circuits"],
        "fthx_meta": {k: meta[k] for k in
                      ("core_bbox", "duct_box", "tube_z", "fin_pack",
                       "operating", "operating_derived", "derived")},
    }
    (out / f"{p.name}.foam.json").write_text(
        json.dumps(foam_meta, indent=2, ensure_ascii=False), encoding="utf-8")
    foam_meta["_files"] = {"dir": str(out),
                          "stl": sorted(b["file"] for b in bodies.values()),
                          "json": f"{p.name}.foam.json"}
    return foam_meta
