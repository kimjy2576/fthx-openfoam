# fthx-openfoam

FT-HX CFD Studio 의 **OpenFOAM 경로** (Windows + WSL2, OpenFOAM v2412/.com).
형상·회로·폐합 코어는 [fthx-cfd-studio](https://github.com/kimjy2576/fthx-cfd-studio)
를 `core/` submodule 로 참조함 — **중복 구현 금지 원칙**. Fluent 경로에서
closure/params 가 갱신되면 `check.sh` 가 자동으로 최신 core 를 받아옴.

## 루틴 (두 줄)

```powershell
# Windows
cd C:\Users\kimjy\dev\fthx-openfoam ; git pull
```
```bash
# WSL
cd /mnt/c/Users/kimjy/dev/fthx-openfoam && bash scripts/check.sh
```

첫 회만: `git clone --recurse-submodules https://github.com/kimjy2576/fthx-openfoam.git`
(venv 는 형제 폴더의 fthx-cfd-studio/.venv 를 자동 재사용 — 새 설치 없음)

## 구조

```
core/       fthx-cfd-studio submodule (params·circuits·closure·cad·presets)
foam/       foam_stl.py(F0) · openfoam.py(F1~F3: blockMesh/snappy/물리)
scripts/    check.sh(통합 검증) · make_stl · make_case · verify_stl
docs/       verify-routine.md · openfoam-issues.md(O1~O5)
tests/      test_foam.py (F0~F3 회귀)
```

## 상태

F0 ✅ STL(3종 검증) → F1+F2 ✅ 메시(tutorial 39,626셀 · cellZone 검산)
→ F3 ✅ 공기측 simpleFoam (ΔP=7.88 Pa @2m/s, f=C2 단독 폐합)
→ B안 열전달 ✅ (buoyantSimpleFoam + 체적 열원 + externalWallHeatFlux,
   UA_CFD 3.38 vs 예측 3.349 W/K)  → O3 probe ✅ (95,700셀, UA 8.114 vs 예측 8.038 — 0.95%)
   → D 모드 단위셀 ✅ 메시(365,683셀·Mesh OK) + j/f 추출 배선
   →  다음: 단위셀 수렴·f 정의 정렬 → closure 주입 → O5
