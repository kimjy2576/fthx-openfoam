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


@needs_cad
@needs_cp
class TestProbeAir:
    """O3 — probe(벤드·관3개). air 모드는 벤드가 공기 도메인 밖이라 무관"""

    def test_probe_air_drops_bends(self, tmp_path):
        from fthx import presets
        from foam.openfoam import write_case
        pl = write_case(presets.probe(), str(tmp_path / "p"), force=True)
        ts = tmp_path / "p/constant/triSurface"
        assert not list(ts.glob("*bend*")), "벤드 STL 이 남아있음"
        assert set(pl["surfaces"]) == {f"solid_tube_r01t{i:02d}" for i in (1, 2, 3)}
        assert set(pl["zones"]) == {"fluid_air_core_r01"}

    def test_probe_bbox_is_duct_only(self, tmp_path):
        """배경격자는 air_bbox(덕트) — 벤드가 나가는 global_bbox 가 아님"""
        from fthx import presets
        from foam.openfoam import write_case
        p = presets.probe()
        write_case(p, str(tmp_path / "p"), force=True)
        bm = (tmp_path / "p/system/blockMeshDict").read_text("utf-8")
        zs = [float(l.split()[2].rstrip(")")) for l in bm.splitlines()
              if l.strip().startswith("(") and len(l.split()) == 3]
        assert min(zs) >= p.duct_box["z0"] - 1e-6
        assert max(zs) <= p.duct_box["z1"] + 1e-6

    def test_probe_cht_still_blocked(self, tmp_path):
        import pytest as _pt
        from fthx import presets
        from foam.openfoam import write_case
        with _pt.raises(NotImplementedError):
            write_case(presets.probe(), str(tmp_path / "c"), mode="cht")


@needs_cad
@needs_cp
class TestCellCase:
    """D 모드 — 주기 단위셀 (핀 실형상). core 의 cell.py 를 그대로 씀"""

    def test_cell_case_files(self, tmp_path):
        from fthx import presets
        from foam.cell_case import write_cell_case
        r = write_cell_case(presets.PRESETS["cell"](), str(tmp_path / "c"),
                            force=True)
        c = tmp_path / "c"
        for f in ("system/blockMeshDict", "system/snappyHexMeshDict",
                  "0/U", "0/p", "0/T", "constant/transportProperties",
                  "Allrun.mesh"):
            assert (c / f).exists(), f
        # 관만 STL — 핀·경계는 blockMesh 가 담당.
        # 이름은 core 가 정하므로(1/4→full-pitch 전환 시 r01→r01a/r01b)
        # 하드코딩하지 않고 접두사로만 검사
        assert r["stl"], "관 STL 이 없음"
        assert all(n.startswith("solid_tube") for n in r["stl"])
        assert not (c / "constant/triSurface/solid_fin.stl").exists()

    def test_background_matches_air_domain(self, tmp_path):
        """배경격자 z 범위 = 핀 상면 ~ 핀사이 중앙 (공기만)"""
        from fthx import presets, cell
        from foam.cell_case import write_cell_case
        p = presets.PRESETS["cell"]()
        r = write_cell_case(p, str(tmp_path / "c"), force=True)
        g = cell.cell_geometry(p)
        # 1/4 도메인: z 는 gap 중앙(0) ~ 핀 하면, y 는 Pt/2
        assert r["z_range_mm"][0] == 0.0
        assert abs(r["z_range_mm"][1] - g["fin_z"][0]) < 1e-9
        assert abs(r["Ly_mm"] - g["Ly"] / 2.0) < 1e-9

    def test_laminar_and_symmetry(self, tmp_path):
        """Re_Dh<2300 층류 — 난류 모델을 켜면 h 과대평가 (cell_flow 경고)"""
        from fthx import presets
        from foam.cell_case import write_cell_case
        r = write_cell_case(presets.PRESETS["cell"](), str(tmp_path / "c"),
                            force=True)
        assert r["flow"]["regime"] == "laminar"
        tp = (tmp_path / "c/constant/turbulenceProperties").read_text("utf-8")
        assert "laminar" in tp
        bm = (tmp_path / "c/system/blockMeshDict").read_text("utf-8")
        assert bm.count("symmetryPlane") == 3      # sym_z, sym_y0, sym_y1
        assert "cyclic" not in bm                  # 대칭면이므로 주기 불필요
        assert "fin_wall" in bm


