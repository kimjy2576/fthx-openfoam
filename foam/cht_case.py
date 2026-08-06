"""
cht 모드 — 공기 · 관벽 · 냉매 3영역 conjugate (Fluent 대등)

B 모드(`mode="air"`)는 냉매를 경계조건으로 축약하지만, 이 모듈은 Fluent 저널과
같이 **냉매를 실제로 푼다**. 냉매는 우선 단상(물).

    region          내용                     솔버 취급
    ────────────────────────────────────────────────────
    air             상류+코어+하류 공기       유체 (포러스 fvOptions)
    tube            관벽 (구리)               고체
    ref             관내 냉매 (물)            유체 (mass-flow-inlet)

메시 흐름 (실측으로 확인한 순서):
    blockMesh → snappyHexMesh(코어 zone 없이!) → splitMeshRegions -cellZones
      → 공기가 한 덩어리로 남음 (코어를 zone 으로 잡으면 상·하류가 쪼개짐)
    → topoSet 으로 공기 region 안에 porousCore cellZone 재생성
      → fvOptions 를 여기 건다

주의: 셀이 B 모드의 4배(≈160k)이고 3영역 연성이라 수렴이 느림.
스윕은 B 모드로, 검증·시각화는 이 모드로 쓰는 병행 구도를 권장.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fthx.params import FTHXParams

from ._thermal_closure import thermal_closure
from .openfoam import _hdr, plan, porous_df
from .foam_stl import export_stl

AIR, TUBE, REF = "air", "tube", "ref"

# 물 물성 (단상, 10 °C 근처)
WATER = {"rho": 999.7, "cp": 4193.0, "mu": 1.307e-3, "Pr": 9.45,
         "molWeight": 18.0}
COPPER = {"rho": 8960.0, "cp": 385.0, "kappa": 386.0}


def _w(case: Path, rel: str, body: str, obj: str | None = None):
    f = case / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_hdr(obj or f.name, str(Path(rel).parent)) + body,
                 encoding="utf-8", newline="\n")


def _coupled_T(nbr_kappa: str, T0: float) -> str:
    """region 계면 온도 연성 BC (v2412 정식 이름)."""
    return (f"""    {{
        type        compressible::turbulentTemperatureRadCoupledMixed;
        Tnbr        T;
        kappaMethod {nbr_kappa};
        kappa       none;
        value       uniform {T0:.4f};
    }}""")


def write_cht_case(p: FTHXParams, case_dir: str, force: bool = False,
                   jf: dict | None = None, iterations: int = 3000) -> dict:
    """3영역 conjugate 케이스. Allrun 이 메시 분리까지 수행."""
    d = p.domain
    if d.include_bends:
        raise NotImplementedError("벤드 포함 형상의 cht 는 미지원 (Phase 5)")

    case = Path(case_dir)
    if case.exists() and force:
        shutil.rmtree(case)
    (case / "system").mkdir(parents=True, exist_ok=True)
    (case / "constant" / "triSurface").mkdir(parents=True, exist_ok=True)

    # ── STL: 관벽·냉매만. 공기 코어는 zone 으로 잡지 않는다 (region 분리 이유)
    meta = export_stl(p, outdir=str(case / "_stl"))
    names = []
    for b in meta["bodies"].values():
        n = b["file"][:-4]
        if not (n.startswith("solid_tube") or n.startswith("fluid_ref")):
            continue
        from .openfoam import _scale_stl
        _scale_stl(case / "_stl" / b["file"],
                   case / "constant" / "triSurface" / b["file"])
        names.append(n)
    shutil.rmtree(case / "_stl")
    tube_n = [n for n in names if n.startswith("solid_tube")]
    ref_n = [n for n in names if n.startswith("fluid_ref")]

    pl = plan(p)
    pf = porous_df(p, jf)
    th = thermal_closure(p, jf=jf)
    T_in = p.operating.air.T_in + 273.15
    T_ref = p.operating.ref.T_sat_in + 273.15
    Pop = p.operating.air.P_in
    U = p.operating.air.V_face
    m_ref = p.operating.ref.m_total / max(len(ref_n), 1)

    # ── 배경격자 (B 모드와 동일)
    from .openfoam import _block_mesh_dict, _feature_dict
    _w(case, "system/blockMeshDict", _block_mesh_dict(p, pl).split("\n", 8)[-1],
       obj="blockMeshDict")
    (case / "system" / "blockMeshDict").write_text(
        _block_mesh_dict(p, pl), encoding="utf-8", newline="\n")
    _w(case, "system/surfaceFeatureExtractDict",
       _feature_dict(sorted(names)).split("\n", 8)[-1],
       obj="surfaceFeatureExtractDict")
    (case / "system" / "surfaceFeatureExtractDict").write_text(
        _feature_dict(sorted(names)), encoding="utf-8", newline="\n")

    geom = "".join(f'    {n}.stl {{ type triSurfaceMesh; name {n}; }}\n'
                   for n in names)
    feat = "".join(f'    {{ file "{n}.eMesh"; level {pl["lv_ref"]}; }}\n'
                   for n in names)
    surf = ""
    for n in names:
        lv = pl["lv_wall"] if n.startswith("solid_tube") else pl["lv_ref"]
        surf += (f"        {n}\n        {{\n            level ({lv} {lv});\n"
                 f"            faceZone {n};\n            cellZone {n};\n"
                 f"            cellZoneInside inside;\n        }}\n")
    dk = p.duct_box
    x0 = p.core_bbox[0]
    loc = tuple(v / 1000.0 for v in (
        (x0 - d.L_up + x0) / 2 + 0.0123,
        (dk["y0"] + dk["y1"]) / 2 + 0.0231,
        (dk["z0"] + dk["z1"]) / 2 + 0.0312))
    _w(case, "system/snappyHexMeshDict", f"""
