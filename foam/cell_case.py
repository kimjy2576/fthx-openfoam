"""
D 모드 — 주기 단위셀 (핀 실형상) → j/f 추출

핵심 설계:
  · 공기 도메인만 푼다. core 의 `extract_jf` 가 등온 벽 전제이므로
    핀·관 표면을 T_wall 등온으로 두고 h 를 뽑으면 정의가 정확히 맞음.
    (핀 효율은 closure.fin_efficiency 가 별도로 적용 — 중복 없음)
  · 배경격자를 공기 bbox 에 정확히 맞추면 다섯 면이 그대로 patch 가 된다:
        z = t_f/2   핀 상면        → wall (등온)
        z = Fp/2    핀 사이 중앙   → symmetryPlane
        y = 0, Pt/2 관 중심·중앙   → symmetryPlane
        x = 0, Lx   입·출구        → patch
    따라서 STL 은 관(칼라 포함)만 필요하고, snappy 는 관만 깎으면 된다.
  · z 가 0.85mm 로 얇아 배경격자를 비등방으로 만든다 (Fluent 의 z 스윕에
    해당). blockMesh 는 방향별 분할이 자유로우므로 자연스럽게 대응됨.
  · Re_Dh ~ 500 층류 → 난류 모델을 켜지 않는다 (cell_flow 의 경고).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fthx import cell as CELL
from fthx.params import FTHXParams

from .foam_stl import read_stl, stl_metrics
from .openfoam import _hdr


def _export_cell_stl(p: FTHXParams, outdir: Path, tol: float) -> list[str]:
    """단위셀 관 바디만 STL 로 (m 단위). 핀·경계는 blockMesh 가 담당."""
    assy, meta = CELL.build(p)
    outdir.mkdir(parents=True, exist_ok=True)
    names = []
    for ch in assy.children:
        if not ch.name.startswith("solid_tube"):
            continue
        tmp = outdir / f"_{ch.name}.stl"
        ch.obj.exportStl(str(tmp), tolerance=tol, angularTolerance=0.1,
                         ascii=False)
        m = stl_metrics(read_stl(tmp))
        if not m["watertight"]:
            raise ValueError(f"{ch.name}: watertight 아님")
        # mm → m
        import struct
        b = bytearray(tmp.read_bytes())
        n = int.from_bytes(b[80:84], "little")
        for i in range(n):
            off = 84 + i * 50
            v = struct.unpack_from("<12f", b, off)
            struct.pack_into("<12f", b, off, *(x * 0.001 for x in v))
        (outdir / f"{ch.name}.stl").write_bytes(bytes(b))
        tmp.unlink()
        names.append(ch.name)
    return names, meta


def write_cell_case(p: FTHXParams, case_dir: str, force: bool = False,
                    h_xy: float = 0.25, nz_gap: int = 10) -> dict:
    """단위셀 케이스 생성. 반환: 사이징 + 유동 조건 + 게이트값."""
    g = CELL.cell_geometry(p)
    sz = CELL.cell_sizing(p, h_xy=h_xy, nz_gap=nz_gap)
    fl = CELL.cell_flow(p)
    case = Path(case_dir)
    if case.exists() and force:
        shutil.rmtree(case)
    for sub in ("system", "constant/triSurface", "0"):
        (case / sub).mkdir(parents=True, exist_ok=True)

    tol = min(p.fin.t_f, sz["hz_gap_mm"]) / 8.0
    stl_names, meta = _export_cell_stl(p, case / "constant" / "triSurface", tol)

    Lx, Ly, Lz = g["Lx"], g["Ly"], g["Lz"]
    z0 = g["t_f_half"]                       # 핀 상면
    nx = max(2, round(Lx / h_xy))
    ny = max(2, round(Ly / h_xy))
    nz = max(2, nz_gap)

    def w(rel, body, obj=None, loc=None):
        f = case / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_hdr(obj or f.name, loc or str(Path(rel).parent)) + body,
                     encoding="utf-8", newline="\n")

    v = [(0, 0, z0), (Lx, 0, z0), (Lx, Ly, z0), (0, Ly, z0),
         (0, 0, Lz), (Lx, 0, Lz), (Lx, Ly, Lz), (0, Ly, Lz)]
    w("system/blockMeshDict", f"""
convertToMeters 0.001;

