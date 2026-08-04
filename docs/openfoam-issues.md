# OpenFOAM 경로 — 미해결 / 결정 항목

핸드아웃 §6 형식을 따름. Fluent 경로에도 해당되는 항목은 (공통) 표시.

| # | 항목 | 상태 |
|---|---|---|
| O1 | **(공통) closure α·C2 상호배타성** — `closure.air_side()` 의 alpha 와 C2 는 각각 '단독으로' dp 전체를 재현하는 대체 폐합임 (μ·(1/α)·u·W ≡ dp, C2·W·½ρu² ≡ dp). 둘을 동시에 적용하면 구조적으로 dp 2배. OpenFOAM 실측: d+f 동시 16.0 Pa → f 단독 7.88 Pa. **OpenFOAM 은 f=C2 단독으로 확정** (`porous_df`, 테스트 고정). ⚠ Fluent 저널(`exporters.py`)은 viscous·inertial 을 둘 다 set_state 함 — M4 가 closure 와 0.03% 일치한 것은 `try_all` 이 실패를 삼켜 한쪽만 적용됐을 가능성. **Fluent 세션에서 존 속성 덤프로 실제 적용값 확인 필요.** 저유량 스윕은 Re 별 재폐합 필요 | 열림 |
| O2 | **(공통) 관 항력 이중계상** — j/f 상관식은 전체 번들(관 포함) 기준인데 형상은 관을 명시적으로도 해상 → 관 기여가 상관식과 CFD 에 각각 한 번씩 들어감. tutorial 실측: ΔP_CFD 7.88 = 포러스 4.16 + 관 항력·가속 ~3.2 + 덕트 ~0.5. 근본 해법은 멀티스케일 규약대로 주기 단위셀에서 '핀 전용' j/f 를 받는 것 — Fluent 세션의 단위셀 산출물이 나오면 그 값으로 `closure` 를 대체 | 열림 |
| O3 | probe(벤드) 확장 | **air 모드 해결** — 벤드는 덕트 z 범위 밖(z −17~117 vs 덕트 10~90)이라 공기 도메인과 무관. 배경격자는 air_bbox 그대로, 벤드 STL 은 drop. 실측 95,700셀·Mesh OK·UA 8.19 vs 예측 8.038(1.9%). cht 모드는 여전히 global_bbox 확장 필요 |
| O4 | 열전달 | **완료** — thermalBaffle 대신 externalWallHeatFluxTemperature(두께=물성). Bi=0.017. tutorial UA 3.385 vs 예측 3.349(1.1%), 39,626셀(Fluent 68,641 의 58%) |
| O5 | ΔP 교차비교 게이트 — Fluent 는 O1 확인 전이라 기준값 미확정. O1 해소 후 tutorial 동일 조건으로 Fluent↔OpenFOAM ΔP 비교 (허용오차 제안: 10%) | 대기 |
