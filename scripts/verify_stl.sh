#!/usr/bin/env bash
# 검증 루틴 2단계 — OpenFOAM surfaceCheck 로 STL 일괄 판정 (WSL 에서 실행)
#
# 사용:  ./scripts/verify_stl.sh out_foam            # 하위 전체 재귀
#        ./scripts/verify_stl.sh out_foam/probe      # 한 케이스만
#
# 판정 기준 (파일마다):
#   · illegal triangle 없음
#   · closed (모든 에지가 면 2개에 연결)
#   · 연결 파트 1개 (조각나지 않음)
# 셋 다 확인되면 PASS. 출력 문구를 못 찾으면 UNKNOWN 으로 표시하고
# 원문 로그 경로를 남김 — 버전에 따라 문구가 다를 수 있으므로 오판 방지.
set -u

if ! command -v surfaceCheck >/dev/null 2>&1; then
    echo "surfaceCheck 를 찾을 수 없음 — OpenFOAM 환경을 source 했는지 확인:" >&2
    echo "  source /usr/lib/openfoam/openfoam2412/etc/bashrc" >&2
    exit 2
fi

root="${1:-out_foam}"
tmp=$(mktemp -d)
pass=0; fail=0; unknown=0

while IFS= read -r -d '' f; do
    log="$tmp/$(basename "$f").log"
    surfaceCheck "$f" > "$log" 2>&1

    bad=""
    grep -qi "illegal" "$log" && ! grep -qi "no illegal" "$log" && bad+="illegal-tri "

    closed="?"
    if grep -qiE "surface is closed[?]? *1|^ *Surface is closed" "$log"; then closed=yes
    elif grep -qiE "not closed|closed[?]? *0" "$log"; then closed=no; bad+="open "
    fi

    parts=$(grep -iE "unconnected parts" "$log" | grep -oE "[0-9]+" | tail -1)
    [ -n "${parts:-}" ] && [ "$parts" != "1" ] && bad+="parts=$parts "

    name=$(basename "$f")
    if [ -n "$bad" ]; then
        echo "[FAIL] $name  ($bad)  로그: $log"; fail=$((fail+1))
    elif [ "$closed" = "?" ] && [ -z "${parts:-}" ]; then
        echo "[????] $name  판정 문구 못 찾음 — 로그 확인: $log"; unknown=$((unknown+1))
    else
        echo "[PASS] $name"; pass=$((pass+1)); rm -f "$log"
    fi
done < <(find "$root" -name '*.stl' -print0 | sort -z)

echo "──────────────────────────────"
echo "PASS $pass · FAIL $fail · UNKNOWN $unknown"
[ $fail -eq 0 ] && [ $unknown -eq 0 ] && rmdir "$tmp" 2>/dev/null
[ $fail -eq 0 ] || exit 1