castellatedMesh true;
snap            true;
addLayers       false;

geometry
{{
{geom}}}

castellatedMeshControls
{{
    maxLocalCells 4000000; maxGlobalCells 12000000;
    minRefinementCells 0; nCellsBetweenLevels 3; resolveFeatureAngle 30;
    features ( 
{feat}    );
    refinementSurfaces
    {{
{surf}    }}
    refinementRegions {{ }}
    locationInMesh ({loc[0]} {loc[1]} {loc[2]});
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch 3; tolerance 2.0; nSolveIter 50; nRelaxIter 5;
    nFeatureSnapIter 10; implicitFeatureSnap false;
    explicitFeatureSnap true; multiRegionFeatureSnap true;
}}
addLayersControls
{{
    relativeSizes true; layers {{ }} expansionRatio 1.2;
    finalLayerThickness 0.5; minThickness 0.25; nGrow 0; featureAngle 60;
    nRelaxIter 5; nSmoothSurfaceNormals 1; nSmoothNormals 3;
    nSmoothThickness 10; maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3; minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0; nLayerIter 50;
}}
meshQualityControls
{{
    #includeEtc "caseDicts/meshQualityDict"
    minTetQuality 1e-15; nSmoothScale 4; errorReduction 0.75;
}}
writeFlags (); mergeTolerance 1e-6;
""")

    # ── 공기 region 안의 포러스 존 (분리 후 topoSet)
    cb = p.core_bbox
    _w(case, f"system/{AIR}/topoSetDict", f"""
actions
(
    {{ name porousCore; type cellSet; action new;
      source boxToCell;
      box ({cb[0] / 1000:.6f} {cb[2] / 1000:.6f} {cb[4] / 1000:.6f})
          ({cb[1] / 1000:.6f} {cb[3] / 1000:.6f} {cb[5] / 1000:.6f}); }}
    {{ name porousCore; type cellZoneSet; action new;
      source setToCellZone; set porousCore; }}
);
""", obj="topoSetDict")

    _w(case, "constant/regionProperties", f"""
regions
(
    fluid ({AIR} {REF})
    solid ({TUBE})
);
""", obj="regionProperties")

    _write_air(case, p, pf, th, U, T_in, Pop, tube_n)
    _write_tube(case, T_in, Pop)
    _write_ref(case, m_ref, T_ref, Pop)
    _write_system(case, iterations)
    _write_allrun(case, tube_n, ref_n)

    return {"case_dir": str(case), "regions": [AIR, TUBE, REF],
            "stl": names, "m_ref_kgs": m_ref, "jf_source": pf["jf_source"],
            "note": "Allrun.mesh 가 splitMeshRegions·topoSet 까지 수행"}


def _write_air(case, p, pf, th, U, T_in, Pop, tube_n):
    core = "porousCore"
    walls = '"(duct_wall)"'
    cpl = '"(air_to_tube|.*_to_.*)"'
    k_in = 1.5 * (0.05 * U) ** 2
    eps_in = 0.09 ** 0.75 * k_in ** 1.5 / (0.1 * (p.duct_box["y1"] - p.duct_box["y0"]) / 1000)
    _w(case, f"0/{AIR}/U", f"""