@needs_cad
@needs_cp
class TestJfInject:
    """D→B 주입 — 단위셀 j/f 로 풀사이즈 포러스·열 계수를 스케일"""

    JF = {"j": 0.042443, "f": 0.056622, "source": "openfoam_cell"}

    def test_none_keeps_closure(self):
        from fthx import presets, closure
        from foam.jf_inject import scaled_air_side
        p = presets.tutorial()
        a = scaled_air_side(p, None)
        b = closure.air_side(p)
        assert a["j"] == b["j"] and a["C2_1perm"] == b["C2_1perm"]
        assert a["jf_source"] == "closure"

    def test_ratio_scaling_is_exact(self):
        """C2 ∝ f, h ∝ j — 비율만 곱하므로 공식 재구현 없음"""
        from fthx import presets, closure
        from foam.jf_inject import scaled_air_side
        p = presets.tutorial()
        base, cell = closure.air_side(p), scaled_air_side(p, self.JF)
        rj, rf = self.JF["j"] / base["j"], self.JF["f"] / base["f"]
        assert abs(cell["C2_1perm"] / base["C2_1perm"] - rf) < 1e-9
        assert abs(cell["h_W_m2K"] / base["h_W_m2K"] - rj) < 1e-9
        assert abs(cell["hv_W_m3K"] / base["hv_W_m3K"] - rj) < 1e-9
        assert cell["j"] == self.JF["j"] and cell["f"] == self.JF["f"]

    def test_case_uses_injected_jf(self, tmp_path):
        from fthx import presets
        from foam.openfoam import write_case
        p = presets.tutorial()
        a = write_case(p, str(tmp_path / "a"), force=True)
        b = write_case(p, str(tmp_path / "b"), force=True, jf=self.JF)
        assert a["physics"]["jf_source"] == "closure"
        assert b["physics"]["jf_source"] == "openfoam_cell"
        assert b["physics"]["f"] > a["physics"]["f"]       # C2 스케일됨
        assert b["physics"]["UA_pred_W_K"] > a["physics"]["UA_pred_W_K"]
        fv = (tmp_path / "b/system/fvOptions").read_text("utf-8")
        assert f"{b['physics']['f']:.6f}" in fv

    def test_load_jf_requires_keys(self, tmp_path):
        import json
        import pytest as _pt
        from foam.jf_inject import load_jf
        f = tmp_path / "bad.json"
        f.write_text(json.dumps({"j": 0.04}), encoding="utf-8")
        with _pt.raises(ValueError):
            load_jf(f)

    def test_core_volume_excludes_tubes(self):
        """D4 회귀: fvOptions 가 적용되는 cellZone 은 관 체적을 제외한
           영역. 예측에 core_bbox 를 쓰면 V 가 ~13% 과대 → UA 과대평가"""
        import math
        from fthx import presets
        from foam._thermal_closure import core_volume_m3
        p = presets.tutorial()
        cb = p.core_bbox
        V_box = (cb[1]-cb[0]) * (cb[3]-cb[2]) * (cb[5]-cb[4]) / 1e9
        V = core_volume_m3(p)
        assert V < V_box
        n = len(p.tube_centers())
        V_t = n * math.pi/4 * (p.tube.Do/1000)**2 * (cb[5]-cb[4])/1000
        assert abs(V - (V_box - V_t)) < 1e-12

    def test_ua_uses_same_volume_as_fvoptions(self):
        """예측 UA 와 hv_eff 가 같은 체적을 써야 자기일관"""
        from fthx import presets
        from foam._thermal_closure import (ua_predicted, thermal_closure,
                                           core_volume_m3)
        p = presets.tutorial()
        jf = {"j": 0.042443, "f": 0.056622}
        u, t = ua_predicted(p, jf=jf), thermal_closure(p, jf=jf)
        V = core_volume_m3(p)
        assert abs(u["UA_air_W_K"] - t["hv_air_W_m3K"] * V) < 1e-9
        assert abs(u["UA_W_K"] - t["hv_W_m3K"] * V) < 1e-9      # hv_eff 정의
