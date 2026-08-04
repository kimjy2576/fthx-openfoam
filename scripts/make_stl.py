"""프리셋 전체 STL 내보내기.  python scripts/make_stl.py [프리셋 ...]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foam.foam_stl import export_stl          # noqa: E402 (core 경로는 foam/__init__)
from fthx import presets                      # noqa: E402

for n in (sys.argv[1:] or list(presets.PRESETS)):
    m = export_stl(presets.PRESETS[n](), outdir=f"out_foam/{n}")
    worst = max(b["area_err"] for b in m["bodies"].values())
    print(f"[OK] {n}: {len(m['bodies'])} bodies, max area_err {worst:.4%}")