dimensions [0 1 -1 0 0 0 0];
internalField uniform ({U} 0 0);
boundaryField
{{
    air_inlet  {{ type fixedValue; value uniform ({U} 0 0); }}
    air_outlet {{ type zeroGradient; }}
    {walls}    {{ type noSlip; }}
    {cpl}      {{ type noSlip; }}
}}
""", obj="U")
    _w(case, f"0/{AIR}/p_rgh", f"""
dimensions [1 -1 -2 0 0 0 0];
internalField uniform {Pop};
boundaryField
{{
    air_inlet  {{ type fixedFluxPressure; value uniform {Pop}; }}
    air_outlet {{ type fixedValue; value uniform {Pop}; }}
    {walls}    {{ type fixedFluxPressure; value uniform {Pop}; }}
    {cpl}      {{ type fixedFluxPressure; value uniform {Pop}; }}
}}
""", obj="p_rgh")
    _w(case, f"0/{AIR}/p", f"""
dimensions [1 -1 -2 0 0 0 0];
internalField uniform {Pop};
boundaryField {{ ".*" {{ type calculated; value uniform {Pop}; }} }}
""", obj="p")
    _w(case, f"0/{AIR}/T", f"""
dimensions [0 0 0 1 0 0 0];
internalField uniform {T_in:.4f};
boundaryField
{{
    air_inlet  {{ type fixedValue; value uniform {T_in:.4f}; }}
    air_outlet {{ type inletOutlet; inletValue uniform {T_in:.4f};
                  value uniform {T_in:.4f}; }}
    {walls}    {{ type zeroGradient; }}
    {cpl}
{_coupled_T('fluidThermo', T_in)}
}}
""", obj="T")
    for fld, dim, val, wf in (("k", "[0 2 -2 0 0 0 0]", k_in, "kqRWallFunction"),
                              ("epsilon", "[0 2 -3 0 0 0 0]", eps_in, "epsilonWallFunction"),
                              ("nut", "[0 2 -1 0 0 0 0]", 0.0, "nutkWallFunction"),
                              ("alphat", "[1 -1 -1 0 0 0 0]", 0.0,
                               "compressible::alphatWallFunction")):
        _w(case, f"0/{AIR}/{fld}", f"""
dimensions {dim};
internalField uniform {val:.6g};
boundaryField
{{
    air_inlet  {{ type {'fixedValue' if fld in ('k', 'epsilon') else 'calculated'};
                  value uniform {val:.6g}; }}
    air_outlet {{ type {'zeroGradient' if fld in ('k', 'epsilon') else 'calculated'};
                  value uniform {val:.6g}; }}
    ".*(wall|_to_).*" {{ type {wf}; {'Prt 0.85; ' if fld == 'alphat' else ''}value uniform {val:.6g}; }}
}}
""", obj=fld)
    od = p.operating_derived()["air"]
    _w(case, f"constant/{AIR}/thermophysicalProperties", f"""
thermoType
{{
    type heRhoThermo; mixture pureMixture; transport const;
    thermo hConst; equationOfState incompressiblePerfectGas;
    specie specie; energy sensibleEnthalpy;
}}
pRef {p.operating.air.P_in};
mixture
{{
    specie          {{ molWeight 28.96; }}
    thermodynamics  {{ Cp {od['cp']:.2f}; Hf 0; }}
    transport       {{ mu {od['mu']:.6e}; Pr {th['Pr']:.4f}; }}
    equationOfState {{ pRef {p.operating.air.P_in}; }}
}}
""", obj="thermophysicalProperties")
    _w(case, f"constant/{AIR}/momentumTransport",
       "\nsimulationType RAS;\nRAS { model kEpsilon; turbulence on; printCoeffs off; }\n",
       obj="momentumTransport")
    _w(case, f"constant/{AIR}/turbulenceProperties",
       "\nsimulationType RAS;\nRAS { RASModel kEpsilon; turbulence on; printCoeffs off; }\n",
       obj="turbulenceProperties")
    _w(case, f"constant/{AIR}/g",
       "\ndimensions [0 1 -2 0 0 0 0];\nvalue (0 0 0);\n", obj="g")
    _w(case, f"system/{AIR}/fvOptions", f"""