vertices
(
{chr(10).join(f'    ({a} {b} {c})' for a, b, c in v)}
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

boundary
(
    cell_inlet  {{ type patch;          faces ((0 4 7 3)); }}
    cell_outlet {{ type patch;          faces ((1 2 6 5)); }}
    fin_wall    {{ type wall;           faces ((0 3 2 1)); }}   // z = t_f/2
    sym_z       {{ type symmetryPlane;  faces ((4 5 6 7)); }}   // z = Fp/2
    sym_y0      {{ type symmetryPlane;  faces ((0 1 5 4)); }}
    sym_y1      {{ type symmetryPlane;  faces ((3 7 6 2)); }}
);
""")

    geom = "".join(f'    {n}.stl {{ type triSurfaceMesh; name {n}; }}\n'
                   for n in stl_names)
    feat = "".join(f'    {{ file "{n}.eMesh"; level 1; }}\n' for n in stl_names)
    surf = "".join(f"        {n}\n        {{\n            level (1 2);\n"
                   f"            patchInfo {{ type wall; }}\n        }}\n"
                   for n in stl_names)
    # 내부점: 입구 근처, 관에서 먼 곳 (상류에는 관이 없음)
    loc = ((g["x_core"][0] * 0.5) / 1000.0, (Ly * 0.5) / 1000.0,
           ((z0 + Lz) * 0.5) / 1000.0)
    w("system/snappyHexMeshDict", f"""
castellatedMesh true;
snap            true;
addLayers       false;

geometry
{{
{geom}}}

castellatedMeshControls
{{
    maxLocalCells       4000000;
    maxGlobalCells      12000000;
    minRefinementCells  0;
    nCellsBetweenLevels 2;
    resolveFeatureAngle 45;
    features ( 
{feat}    );
    refinementSurfaces
    {{
{surf}    }}
    refinementRegions {{ }}
    locationInMesh ({loc[0]} {loc[1]} {loc[2]});
    allowFreeStandingZoneFaces false;
}}

snapControls
{{
    nSmoothPatch 3; tolerance 2.0; nSolveIter 50; nRelaxIter 5;
    nFeatureSnapIter 10; implicitFeatureSnap false;
    explicitFeatureSnap true; multiRegionFeatureSnap false;
}}

addLayersControls
{{
    relativeSizes true; layers {{ }} expansionRatio 1.2;
    finalLayerThickness 0.5; minThickness 0.25; nGrow 0;
    featureAngle 60; nRelaxIter 5; nSmoothSurfaceNormals 1;
    nSmoothNormals 3; nSmoothThickness 10; maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3; minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0; nLayerIter 50;
}}

meshQualityControls
{{
    #includeEtc "caseDicts/meshQualityDict"
    minTetQuality 1e-15; nSmoothScale 4; errorReduction 0.75;
    maxAspectRatio 200;          // 비등방 배경격자 — z 가 얇음
}}
writeFlags ();
mergeTolerance 1e-6;
""")
    w("system/surfaceFeatureExtractDict", "".join(
        f'\n{n}.stl\n{{\n    extractionMethod extractFromSurface;\n'
        f'    includedAngle 150;\n    writeObj no;\n}}\n' for n in stl_names))

    # ── 물리: 층류·등온벽. 온도는 수동 스칼라가 아니라 에너지식으로
    U, Tin, Tw = fl["u_max_ms"], fl["T_in_K"], fl["T_wall_K"]
    xc0, xc1 = g["x_core"]
    nu = fl["mu"] / fl["rho"]
    walls = '"(fin_wall|solid_tube.*)"'
    w("0/U", f"""
dimensions [0 1 -1 0 0 0 0];
internalField uniform ({U} 0 0);
boundaryField
{{
    cell_inlet  {{ type fixedValue; value uniform ({U} 0 0); }}
    cell_outlet {{ type zeroGradient; }}
    {walls}     {{ type noSlip; }}
    "sym_.*"    {{ type symmetryPlane; }}
}}
""")
    w("0/p", """
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{
    cell_inlet  { type zeroGradient; }
    cell_outlet { type fixedValue; value uniform 0; }
    "(fin_wall|solid_tube.*)" { type zeroGradient; }
    "sym_.*"    { type symmetryPlane; }
}
""")
    w("0/T", f"""
dimensions [0 0 0 1 0 0 0];
internalField uniform {Tin};
boundaryField
{{
    cell_inlet  {{ type fixedValue; value uniform {Tin}; }}
    cell_outlet {{ type zeroGradient; }}
    {walls}     {{ type fixedValue; value uniform {Tw}; }}   // 등온 — extract_jf 전제
    "sym_.*"    {{ type symmetryPlane; }}
}}
""")
    Pr = fl["cp"] * fl["mu"] / 0.0263
    w("constant/transportProperties", f"""
transportModel  Newtonian;
nu              {nu:.6e};
// 스칼라 T 수송용 (scalarTransport functionObject)
DT              {nu / Pr:.6e};
""")
    w("constant/turbulenceProperties",
      f"\nsimulationType laminar;   // Re_Dh = {fl['Re_Dh']:.0f} < 2300\n")
    w("system/fvSchemes", """
ddtSchemes      { default steadyState; }
gradSchemes     { default Gauss linear; }
divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div(phi,T)      bounded Gauss linearUpwind grad(T);
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes   { default corrected; }
""", obj="fvSchemes")
    w("system/fvSolution", """
solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-8; relTol 0.01; }
    "(U|T)" { solver smoothSolver; smoother symGaussSeidel;
              tolerance 1e-9; relTol 0.1; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 1;
    consistent yes;
    residualControl { p 1e-5; U 1e-6; T 1e-6; }
}
relaxationFactors { equations { U 0.9; T 0.9; } }
""", obj="fvSolution")
    w("system/controlDict", f"""
