"""케이스 → results.csv.

  python scripts/make_results.py <케이스경로> [프리셋] [jf.json] [csv경로]
예:
  python scripts/make_results.py ~/cases/case_tutorial tutorial
  python scripts/make_results.py ~/cases/case_tut_jf tutorial out_foam/jf_cell.json
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foam.results import write_results     # noqa: E402
from foam.jf_inject import load_jf         # noqa: E402
from fthx import presets                   # noqa: E402

a = sys.argv[1:]
if not a:
    print(__doc__)
    sys.exit(2)
case = Path(a[0]).expanduser()
if not case.is_dir():
    # WSL 경로를 Windows python 에 넘긴 경우 안내 (자주 걸림)
    hint = ""
    if str(case).startswith(("/home", "\\home", "/root")):
        hint = ("\n  → WSL 경로를 Windows python 에 넘긴 것 같음. "
                "wslpath 로 변환할 것:\n"
                f'     ... scripts/make_results.py "$(wslpath -w {a[0]})" ...')
    print(f"[오류] 케이스 디렉터리 없음: {case}{hint}", file=sys.stderr)
    sys.exit(2)
name = a[1] if len(a) > 1 else "tutorial"
jf = load_jf(a[2]) if len(a) > 2 and a[2] not in ("-", "none") else None
csvp = a[3] if len(a) > 3 else None
if csvp:
    Path(csvp).expanduser().parent.mkdir(parents=True, exist_ok=True)

r = write_results(case, presets.PRESETS[name](), csvp, jf=jf)
row = r["row"]
print(f"[OK] {r['csv']}")
for k in ("case", "jf_source", "dP_air_Pa", "Q_W", "UA_W_K", "UA_pred_W_K",
          "UA_err_pct", "effectiveness", "NTU", "converged"):
    if row.get(k) is not None:
        v = row[k]
        print(f"     {k:16s} {v:.4g}" if isinstance(v, float)
              else f"     {k:16s} {v}")
