"""OpenFOAM 경로 회귀 테스트 (F0~F3). core 는 submodule 로 참조."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import foam  # noqa: E402  (core 를 sys.path 에 추가)

try:
    import cadquery  # noqa
    _CAD = True
except ImportError:
    _CAD = False
try:
    import CoolProp  # noqa
    _CP = True
except ImportError:
    _CP = False
needs_cad = pytest.mark.skipif(not _CAD, reason="cadquery 없음")
needs_cp = pytest.mark.skipif(not _CP, reason="CoolProp 없음")

# ══════════════════════════════════════════════════════════════
# F0 — OpenFOAM STL 내보내기
# ══════════════════════════════════════════════════════════════
@needs_cad
@needs_cp
class TestFoamStl:
    def _run(self, name, tmp_path):
        from fthx import presets
        from foam.foam_stl import export_stl
        return export_stl(presets.PRESETS[name](), outdir=str(tmp_path / name))

    def test_tutorial_watertight_and_area(self, tmp_path):
        m = self._run("tutorial", tmp_path)
        assert len(m["bodies"]) == 5                      # 케이싱 제외
        for name, b in m["bodies"].items():
            assert b["watertight"], name
            assert b["area_err"] < 1e-3, name

    def test_probe_watertight_and_area(self, tmp_path):
        m = self._run("probe", tmp_path)
        assert len(m["bodies"]) == 13
        for name, b in m["bodies"].items():
            assert b["watertight"], name
            assert b["area_err"] < 1e-3, name

    def test_inventory_matches_build(self, tmp_path):
        """파일 목록 ↔ build() 바디 인벤토리 1:1 (케이싱 제외)"""
        from fthx import presets, cad
        from foam.foam_stl import export_stl
        p = presets.PRESETS["probe"]()
        m = export_stl(p, outdir=str(tmp_path / "inv"))
        assy, _ = cad.build(p)
        expect = {c.name for c in assy.children
                  if not c.name.startswith("solid_casing")}
        assert set(m["bodies"]) == expect
        for n in expect:
            assert (tmp_path / "inv" / f"{n}.stl").exists()

    def test_global_bbox_covers_air_bbox(self, tmp_path):
        """배경격자 bbox: 전체 합집합이 공기 도메인을 포함해야 함
           (probe 는 벤드가 덕트 z 범위 밖으로 나감)"""
        m = self._run("probe", tmp_path)
        a, g = m["air_bbox_mm"], m["global_bbox_mm"]
        for ax in "xyz":
            assert g[ax][0] <= a[ax][0] and g[ax][1] >= a[ax][1]
        assert g["z"][0] < a["z"][0]      # 벤드가 실제로 밖에 있음
        assert g["z"][1] > a["z"][1]


# ══════════════════════════════════════════════════════════════
# F1+F2 — OpenFOAM 케이스 생성 (blockMesh + snappyHexMesh 딕셔너리)
# ══════════════════════════════════════════════════════════════
@needs_cad
@needs_cp
class TestFoamCase:
    def test_tutorial_case_files(self, tmp_path):
        from fthx import presets
        from foam.openfoam import write_case
        pl = write_case(presets.tutorial(), str(tmp_path / "c"), force=True,
                        mode="cht")
        c = tmp_path / "c"
        for f in ("system/blockMeshDict", "system/snappyHexMeshDict",
                  "system/surfaceFeatureExtractDict", "system/controlDict",
                  "system/fvSchemes", "system/fvSolution", "Allrun.mesh"):
            assert (c / f).exists(), f
        # 존 3개: core / ref / tube — 상·하류 공기는 존이 아님
        assert set(pl["zones"]) == {"fluid_air_core_r01",
                                    "fluid_ref_r01t01", "solid_tube_r01t01"}
        snap = (c / "system/snappyHexMeshDict").read_text(encoding="utf-8")
        for z in pl["zones"]:
            assert f"cellZone {z};" in snap
        assert "addLayers       false" in snap          # 프리즘 불필요 결론

    def test_units_are_meters(self, tmp_path):
        """실측 함정 회귀: triSurface STL·locationInMesh 는 m 단위여야 함
           (mm 로 넣으면 snappy FATAL 'Point ... is not inside the mesh')"""
        from fthx import presets
        from foam.openfoam import write_case
        from foam.foam_stl import read_stl
        write_case(presets.tutorial(), str(tmp_path / "c"), force=True)
        tris = read_stl(tmp_path / "c/constant/triSurface/fluid_air_core_r01.stl")
        assert tris.max() < 1.0                         # 100mm → 0.1m
        snap = (tmp_path / "c/system/snappyHexMeshDict").read_text("utf-8")
        loc = [float(x) for x in
               snap.split("locationInMesh (")[1].split(")")[0].split()]
        assert all(abs(v) < 1.0 for v in loc)

    def test_wall_level_resolves_thickness(self):
        """관벽 존 형성 조건: level 셀 크기 < t_wall"""
        from fthx import presets
        from foam.openfoam import plan
        pl = plan(presets.tutorial())
        assert pl["h_at"][f"level{pl['lv_wall']}"] < pl["t_wall_mm"]

    def test_probe_not_implemented(self, tmp_path):
        import pytest as _pt
        from fthx import presets
        from foam.openfoam import write_case
        with _pt.raises(NotImplementedError):
            write_case(presets.probe(), str(tmp_path / "p"))

    def test_no_crlf_in_case_files(self, tmp_path):
        """실측 함정 회귀: Windows 에서 생성 시 CRLF 이 들어가면
           WSL 에서 shebang 이 'bash\\r' 로 깨짐 — 전 파일 LF 강제"""
        from fthx import presets
        from foam.openfoam import write_case
        write_case(presets.tutorial(), str(tmp_path / "c"), force=True)
        for f in (tmp_path / "c").rglob("*"):
            if f.is_file() and f.suffix != ".stl":
                assert b"\r" not in f.read_bytes(), f.name



@needs_cad
@needs_cp
class TestThermalB:
    """B안 — 관벽을 셀로 풀지 않고 두께=물성으로 (Bi≪1)"""

    def test_enthalpy_source_offset(self):
        """실측 함정 회귀: sensibleEnthalpy 는 h=cp(T−T_std).
           T_std 오프셋을 빼면 목표온도가 T_ref+T_std 가 되어 가열됨"""
        from fthx import presets
        from foam._thermal_closure import thermal_closure, T_STD
        t = thermal_closure(presets.tutorial())
        # S(T=T_ref) == 0 이어야 냉매온도에서 열원이 사라짐
        h_at_Tref = t["cp"] * (t["T_ref_K"] - T_STD)
        assert abs(t["Su"] + t["Sp"] * h_at_Tref) < 1e-6
        assert t["Su"] < 0        # T_ref < T_std 이므로

    def test_thermal_case_files(self, tmp_path):
        from fthx import presets
        from foam.openfoam import write_case
        pl = write_case(presets.tutorial(), str(tmp_path / "t"), force=True,
                        thermal=True)
        c = tmp_path / "t"
        for f in ("0/T", "0/alphat", "0/p_rgh", "constant/g",
                  "constant/thermophysicalProperties"):
            assert (c / f).exists(), f
        assert pl["physics"]["solver"] == "buoyantSimpleFoam"
        T = (c / "0/T").read_text("utf-8")
        assert "externalWallHeatFluxTemperature" in T   # B안 관벽
        assert "thicknessLayers" in T and "kappaLayers" in T
        fv = (c / "system/fvOptions").read_text("utf-8")
        assert "scalarSemiImplicitSource" in fv         # v2412 정식 이름
        assert pl["physics"]["Bi"] < 0.1                # B안 성립 조건

    def test_isothermal_still_works(self, tmp_path):
        from fthx import presets
        from foam.openfoam import write_case
        pl = write_case(presets.tutorial(), str(tmp_path / "i"), force=True,
                        thermal=False)
        assert pl["physics"]["solver"] == "simpleFoam"
        assert not (tmp_path / "i/0/T").exists()

    def test_field_headers_have_correct_class(self, tmp_path):
        """실측 함정 회귀: 0/ 필드의 FoamFile class 가 dictionary 면
           decomposePar 가 필드를 0개로 보고 processorN/0/ 을 만들지 않음
           → 병렬에서 'cannot find processorN/0/p' (직렬은 통과)"""
        from fthx import presets
        from foam.openfoam import write_case
        write_case(presets.tutorial(), str(tmp_path / "h"), force=True)
        want = {"U": "volVectorField", "p": "volScalarField",
                "p_rgh": "volScalarField", "T": "volScalarField",
                "k": "volScalarField", "epsilon": "volScalarField",
                "nut": "volScalarField", "alphat": "volScalarField"}
        for name, cls in want.items():
            f = tmp_path / "h" / "0" / name
            assert f.exists(), name
            head = f.read_text("utf-8")[:400]
            assert f"class       {cls};" in head, f"{name}: {cls} 아님"
            assert 'location    "0";' in head, name
