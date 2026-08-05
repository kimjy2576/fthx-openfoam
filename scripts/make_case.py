"""케이스 생성.

  python scripts/make_case.py [프리셋] [출력] [air|cht] [jf.json]

네 번째 인자에 단위셀 j/f JSON 을 주면 상관식 대신 그 값으로 포러스·열
계수를 스케일함 (D→B 주입).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foam.openfoam import write_case          # noqa: E402
from fthx import presets                      # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "tutorial"
out = sys.argv[2] if len(sys.argv) > 2 else f"out_foam/case_{name}"
mode = sys.argv[3] if len(sys.argv) > 3 else "air"
jf = None
if len(sys.argv) > 4:
    from foam.jf_inject import load_jf
    jf = load_jf(sys.argv[4])
pl = write_case(presets.PRESETS[name](), out, force=True, mode=mode, jf=jf)
hw = pl["h_at"][f"level{pl['lv_wall']}"]
print(f"[OK] {name} (mode={mode}) -> {out}")
print(f"     h_bg={pl['h_bg_mm']:.3f}mm  level: core={pl['lv_core']} "
      f"ref={pl['lv_ref']} wall={pl['lv_wall']} (h@wall={hw:.3f} < t={pl['t_wall_mm']:.3f}mm)")
if "physics" in pl:
    ph = pl["physics"]
    print(f"     porous f={ph['f']:.2f} 1/m (d=0)  ΔP_core(해석해)={ph['dp_core_Pa']:.3f} Pa")
    print(f"     j/f 출처: {ph.get('jf_source','closure')}  "
          f"(j={ph.get('j_used',0):.5f} f={ph.get('f_used',0):.5f})")