porousCore
{{
    type explicitPorositySource; active yes;
    explicitPorositySourceCoeffs
    {{
        selectionMode cellZone; cellZone {core};
        type DarcyForchheimer;
        d (0 0 0);
        f ({pf['f']:.6f} {pf['f']:.6f} {pf['f'] * pf['block_factor']:.6f});
        coordinateSystem
        {{ origin (0 0 0);
           rotation {{ type axesRotation; e1 (1 0 0); e2 (0 1 0); }} }}
    }}
}}
""", obj="fvOptions")


def _write_tube(case, T0, Pop=101325.0):
    cpl = '".*_to_.*"'
    _w(case, f"0/{TUBE}/T", f"""
dimensions [0 0 0 1 0 0 0];
internalField uniform {T0:.4f};
boundaryField
{{
    ".*" {{ type zeroGradient; }}
    {cpl}
{_coupled_T('solidThermo', T0)}
}}
""", obj="T")
    _w(case, f"constant/{TUBE}/thermophysicalProperties", f"""
thermoType
{{
    type heSolidThermo; mixture pureMixture; transport constIso;
    thermo hConst; equationOfState rhoConst; specie specie;
    energy sensibleEnthalpy;
}}
mixture
{{
    specie          {{ molWeight 63.55; }}
    transport       {{ kappa {COPPER['kappa']}; }}
    thermodynamics  {{ Cp {COPPER['cp']}; Hf 0; }}
    equationOfState {{ rho {COPPER['rho']}; }}
}}
""", obj="thermophysicalProperties")
    # 고체 region 도 p 를 요구함 (thermo 가 참조)
    _w(case, f"0/{TUBE}/p", f"""
dimensions [1 -1 -2 0 0 0 0];
internalField uniform {Pop};
boundaryField {{ ".*" {{ type calculated; value uniform {Pop}; }} }}
""", obj="p")


def _write_ref(case, m_ref, T_ref, Pop):
    cpl = '".*_to_.*"'
    _w(case, f"0/{REF}/U", f"""
dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0.5);
boundaryField
{{
    ".*"         {{ type noSlip; }}
    {cpl}        {{ type noSlip; }}
    ".*inlet.*"  {{ type flowRateInletVelocity;
                    massFlowRate constant {m_ref:.6g}; value uniform (0 0 0.5); }}
    ".*outlet.*" {{ type zeroGradient; }}
}}
""", obj="U")
    _w(case, f"0/{REF}/p_rgh", f"""
dimensions [1 -1 -2 0 0 0 0];
internalField uniform {Pop};
boundaryField
{{
    ".*outlet.*" {{ type fixedValue; value uniform {Pop}; }}
    ".*"         {{ type fixedFluxPressure; value uniform {Pop}; }}
}}
""", obj="p_rgh")
    _w(case, f"0/{REF}/p", f"""
dimensions [1 -1 -2 0 0 0 0];
internalField uniform {Pop};
boundaryField {{ ".*" {{ type calculated; value uniform {Pop}; }} }}
""", obj="p")
    _w(case, f"0/{REF}/T", f"""
dimensions [0 0 0 1 0 0 0];
internalField uniform {T_ref:.4f};
boundaryField
{{
    ".*"         {{ type zeroGradient; }}
    ".*inlet.*"  {{ type fixedValue; value uniform {T_ref:.4f}; }}
    ".*outlet.*" {{ type zeroGradient; }}
    {cpl}
{_coupled_T('fluidThermo', T_ref)}
}}
""", obj="T")
    _w(case, f"constant/{REF}/thermophysicalProperties", f"""