application     simpleFoam;
startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         3000;
deltaT          1;
writeControl    timeStep;
writeInterval   1000;
purgeWrite      2;
functions
{{
    scalarTransport
    {{
        type            scalarTransport;
        libs            (solverFunctionObjects);
        field           T;
        schemesField    T;
        writeControl    writeTime;
    }}
    // 코어 전후 단면 — 상관식 f 는 코어만 기준이므로 여기서 dp 를 읽어야 함
    // (입출구 dp 는 상하류 연장 마찰까지 포함 → f 가 과대)
    pCore0
    {{
        type surfaceFieldValue; libs (fieldFunctionObjects);
        regionType sampledSurface;
        name coreIn;
        sampledSurfaceDict {{ type plane; planeType pointAndNormal;
                 pointAndNormalDict {{ point ({xc0/1000:.6f} 0 0);
                                      normal (1 0 0); }}
                             interpolate true; }}
        operation areaAverage; fields (p);
        writeFields no; writeControl timeStep; writeInterval 50; log no;
    }}
    pCore1
    {{
        type surfaceFieldValue; libs (fieldFunctionObjects);
        regionType sampledSurface;
        name coreOut;
        sampledSurfaceDict {{ type plane; planeType pointAndNormal;
                 pointAndNormalDict {{ point ({xc1/1000:.6f} 0 0);
                                      normal (1 0 0); }}
                             interpolate true; }}
        operation areaAverage; fields (p);
        writeFields no; writeControl timeStep; writeInterval 50; log no;
    }}
    pIn  {{ type surfaceFieldValue; libs (fieldFunctionObjects);
           regionType patch; name cell_inlet; operation areaAverage;
           fields (p); writeFields no; writeControl timeStep;
           writeInterval 50; log no; }}
    pOut {{ type surfaceFieldValue; libs (fieldFunctionObjects);
           regionType patch; name cell_outlet; operation areaAverage;
           fields (p); writeFields no; writeControl timeStep;
           writeInterval 50; log no; }}
    Tout {{ type surfaceFieldValue; libs (fieldFunctionObjects);
           regionType patch; name cell_outlet; operation weightedAreaAverage;
           weightField phi; fields (T); writeFields no;
           writeControl timeStep; writeInterval 50; log no; }}
}}
""", obj="controlDict")
    w("system/decomposeParDict", "\nnumberOfSubdomains 8;\nmethod scotch;\n")

    allrun = """#!/usr/bin/env bash
cd "$(dirname "$0")"
if ! command -v blockMesh >/dev/null 2>&1; then
    for rc in /usr/lib/openfoam/openfoam*/etc/bashrc; do
        [ -f "$rc" ] && source "$rc" && break
    done
fi
set -e
run() { echo ">>> $1"; "$@" > "log.$1" 2>&1 || { echo "<<< $1 실패 — log.$1"; exit 1; }; echo "<<< $1 OK"; }
run surfaceFeatureExtract
run blockMesh
run snappyHexMesh -overwrite
run checkMesh -constant
echo "──────── 메시 요약 ────────"
grep -E "^Snapped mesh|  cells:" log.snappyHexMesh log.checkMesh | tail -2
grep -E "Max aspect ratio|Mesh OK|Failed .* mesh checks" log.checkMesh
"""
    ar = case / "Allrun.mesh"
    ar.write_text(allrun, encoding="utf-8", newline="\n")
    ar.chmod(0o755)

    return {"geometry": g, "sizing": sz, "flow": fl, "case_dir": str(case),
            "stl": stl_names, "blocks": [nx, ny, nz],
            "z_range_mm": [z0, Lz], "tol_mm": tol,
            "gate": {"cells_est": sz["cells_est"],
                     "aspect_ratio": sz["aspect_ratio"]}}
