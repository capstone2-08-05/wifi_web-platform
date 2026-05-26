"""RF 시뮬레이션 디폴트 하이퍼파라미터 — 한 곳에서 조정.

`RfSimulationParams` (요청 스키마) 의 Field default 가 이 모듈의 상수를 참조.
프론트엔드가 안 보내는 모든 필드가 여기 값으로 채워진다.

## 설계 의도

- **5GHz 실내 Wi-Fi 기준** (project memory: 5GHz/20dBm/refraction=true 의도)
- **CPU dev 빠른 preview** 가 1차 — max_depth/samples 는 약간 보수적
- ai_api `SimulationConfig` 디폴트와 일관성 유지 (불일치 시 web-platform 값이 강제)

## 정확도 ↑ 가 필요하면 (예: 논문/시연용)

```python
DEFAULT_MAX_DEPTH = 6              # 3 → 6  (반사 더 깊게)
DEFAULT_SAMPLES_PER_TX = 500_000   # 100k → 500k (Sionna 권장)
DEFAULT_RESOLUTION_M = 0.25        # 0.5 → 0.25 (셀 4배)
```

각각 CPU 에서 분 단위 → 십분대로 늘 수 있음. GPU 환경이면 부담 적음.

## 디폴트 ↔ ai_api SimulationConfig 매핑

| 여기 (web-platform)         | ai_api 도메인                              |
|---------------------------- |-------------------------------------------|
| DEFAULT_FREQUENCY_HZ        | PhysicalConfig.frequency_ghz × 1e9         |
| DEFAULT_TX_POWER_DBM        | PhysicalConfig.tx_power_dbm               |
| DEFAULT_MAX_DEPTH           | SolverConfig.max_depth                     |
| DEFAULT_SAMPLES_PER_TX      | SolverConfig.samples_per_tx                |
| DEFAULT_SEED                | SolverConfig.seed                          |

(propagation: los/specular/refraction true, diffuse/diffraction false 는 ai_api 쪽에서 결정)
"""
from __future__ import annotations

# ============================================================
# 물리값 — 결과의 의미를 결정 (사용자가 UI 에서 바꿀 만한 값)
# ============================================================
# Wi-Fi 5 / 6 (5GHz band). 2.4GHz 가 필요하면 요청에서 override.
DEFAULT_FREQUENCY_HZ: float = 5.0e9

# 일반 indoor AP (~100mW). FCC indoor 5GHz 상한 30dBm/1W.
DEFAULT_TX_POWER_DBM: float = 20.0


# ============================================================
# 측정 grid — 결과 해상도
# ============================================================
# 0.5m × 0.5m 셀. 0.25 로 낮추면 grid 4배 → CPU 시간 ~4배.
DEFAULT_RESOLUTION_M: float = 0.25

# 측정면 높이 (m). 1.0 = 책상/허리, 1.2~1.5 = 핸드폰 사용 평균.
DEFAULT_MEASUREMENT_PLANE_Z_M: float = 1.0


# ============================================================
# Sionna RT solver — 속도 vs 정확도 트레이드오프
# ============================================================
# Ray 추적 최대 반사 횟수. 3 = direct + 3 bounce (CPU 빠른 preview).
# Sionna 권장 5~6. 실내 다중경로 중요한 환경에선 5 이상 권장.
DEFAULT_MAX_DEPTH: int = 6

# TX 당 ray 수. 100k = CPU 수십초. 500k = Sionna 권장, CPU 분 단위.
# 적으면 RSSI 가 노이지 (값이 cell 간 들쭉날쭉).
DEFAULT_SAMPLES_PER_TX: int = 500_000

# Monte Carlo 시드 — 재현성용.
DEFAULT_SEED: int = 42
