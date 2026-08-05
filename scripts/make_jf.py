"""단위셀 결과 → j/f JSON.

사용:
  python scripts/make_jf.py <pCore0> <pCore1> <Tout> [pIn] [pOut] [출력경로]
예:
  python scripts/make_jf.py 23.28486 8.038156 280.8012 30.58949 0 out_foam/jf_cell.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foam.cell_case import report_jf      # noqa: E402
from fthx import presets                  # noqa: E402

a = sys.argv[1:]
if len(a) < 3:
    print(__doc__)
    sys.exit(2)
pc0, pc1, tout = float(a[0]), float(a[1]), float(a[2])
pin = float(a[3]) if len(a) > 3 else None
pout = float(a[4]) if len(a) > 4 else None
out = Path(a[5] if len(a) > 5 else "out_foam/jf_cell.json")

p = presets.PRESETS["cell"]()
r = report_jf(p, pc0, pc1, tout, pin, pout)
doc = {"j": r["j"], "f": r["f"], "Re_Dc": r["Re_Dc"],
       "h_W_m2K": r["h_W_m2K"], "dp_core_Pa": r["dp_Pa"],
       "effectiveness": r["effectiveness"], "source": "openfoam_cell",
       "preset": p.name,
       "note": "주기 단위셀(핀 실형상) CFD. 효율이 0.9 를 넘으면 LMTD 민감"}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[OK] {out}")
for k in ("j", "f", "h_W_m2K", "dp_core_Pa", "effectiveness"):
    print(f"     {k:14s} {doc[k]:.5g}")
