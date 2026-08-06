# fthx-openfoam

FT-HX 열교환기 CFD 자동화의 **OpenFOAM 경로** (Windows + WSL2, OpenFOAM v2412 / .com).
형상·회로·폐합 코어는 [fthx-cfd-studio](https://github.com/kimjy2576/fthx-cfd-studio)
를 `core/` submodule 로 참조함 — **중복 구현 금지 원칙**. Fluent 경로에서
closure/params 가 갱신되면 `check.sh` 가 자동으로 최신 core 를 받아옴.

라이선스가 필요 없으므로 HPC 큐 대기 없이 워크스테이션에서 바로 실행됨.

---

# 새 PC 설치 (처음 한 번)

권장 사양: 물리 8코어 이상, RAM 32GB 이상, 여유 디스크 50GB 이상.
tutorial(40k셀) · probe(96k셀) · 단위셀(366k셀)은 이 사양에서 수 분 내 완주함.

## 1. WSL2 + Ubuntu (PowerShell 관리자)

```powershell
wsl --install -d Ubuntu-24.04
wsl --set-default-version 2
```

재부팅 → Ubuntu 실행 → 사용자 계정 생성.
`wsl` 실행 시 가상화 오류가 나면 BIOS 에서 VT-x/AMD-V 활성화 필요.

리소스 배정 — `C:\Users\<계정>\.wslconfig` 생성 후 `wsl --shutdown`:

```ini
[wsl2]
memory=24GB      # 물리 RAM 의 60~75%
processors=14    # 물리 코어에서 2 정도 남김
```

## 2. OpenFOAM v2412 (.com / ESI) — WSL 안에서

```bash
curl https://dl.openfoam.com/add-debian-repo.sh | sudo bash
sudo apt install -y openfoam2412-default
echo 'source /usr/lib/openfoam/openfoam2412/etc/bashrc' >> ~/.bashrc
source ~/.bashrc
which blockMesh snappyHexMesh simpleFoam buoyantSimpleFoam checkMesh surfaceCheck
```

⚠ **.com(ESI) 배포판이어야 함.** .org/Foundation 은 딕셔너리 문법과 유틸
이름이 달라서 이 레포의 생성기가 맞지 않음.

설치 확인 (10분):

```bash
mkdir -p ~/cases && cd ~/cases
cp -r $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily . && cd pitzDaily
blockMesh && simpleFoam | tail -3      # "End" 나오면 정상
```

## 3. 레포 clone (Windows 쪽 경로에)

두 레포를 **형제 폴더로** 두어야 venv 가 재사용됨.

```powershell
cd C:\Users\<계정>\dev
git config --global core.autocrlf false     # WSL 스크립트가 CRLF 로 깨지는 것 방지
git clone https://github.com/kimjy2576/fthx-cfd-studio.git
git clone --recurse-submodules https://github.com/kimjy2576/fthx-openfoam.git
```

결과 구조:

```
dev/
 ├ fthx-cfd-studio/     ← Fluent 경로 + 코어. venv 가 여기 생김
 └ fthx-openfoam/       ← 이 레포. core/ 가 위를 submodule 로 참조
```

## 4. Python 환경 (fthx-cfd-studio 쪽에 1회)

```powershell
cd C:\Users\<계정>\dev\fthx-cfd-studio
.\run.bat                  # .venv 생성 + cadquery 등 설치 (수 분)
                           # 서버가 뜨면 Ctrl+C 로 종료
.venv\Scripts\python -m pip install pytest
```

cadquery 가 커서 오래 걸림. `.venv\Scripts\python.exe` 가 생기면 완료.

## 5. 설치 검증

```bash
# WSL
cd /mnt/c/Users/<계정>/dev/fthx-openfoam
bash scripts/check.sh
```

마지막에 `ALL OK` 가 나오면 설치 완료.

### 새 PC 에서 자주 걸리는 것

| 증상 | 원인·해결 |
|---|---|
| `set: invalid option` / `$'\r': command not found` | CRLF. `sed -i 's/\r$//' scripts/*.sh` 후 `git config core.autocrlf false` |
| `No module named cadquery` | 전역 python 사용. `.venv\Scripts\python` 을 쓸 것 (check.sh 는 자동 탐색) |
| `No module named pytest` | 4단계의 pip install 누락 |
| `surfaceCheck: command not found` | OpenFOAM bashrc 미적용. `source /usr/lib/openfoam/openfoam2412/etc/bashrc` |
| `core/` 가 비어 있음 | `git submodule update --init --recursive` |

---

# 일상 루틴 (두 줄)

```powershell
# Windows — 이것만 직접
cd C:\Users\<계정>\dev\fthx-openfoam ; git pull
```
```bash
# WSL — 나머지는 전부 자동
cd /mnt/c/Users/<계정>/dev/fthx-openfoam && bash scripts/check.sh
```

`check.sh` 가 수행하는 것: pytest → STL 생성+surfaceCheck → 케이스 생성 →
`~/cases` 로 복사 → 메싱 → checkMesh → cellZone 검산 → 8코어 솔버 → ΔP·Q·UA.
**실패하면 해당 로그 마지막 30줄을 자동 출력하고 멈춤** — 그 출력을 그대로
회신하면 됨. 끝까지 가면 `ALL OK`.

기대 출력 (tutorial 기준):

```
1/4  18 passed
2/4  PASS 30 · FAIL 0 · UNKNOWN 0
3/4  [OK] tutorial (mode=air)
4/4  cells:39626 · fluid_air_core_r01: 24994 · Mesh OK
5/5  ΔP 8.100 Pa · Q 51.81 W · UA_CFD 3.385 vs 예측 3.349 W/K
     ALL OK
```

옵션: `FTHX_FULL=1`(전체 pytest) · `FTHX_SOLVE=0`(솔버 생략) ·
`FTHX_NP=4`(코어 수) · `FTHX_PYTEST_K="CellCase"`(테스트 범위)

## 개별 케이스 실행

```powershell
# Windows — 케이스 생성
cd C:\Users\<계정>\dev\fthx-openfoam
..\fthx-cfd-studio\.venv\Scripts\python scripts\make_case.py probe out_foam\case_probe
```
```bash
# WSL — 실행 (반드시 ~/cases 에서. /mnt/c 는 I/O 가 5~10배 느림)
cp -r out_foam/case_probe ~/cases/ && cd ~/cases/case_probe
./Allrun.mesh && ./Allrun.solve
```

단위셀(D 모드)은 전용 생성기를 씀:

```powershell
..\fthx-cfd-studio\.venv\Scripts\python -c "import sys;sys.path.insert(0,'.');import foam;from fthx import presets;from foam.cell_case import write_cell_case;write_cell_case(presets.PRESETS['cell'](),'out_foam/case_cell',force=True)"
```
```bash
cp -r out_foam/case_cell ~/cases/ && cd ~/cases/case_cell
./Allrun.mesh && ./Allrun.solve      # 끝에 pCore0/1·pIn/Out·Tout 출력
```

출력값 → j/f 변환:

```python
from foam.cell_case import report_jf
from fthx import presets
report_jf(presets.PRESETS['cell'](), pCore0, pCore1, Tout, pIn, pOut)
```

---

# 구조

```
core/       fthx-cfd-studio submodule (params·circuits·closure·cad·cell·presets)
foam/       foam_stl.py    F0 STL 내보내기 + 3종 검증
            openfoam.py    F1~F3 blockMesh/snappy/물리 (B 모드 풀사이즈)
            cell_case.py   D 모드 주기 단위셀 → j/f
            _thermal_closure.py  열 폐합 (core closure 래퍼)
            jf_inject.py   D→B 주입 (단위셀 j/f → 포러스·열 계수)
            results.py     F5 후처리 → results.csv (core post 스키마)
            sweep.py       파라미터 스윕 (조합 전개·무인 실행·실패 격리)
            cht_case.py    3영역 conjugate (공기·관벽·냉매) — Fluent 대등
scripts/    check.sh(통합) · make_stl · make_case · make_jf · make_results
            run_sweep · compare_paths(O5) · verify_stl
docs/       verify-routine.md · openfoam-issues.md (미해결 항목)
tests/      test_foam.py (18개 회귀)
```

설계 원칙: 형상·물리 폐합은 `core/` 에만 두고 이 레포는 **OpenFOAM 배선만**
담당. 사이징은 전부 파라미터의 함수 — 사람이 만질 값 없음.

# 상태

| 단계 | 결과 |
|---|---|
| F0 STL | watertight·면적오차<0.1%·surfaceCheck 교차검증 |
| F1+F2 메시 | tutorial 39,626셀 / probe 95,700셀 / 단위셀 365,683셀, 전부 Mesh OK |
| F3 물리 | 포러스 fvOptions(f=C2 단독) + 경계조건 |
| B안 열전달 | 관벽을 셀로 풀지 않고 두께=물성 (Bi=0.017) |
| **검증** (16코어 수렴) | 상관식 UA 3.031 vs 예측 2.971 (**+2.0%**) · 단위셀 j/f 주입 7.194 vs 7.501 (**−4.1%**) |
| D 모드 | 358,525셀 수렴 · j=0.0424 f=0.0566 (상관식의 2.9/3.3배) |
| D→B 주입 | `jf_inject.py` — 단위셀 j/f 로 포러스·열 계수 스케일 (C2∝f, h∝j) |
| F5 후처리 | `results.py` — core 의 post.to_row 스키마 그대로, 상관식/단위셀 기준을 한 CSV 에 |
| 스윕 | `sweep.py` — 조합별 무인 실행, 실패해도 계속 진행하고 사유 기록 |

## 스윕 사용법

```bash
# 9 조합 (V_face 3 x FPI 3)
FTHX_NP=16 ../fthx-cfd-studio/.venv/Scripts/python.exe scripts/run_sweep.py \
    examples/grid_9.json tutorial ~/cases/sweep ~/cases/sweep/results.csv
```

`examples/grid_36.json` 은 Fluent 36조합에 대응. 다섯 번째 인자로 단위셀
j/f JSON 을 주면 그 기준으로 스윕함. `FTHX_SOLVE=0` 이면 생성만.

다음: Fluent 교차비교(O5) → 단위셀 j/f 값 확정(D3).
미해결 항목은 `docs/openfoam-issues.md` 참조.
