"""3영역 conjugate 케이스 생성 (공기·관벽·냉매).

  python scripts/make_cht.py [프리셋] [출력] [jf.json]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foam.cht_case import write_cht_case    # noqa: E402
from foam.jf_inject import load_jf          # noqa: E402
from fthx import presets                    # noqa: E402

a = sys.argv[1:]
name = a[0] if a else "tutorial"
out = a[1] if len(a) > 1 else f"out_foam/cht_{name}"
jf = load_jf(a[2]) if len(a) > 2 and a[2] not in ("-", "none") else None
r = write_cht_case(presets.PRESETS[name](), out, force=True, jf=jf)
print(f"[OK] {name} (cht) -> {out}")
print(f"     regions {r['regions']}  냉매 {r['m_ref_kgs']:.4g} kg/s  "
      f"j/f {r['jf_source']}")
print("  다음(WSL): ./Allrun.mesh && FTHX_NP=16 ./Allrun.solve")
