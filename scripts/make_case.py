"""케이스 생성.  python scripts/make_case.py [프리셋] [출력] [air|cht]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foam.openfoam import write_case          # noqa: E402
from fthx import presets                      # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "tutorial"
out = sys.argv[2] if len(sys.argv) > 2 else f"out_foam/case_{name}"
mode = sys.argv[3] if len(sys.argv) > 3 else "air"
pl = write_case(presets.PRESETS[name](), out, force=True, mode=mode)
hw = pl["h_at"][f"level{pl['lv_wall']}"]
print(f"[OK] {name} (mode={mode}) -> {out}")
print(f"     h_bg={pl['h_bg_mm']:.3f}mm  level: core={pl['lv_core']} "
      f"ref={pl['lv_ref']} wall={pl['lv_wall']} (h@wall={hw:.3f} < t={pl['t_wall_mm']:.3f}mm)")
if "physics" in pl:
    ph = pl["physics"]
    print(f"     porous f={ph['f']:.2f} 1/m (d=0)  ΔP_core(해석해)={ph['dp_core_Pa']:.3f} Pa")
