# push 후 검증 루틴 (OpenFOAM 경로)

Claude 가 push 할 때마다 아래 순서로 확인함. 1·2단계는 매번, 3단계는 형상이
바뀐 커밋에서만.

## 통합 실행 (권장) — 두 줄로 끝

```powershell
# Windows
cd C:\Users\kimjy\dev\fthx-cfd-studio ; git pull
```
```bash
# WSL
cd /mnt/c/Users/kimjy/dev/fthx-cfd-studio && bash scripts/check.sh
```

`scripts/check.sh` 가 아래 전 단계를 순서대로 수행함:
1. pytest 회귀 (Windows venv 의 python.exe 를 WSL 에서 직접 호출)
2. STL 생성 + surfaceCheck 교차검증
3. tutorial 케이스 생성
4. `~/cases/case_tutorial` 로 복사 → 메싱 → checkMesh → cellZone 검산
5. simpleFoam(8코어) → ΔP 추출 (건너뛰려면 FTHX_SOLVE=0)

실패하면 해당 로그의 마지막 30줄을 자동으로 출력하고 멈춤 — 그 출력을
그대로 회신하면 됨. 끝까지 가면 `ALL OK` — 그 출력 전체를 회신.

3단계(ParaView 육안)만 자동화 밖: 커밋 메시지에 **[geom]** 태그가 있을 때
`out_foam/probe/*.stl` 을 열어 확인.

빠른 반복이 필요할 때: `FTHX_FULL=1 bash scripts/check.sh` (전체 스위트), `FTHX_PYTEST_K="FoamCase" bash scripts/check.sh` (더 좁게)

---

아래는 단계별 수동 실행 (문제 원인 분리가 필요할 때만):

## 1단계 — 회귀 + STL 생성 (Windows PowerShell, ~1분)

반드시 레포 venv 의 python 을 사용 (전역 python 에는 cadquery 가 없음).
`.venv` 이 없으면 `run.bat` 을 한 번 실행해 생성 (서버는 Ctrl+C 로 종료).

```powershell
cd fthx-cfd-studio
git pull
.venv\Scripts\python -m pytest tests/ -q     # 실패 0 확인 (cadquery 있으면 skip 없이 103+)
.venv\Scripts\python scripts\make_stl.py     # 전 프리셋 → out_foam/<프리셋>/
```

`make_stl.py` 가 예외 없이 `[OK]` 를 찍으면 내장 검증
(watertight · STL↔CAD 면적오차<0.1% · 인벤토리 1:1) 통과임.
여기서 실패하면 2단계로 가지 말고 에러 전문을 회신.

## 2단계 — OpenFOAM 자체 검사 (WSL, ~1분)

1단계와 독립된 구현(surfaceCheck)으로 교차검증. snappyHexMesh 가 실제
소비자이므로 이것이 최종 판정.

```bash
source /usr/lib/openfoam/openfoam2412/etc/bashrc   # .bashrc 에 있으면 생략
cd /mnt/c/<레포 경로>/fthx-cfd-studio
bash scripts/verify_stl.sh out_foam
```

기대: 전 파일 `[PASS]`, 마지막 줄 `FAIL 0 · UNKNOWN 0`.
`[FAIL]`/`[????]` 가 있으면 표시된 로그 파일 내용을 회신.

주의: 검사만 하는 것이므로 `/mnt/c` 에서 바로 실행해도 됨.
(느려지는 것은 snappy/솔버 실행이며, 그때만 `~/cases` 로 복사)

## 3단계 — 육안 확인 (ParaView, 형상 변경 커밋만)

커밋 메시지에 **[geom]** 태그가 있으면 수행:

1. ParaView 에서 `out_foam/probe/*.stl` 전체 열기 (다중 선택)
2. 확인: 벤드↔관 끝 맞물림 · 코어 박스의 관 구멍 · 상·하류 박스 접합
3. 어긋난 부분은 스크린샷으로 회신

## 메시 단계 — F1+F2 커밋부터 (WSL, tutorial ~1분)

1·2단계 통과 후, 케이스 생성 커밋이면 실제 메싱까지:

```powershell
# Windows — 케이스 생성 (딕셔너리+STL(m 단위)+Allrun)
.venv\Scripts\python scripts\make_case.py tutorial
```

```bash
# WSL — 실행은 WSL 파일시스템에서 (mnt/c 는 I/O 느림)
cp -r /mnt/c/Users/kimjy/dev/fthx-cfd-studio/out_foam/case_tutorial ~/cases/
cd ~/cases/case_tutorial && ./Allrun.mesh
```

기대 요약:
```
Snapped mesh : cells:16만±   (Fluent 68,641 과 같은 자릿수면 통과)
  fluid_air_core_r01: >0
  fluid_ref_r01t01:   >0
  solid_tube_r01t01:  >0     ← 0 이면 관벽 존 형성 실패
Mesh OK.
```
실패 시 해당 log.* 파일 마지막 30줄을 회신.

## 회신 형식 (2단계 기준)

```
1단계: 103 passed / make_stl [OK] 2건
2단계: PASS 18 · FAIL 0 · UNKNOWN 0
(3단계 해당 시: 이상 없음 / 스크린샷 첨부)
```

이 세 줄이면 다음 단계 착수 가능.