// 냉매 = 단상 물 (2상 확장 시 여기를 교체)
thermoType
{{
    type heRhoThermo; mixture pureMixture; transport const;
    thermo hConst; equationOfState rhoConst; specie specie;
    energy sensibleEnthalpy;
}}
mixture
{{
    specie          {{ molWeight {WATER['molWeight']}; }}
    thermodynamics  {{ Cp {WATER['cp']}; Hf 0; }}
    transport       {{ mu {WATER['mu']:.6e}; Pr {WATER['Pr']}; }}
    equationOfState {{ rho {WATER['rho']}; }}
}}
""", obj="thermophysicalProperties")
    _w(case, f"constant/{REF}/momentumTransport",
       "\nsimulationType laminar;\n", obj="momentumTransport")
    _w(case, f"constant/{REF}/turbulenceProperties",
       "\nsimulationType laminar;\n", obj="turbulenceProperties")
    _w(case, f"constant/{REF}/g",
       "\ndimensions [0 1 -2 0 0 0 0];\nvalue (0 0 0);\n", obj="g")


def _write_system(case, iterations):
    _w(case, "system/controlDict", f"""
application     chtMultiRegionSimpleFoam;
startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         {iterations};
deltaT          1;
writeControl    timeStep;
writeInterval   {max(iterations // 3, 100)};
purgeWrite      2;
runTimeModifiable true;
""", obj="controlDict")
    for r in (AIR, TUBE, REF):
        solid = r == TUBE
        _w(case, f"system/{r}/fvSchemes", """
ddtSchemes      { default steadyState; }
gradSchemes     { default Gauss linear; }
divSchemes
{
    default none;
""" + ("" if solid else """    div(phi,U)   bounded Gauss linearUpwind grad(U);
    div(phi,h)   bounded Gauss upwind;
    div(phi,K)   bounded Gauss upwind;
    div(phi,k)   bounded Gauss upwind;
    div(phi,epsilon) bounded Gauss upwind;
    div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;
""") + """}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes   { default corrected; }
""", obj="fvSchemes")
        _w(case, f"system/{r}/fvSolution", ("""
solvers
{
    h { solver PCG; preconditioner DIC; tolerance 1e-8; relTol 0.1; }
}
SIMPLE { nNonOrthogonalCorrectors 1; }
relaxationFactors { equations { h 0.7; } }
""" if solid else """
solvers
{
    p_rgh { solver GAMG; smoother GaussSeidel; tolerance 1e-8; relTol 0.01; }
    "(U|h|k|epsilon)" { solver PBiCGStab; preconditioner DILU;
                        tolerance 1e-8; relTol 0.1; }
}
SIMPLE { momentumPredictor yes; nNonOrthogonalCorrectors 1;
         rhoMin 0.2; rhoMax 1200;
         // 밀폐 region(냉매)은 압력 기준점이 필요
         pRefCell 0; pRefValue 101325;
         pRefPoint (0 0 0); }
relaxationFactors { fields { rho 1.0; p_rgh 0.3; }
                    equations { U 0.7; h 0.7; "(k|epsilon)" 0.7; } }
"""), obj="fvSolution")
    # 메시 단계(blockMesh/snappy/splitMeshRegions)는 최상위 system/ 을 봄
    _w(case, "system/fvSchemes",
       "\nddtSchemes { default steadyState; }\ngradSchemes { default Gauss linear; }\n"
       "divSchemes { default none; }\nlaplacianSchemes { default Gauss linear corrected; }\n"
       "interpolationSchemes { default linear; }\nsnGradSchemes { default corrected; }\n",
       obj="fvSchemes")
    _w(case, "system/fvSolution", "\nsolvers {}\n", obj="fvSolution")
    _w(case, "constant/g",
       "\ndimensions [0 1 -2 0 0 0 0];\nvalue (0 0 0);\n", obj="g")
    _w(case, "system/decomposeParDict",
       "\nnumberOfSubdomains 8;\nmethod scotch;\n", obj="decomposeParDict")
    for r in (AIR, TUBE, REF):
        _w(case, f"system/{r}/decomposeParDict",
           "\nnumberOfSubdomains 8;\nmethod scotch;\n", obj="decomposeParDict")


def _write_allrun(case, tube_n, ref_n):
    tube0 = tube_n[0] if tube_n else "solid_tube"
    ref0 = ref_n[0] if ref_n else "fluid_ref"
    mesh = f"""#!/usr/bin/env bash
# 3영역 메시: 배경 → snappy → region 분리 → 포러스 존 재생성
cd "$(dirname "$0")"
if ! command -v blockMesh >/dev/null 2>&1; then
    for rc in /usr/lib/openfoam/openfoam*/etc/bashrc; do
        [ -f "$rc" ] && source "$rc" && break
    done
fi
set -e
run() {{ echo ">>> $1"; "$@" > "log.$1" 2>&1 || {{ echo "<<< $1 실패 — log.$1"; exit 1; }}; echo "<<< $1 OK"; }}

run surfaceFeatureExtract
run blockMesh
run snappyHexMesh -overwrite
run splitMeshRegions -cellZones -overwrite

# splitMeshRegions 가 만든 region 디렉터리를 우리 이름 아래로 옮긴다.
# (공기는 zone 이 없어 domain0 으로 나옴. 대상 디렉터리가 이미 있으므로
#  디렉터리째 mv 하면 그 안으로 들어가버림 → 내용물만 옮길 것)
# -n: splitMeshRegions 가 만든 기본 dict 가 우리 설정을 덮어쓰지 않게
movein() {{ [ -d "$1" ] || return 0; mkdir -p "$2"; mv -n "$1"/* "$2"/ 2>/dev/null; rm -rf "$1" 2>/dev/null; }}
movein constant/domain0     constant/{AIR}
movein system/domain0       system/{AIR}
movein 0/domain0            0/{AIR}
movein constant/{tube0}     constant/{TUBE}
movein system/{tube0}       system/{TUBE}
movein 0/{tube0}            0/{TUBE}
movein constant/{ref0}      constant/{REF}
movein system/{ref0}        system/{REF}
movein 0/{ref0}             0/{REF}

# splitMeshRegions 가 boundary 의 sampleRegion 에 원래 이름을 박아둠 —
# 디렉터리만 바꾸면 "failed lookup of ..." 로 죽는다. 함께 치환할 것.
for f in constant/*/polyMesh/boundary; do
    [ -f "$f" ] || continue
    sed -i "s/\\bdomain0\\b/{AIR}/g; s/\\b{tube0}\\b/{TUBE}/g; s/\\b{ref0}\\b/{REF}/g" "$f"
done

run topoSet -region {AIR}
echo "──────── region 요약 ────────"
for r in {AIR} {TUBE} {REF}; do
    n=$(grep -m1 -A2 "^nCells" constant/$r/polyMesh/owner 2>/dev/null | head -1)
    printf "  %-6s %s\\n" "$r" "$(checkMesh -region $r 2>/dev/null | grep -E '^ *cells:' | head -1)"
done
grep -E "porousCore now size" log.topoSet || true
echo "→ 다음: ./Allrun.solve"
"""
    (case / "Allrun.mesh").write_text(mesh, encoding="utf-8", newline="\n")
    (case / "Allrun.mesh").chmod(0o755)

    solve = f"""#!/usr/bin/env bash
cd "$(dirname "$0")"
if ! command -v chtMultiRegionSimpleFoam >/dev/null 2>&1; then
    for rc in /usr/lib/openfoam/openfoam*/etc/bashrc; do
        [ -f "$rc" ] && source "$rc" && break
    done
fi
set -e
NP=${{FTHX_NP:-8}}; A=$(nproc); [ "$NP" -gt "$A" ] && NP=$A
if [ "$NP" -gt 1 ] && command -v mpirun >/dev/null 2>&1; then
    for r in {AIR} {TUBE} {REF}; do
        sed -i "s/^numberOfSubdomains.*/numberOfSubdomains $NP;/" system/$r/decomposeParDict
    done
    rm -rf processor*
    decomposePar -allRegions -force > log.decomposePar 2>&1
    echo ">>> chtMultiRegionSimpleFoam (${{NP}}코어)"
    mpirun --oversubscribe --allow-run-as-root -np "$NP" \\
        chtMultiRegionSimpleFoam -parallel > log.solver 2>&1 \\
        || {{ echo "<<< 실패 — log.solver"; tail -40 log.solver; exit 1; }}
    reconstructPar -allRegions -latestTime > log.reconstructPar 2>&1
    rm -rf processor*
else
    echo ">>> chtMultiRegionSimpleFoam (직렬)"
    chtMultiRegionSimpleFoam > log.solver 2>&1 \\
        || {{ echo "<<< 실패 — log.solver"; tail -40 log.solver; exit 1; }}
fi
echo "<<< 솔버 OK"
grep -E "^Time = " log.solver | tail -1
echo "ParaView: touch case.foam 후 열면 region 선택 가능"
"""
    (case / "Allrun.solve").write_text(solve, encoding="utf-8", newline="\n")
    (case / "Allrun.solve").chmod(0o755)
