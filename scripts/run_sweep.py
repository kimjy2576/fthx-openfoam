"""파라미터 스윕.

  python scripts/run_sweep.py <grid.json> [프리셋] [작업경로] [csv] [jf.json]

grid.json 예:
  {"V_face": [1.0, 2.0, 3.0], "FPI": [12, 14, 16]}   → 9 조합

단축키: V_face T_air_in T_sat FPI fin_type Pt Pl Do Nr Nt
그 외는 점 표기 그대로 ("operating.air.RH_in" 등).
환경변수: FTHX_NP(코어), FTHX_SOLVE=0(생성만), FTHX_KEEP=1(케이스 보존)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foam.sweep import run_sweep, expand   # noqa: E402
from foam.jf_inject import load_jf         # noqa: E402
from fthx import presets                   # noqa: E402

a = sys.argv[1:]
if not a:
    print(__doc__)
    sys.exit(2)
grid = json.loads(Path(a[0]).read_text(encoding="utf-8"))
name = a[1] if len(a) > 1 else "tutorial"
work = a[2] if len(a) > 2 else "out_foam/sweep"
csvp = a[3] if len(a) > 3 else "out_foam/sweep/results.csv"
jf = load_jf(a[4]) if len(a) > 4 and a[4] not in ("-", "none") else None

n = len(expand(grid))
print(f"조합 {n}개 · 프리셋 {name} · j/f {'cell' if jf else 'closure'}")
s = run_sweep(presets.PRESETS[name](), grid, work, csvp, jf=jf,
              np_cores=int(os.environ.get("FTHX_NP", 8)),
              solve=os.environ.get("FTHX_SOLVE", "1") != "0",
              keep_cases=os.environ.get("FTHX_KEEP") == "1")
print(f"\n완료: {s['ok']}/{s['n']} 성공, {s['failed']} 실패 → {s['csv']}")
for e in s["errors"][:5]:
    print(f"  실패 {e['label']}: {e['error'][:120]}")
