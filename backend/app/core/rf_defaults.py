"""RF 시뮬레이션 디폴트 하이퍼파라미터 — **유일한 source of truth**.

이 모듈만 보면 시뮬 동작이 결정된다. 다른 어디에 디폴트 박지 말 것:
  - frontend `SimulationPage.tsx` 는 `simulation: {}` 빈 객체 전송 (override 안 함)
  - web-platform `RfSimulationParams` 디폴트 가 여길 import 해서 채움
  - ai_api 호출 페이로드 빌더 (`rf_backend_local._build_sionna_request_payload`) 가
    여기 값을 명시적으로 모두 보냄 → ai_api `SimulationConfig` 디폴트는 fallback 일 뿐

## ai_api `SimulationConfig` 와의 관계

ai_api 의 `simulation_config.py` 의 디폴트들은 **/internal/sionna/run 을 직접 호출하는
다른 클라이언트** (테스트/CLI 등) 용 fallback. web-platform 경로에선 이 파일의 값이 강제.
혼선 방지 위해 두 파일은 **같은 값으로 유지** 권장.

## 정확도 ↑ vs 속도 ↑ 가이드

| 효과 큼순 | 변수 | 빠름값 | 정확값 | 비고 |
|----|----|----|----|----|
| 1 | `DEFAULT_DIFFRACTION`        | False | True   | 가장자리 회절. 켜면 ×2~10 느림 |
| 2 | `DEFAULT_DIFFUSE_REFLECTION` | False | True   | 거친 표면 산란. 켜면 ×5~50 |
| 3 | `DEFAULT_SAMPLES_PER_TX`     | 100k  | 2M+    | ray 수. 선형 |
| 4 | `DEFAULT_RESOLUTION_M`       | 0.5   | 0.1    | grid 셀. 면적 inverse-square |
| 5 | `DEFAULT_MAX_DEPTH`          | 3     | 10+    | bounce 깊이. 대부분 ray 가 일찍 죽어서 효과 제한적 |
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
# Propagation mechanisms — 어떤 전파 메커니즘을 모델링할지
# ============================================================
# 직접 시선 path. 끄면 RX 가 AP 를 직접 못 봄 (벽 너머만 시뮬).
DEFAULT_LOS: bool = True

# 벽 거울 반사. 끄면 multipath 거의 사라짐.
DEFAULT_SPECULAR_REFLECTION: bool = True

# 매질 통과 (벽 안 흡수 + 굴절). 실내 시뮬에 중요.
DEFAULT_REFRACTION: bool = True

# 거친 표면 산란 — Monte Carlo 서브샘플링 발생. 켜면 ×5~50 느려짐.
# 실내에선 효과 작아서 보통 False, 정확도 ↑ 시연시 True.
DEFAULT_DIFFUSE_REFLECTION: bool = True

# 가장자리 회절 — edge detection 비용 ↑↑. 켜면 ×2~10 느려짐.
# 구석/문틈 신호 누설 정확하게 잡으려면 True. 빠른 preview 면 False.
DEFAULT_DIFFRACTION: bool = True


# ============================================================
# Sionna RT solver — 속도 vs 정확도 트레이드오프
# ============================================================
# Ray 추적 최대 반사 횟수. 3 = direct + 3 bounce (CPU 빠른 preview).
# Sionna 권장 5~6. 실내 다중경로 중요한 환경에선 5 이상 권장.
DEFAULT_MAX_DEPTH: int = 10

# TX 당 ray 수. 100k = CPU 수십초. 500k = Sionna 권장, CPU 분 단위.
# 적으면 RSSI 가 노이지 (값이 cell 간 들쭉날쭉).
DEFAULT_SAMPLES_PER_TX: int = 500_000

# Monte Carlo 시드 — 재현성용.
DEFAULT_SEED: int = 42
