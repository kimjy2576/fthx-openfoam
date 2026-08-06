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


@needs_cad
@needs_cp
class TestResults:
    """F5 — results.csv (core 의 post.py 스키마 그대로)"""

    def _fake_case(self, tmp_path, thermal=True):
        """postProcessing 구조만 흉내낸 최소 케이스"""
        c = tmp_path / "case"
        (c / "0").mkdir(parents=True)
        if thermal:
            (c / "0" / "T").write_text("dummy", encoding="utf-8")
        for name, val in (("pIn", 101333.1), ("pOut", 101325.0),
                          ("Tout", 292.25)):
            d = c / "postProcessing" / name / "0"
            d.mkdir(parents=True)
            (d / "surfaceFieldValue.dat").write_text(
                f"# Time\tareaAverage\n50\t{val:.6e}\n", encoding="utf-8")
        (c / "log.solver").write_text("SIMPLE solution converged in 281 iterations",
                                      encoding="utf-8")
        return c

    def test_schema_matches_core_post(self, tmp_path):
        """열 이름은 core 의 post.to_row 가 정함 — 여기서 새로 만들지 않음"""
        from fthx import presets, post
        from foam.results import write_results
        p = presets.tutorial()
        c = self._fake_case(tmp_path)
        r = write_results(c, p)
        base = post.to_row(p, post.metrics(p, {}))
        for k in base:
            assert k in r["row"], k
        for k in ("dP_air_Pa", "Q_W", "UA_W_K", "UA_pred_W_K", "UA_err_pct"):
            assert k in r["row"], k
        assert r["row"]["path"] == "openfoam"
        assert r["row"]["converged"] is True

    def test_jf_source_recorded(self, tmp_path):
        from fthx import presets
        from foam.results import write_results
        p = presets.tutorial()
        jf = {"j": 0.042443, "f": 0.056622, "source": "openfoam_cell"}
        a = write_results(self._fake_case(tmp_path / "a"), p)
        b = write_results(self._fake_case(tmp_path / "b"), p, jf=jf)
        assert a["row"]["jf_source"] == "closure"
        assert b["row"]["jf_source"] == "openfoam_cell"
        # 같은 CFD 값이라도 예측이 달라지므로 오차가 달라야 함
        assert a["row"]["UA_pred_W_K"] < b["row"]["UA_pred_W_K"]

    def test_rows_append(self, tmp_path):
        import csv as _csv
        from fthx import presets
        from foam.results import write_results
        p = presets.tutorial()
        out = tmp_path / "results.csv"
        write_results(self._fake_case(tmp_path / "a"), p, out)
        write_results(self._fake_case(tmp_path / "b"), p, out,
                      jf={"j": 0.0424, "f": 0.0566, "source": "cell"})
        rows = list(_csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 2
        assert {r["jf_source"] for r in rows} == {"closure", "cell"}

    def test_isothermal_scales_kinematic_p(self, tmp_path):
        """등온(simpleFoam)은 p 가 kinematic — rho 를 곱해 Pa 로"""
        from fthx import presets
        from foam.results import read_case
        p = presets.tutorial()
        c = self._fake_case(tmp_path, thermal=False)
        raw = read_case(c, p)
        rho = p.operating_derived()["air"]["rho"]
        assert abs(raw["p_air_in"] - 101333.1 * rho) < 1e-6


@needs_cad
@needs_cp
class TestSweep:
    """파라미터 스윕 — 조합 전개·오버라이드·무인 실행"""

    def test_expand_is_cartesian(self):
        from foam.sweep import expand
        c = expand({"V_face": [1, 2, 3], "FPI": [12, 14]})
        assert len(c) == 6
        assert {tuple(sorted(x.items())) for x in c} == {
            (("FPI", f), ("V_face", v)) for v in (1, 2, 3) for f in (12, 14)}

    def test_overrides_apply(self):
        from fthx import presets
        from foam.sweep import apply_overrides
        p = presets.tutorial()
        q = apply_overrides(p, {"V_face": 3.5, "FPI": 16})
        assert q.operating.air.V_face == 3.5 and q.fin.FPI == 16
        assert p.operating.air.V_face == 2.0        # 원본 불변
        # 점 표기도 지원
        r = apply_overrides(p, {"operating.air.T_in": 35.0})
        assert r.operating.air.T_in == 35.0

    def test_labels_are_filename_safe(self):
        from foam.sweep import case_label
        s = case_label({"V_face": 1.5, "fin_type": "louver"})
        assert s == "V_face1p5_fin_typelouver"
        assert "." not in s and "/" not in s and " " not in s

    def test_generation_only(self, tmp_path):
        """solve=False 로 케이스만 — 오버라이드가 실제로 반영되는지"""
        from fthx import presets
        from foam.sweep import run_sweep
        s = run_sweep(presets.tutorial(), {"V_face": [1.5]},
                      tmp_path / "w", tmp_path / "r.csv",
                      solve=False, keep_cases=True)
        assert s["ok"] == 1 and s["failed"] == 0
        u = (tmp_path / "w/case_V_face1p5/0/U").read_text("utf-8")
        assert "(1.5 0 0)" in u
        assert (tmp_path / "w/sweep_summary.json").exists()

    def test_failure_does_not_stop_sweep(self, tmp_path):
        """한 조합이 실패해도 나머지는 계속 — 사유는 errors 에"""
        from fthx import presets
        from foam.sweep import run_sweep
        s = run_sweep(presets.tutorial(),
                      {"V_face": [1.5], "tube.Do": [9.52, -1.0]},
                      tmp_path / "w", tmp_path / "r.csv",
                      solve=False, keep_cases=False)
        assert s["n"] == 2
        assert s["ok"] >= 1 and s["failed"] >= 1
        assert s["errors"][0]["error"]


class TestComparePaths:
    """O5 — Fluent↔OpenFOAM results.csv 교차비교 (스키마 공유 전제)"""

    def _csv(self, path, **over):
        import csv
        h = ["case", "Nr", "Nt", "FPI", "fin_type", "Pt_mm", "Pl_mm",
             "V_face_ms", "T_air_in_C", "T_sat_C", "dP_air_Pa", "Q_W", "UA_W_K"]
        row = dict(zip(h, ["t1", "1", "1", "14.0", "plain", "25.4", "22.0",
                           "2.0", "27.0", "7.0", "4.0", "45.0", "2.9"]))
        row.update(over)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=h)
            w.writeheader()
            w.writerow(row)

    def test_matches_on_condition_keys(self, tmp_path, capsys):
        import subprocess
        import sys as _s
        from pathlib import Path as _P
        a, b = tmp_path / "f.csv", tmp_path / "o.csv"
        self._csv(a)
        self._csv(b, dP_air_Pa="8.0", UA_W_K="3.0")
        script = _P(__file__).resolve().parents[1] / "scripts" / "compare_paths.py"
        r = subprocess.run([_s.executable, str(script), str(a), str(b)],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert "공통 조건 1건" in r.stdout
        assert "+100.0" in r.stdout          # dP 4→8
        assert "15% 초과 항목 1/" in r.stdout

    def test_reports_no_match(self, tmp_path):
        import subprocess
        import sys as _s
        from pathlib import Path as _P
        a, b = tmp_path / "f.csv", tmp_path / "o.csv"
        self._csv(a)
        self._csv(b, V_face_ms="3.0")        # 조건이 다름
        script = _P(__file__).resolve().parents[1] / "scripts" / "compare_paths.py"
        r = subprocess.run([_s.executable, str(script), str(a), str(b)],
                           capture_output=True, text=True)
        assert r.returncode == 1
        assert "짝지을 조건이 없음" in r.stdout


@needs_cad
@needs_cp
class TestChtCase:
    """O6 — 3영역 conjugate (공기·관벽·냉매). Fluent 대등 옵션"""

    def test_three_region_files(self, tmp_path):
        from fthx import presets
        from foam.cht_case import write_cht_case
        r = write_cht_case(presets.tutorial(), str(tmp_path / "c"), force=True)
        c = tmp_path / "c"
        assert r["regions"] == ["air", "tube", "ref"]
        for f in ("constant/regionProperties", "system/fvSchemes",
                  "constant/g", "Allrun.mesh", "Allrun.solve",
                  "0/air/T", "0/air/U", "0/tube/T", "0/ref/T", "0/ref/U",
                  "constant/air/thermophysicalProperties",
                  "constant/tube/thermophysicalProperties",
                  "constant/ref/thermophysicalProperties",
                  "system/air/topoSetDict", "system/air/fvOptions"):
            assert (c / f).exists(), f

    def test_core_zone_absent_in_snappy(self, tmp_path):
        """공기가 한 region 으로 남으려면 코어를 cellZone 으로 잡으면 안 됨
           (실측: 잡으면 상류·코어·하류 3조각으로 쪼개짐)"""
        from fthx import presets
        from foam.cht_case import write_cht_case
        write_cht_case(presets.tutorial(), str(tmp_path / "c"), force=True)
        snap = (tmp_path / "c/system/snappyHexMeshDict").read_text("utf-8")
        assert "fluid_air_core" not in snap
        assert "solid_tube" in snap and "fluid_ref" in snap
        # 포러스는 분리 후 topoSet 으로 재생성
        ts = (tmp_path / "c/system/air/topoSetDict").read_text("utf-8")
        assert "porousCore" in ts and "boxToCell" in ts

    def test_water_and_copper_properties(self, tmp_path):
        from fthx import presets
        from foam.cht_case import write_cht_case
        write_cht_case(presets.tutorial(), str(tmp_path / "c"), force=True)
        ref = (tmp_path / "c/constant/ref/thermophysicalProperties").read_text("utf-8")
        assert "rhoConst" in ref and "999.7" in ref     # 단상 물
        tube = (tmp_path / "c/constant/tube/thermophysicalProperties").read_text("utf-8")
        assert "heSolidThermo" in tube and "386" in tube  # 구리

    def test_coupled_bc_on_all_regions(self, tmp_path):
        from fthx import presets
        from foam.cht_case import write_cht_case
        write_cht_case(presets.tutorial(), str(tmp_path / "c"), force=True)
        for r, kappa in (("air", "fluidThermo"), ("tube", "solidThermo"),
                         ("ref", "fluidThermo")):
            t = (tmp_path / f"c/0/{r}/T").read_text("utf-8")
            assert "turbulentTemperatureRadCoupledMixed" in t, r
            assert kappa in t, r

    def test_mass_flow_from_params(self, tmp_path):
        from fthx import presets
        from foam.cht_case import write_cht_case
        p = presets.tutorial()
        r = write_cht_case(p, str(tmp_path / "c"), force=True)
        assert r["m_ref_kgs"] == p.operating.ref.m_total
        u = (tmp_path / "c/0/ref/U").read_text("utf-8")
        assert "flowRateInletVelocity" in u and "massFlowRate" in u
