"""O5 — Fluent ↔ OpenFOAM 교차비교.

두 경로가 core 의 `fthx.post` 스키마를 공유하므로 results.csv 를 그대로
맞대면 됨. 형상·운전조건 열로 행을 짝지어 지표 차이를 낸다.

  python scripts/compare_paths.py <fluent.csv> <openfoam.csv> [출력.csv]
"""
import csv
import sys
from pathlib import Path

KEY = ["case", "Nr", "Nt", "FPI", "fin_type", "Pt_mm", "Pl_mm",
       "V_face_ms", "T_air_in_C", "T_sat_C"]
CMP = ["dP_air_Pa", "Q_W", "UA_W_K", "effectiveness", "NTU", "LMTD_K"]


def load(p):
    rows = list(csv.DictReader(Path(p).expanduser().open(encoding="utf-8")))
    out = {}
    for r in rows:
        k = tuple(r.get(c, "") for c in KEY)
        out[k] = r                      # 같은 조건이 여러 번이면 마지막 것
    return out


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main(a):
    if len(a) < 2:
        print(__doc__)
        return 2
    F, O = load(a[0]), load(a[1])
    common = [k for k in F if k in O]
    print(f"Fluent {len(F)}행 · OpenFOAM {len(O)}행 · 공통 조건 {len(common)}건")
    if not common:
        print("\n짝지을 조건이 없음. 두 CSV 의 다음 열이 일치해야 함:")
        print("  " + ", ".join(KEY))
        for tag, d in (("Fluent", F), ("OpenFOAM", O)):
            if d:
                print(f"  {tag} 예: {dict(zip(KEY, next(iter(d))))}")
        return 1

    rows = []
    print(f"\n{'조건':28s} {'지표':14s} {'Fluent':>10s} {'OpenFOAM':>10s} {'차이%':>8s}")
    for k in common:
        label = f"{k[0]}/V{k[7]}/FPI{k[3]}"[:28]
        for c in CMP:
            f, o = num(F[k].get(c)), num(O[k].get(c))
            if f is None or o is None or f == 0:
                continue
            d = (o - f) / abs(f) * 100.0
            rows.append({"조건": label, "지표": c, "fluent": f,
                         "openfoam": o, "diff_pct": round(d, 2)})
            print(f"{label:28s} {c:14s} {f:10.4g} {o:10.4g} {d:+8.1f}")

    if len(a) > 2 and rows:
        out = Path(a[2]).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\n→ {out}")
    if rows:
        big = [r for r in rows if abs(r["diff_pct"]) > 15]
        print(f"\n15% 초과 항목 {len(big)}/{len(rows)}")
        for r in big[:10]:
            print(f"  {r['조건']} {r['지표']} {r['diff_pct']:+.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
