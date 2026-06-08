"""Physical AP and Radio Interface schemas.

용어 정의:
- Physical AP: 실제로 설치/이동할 수 있는 하드웨어 장비 단위.
  x, y, z 좌표를 가지며 AP 추천의 평가 단위이다.
- Radio Interface: Physical AP 안의 송신 radio 단위.
  2.4GHz 또는 5GHz band를 가지며 Sionna RF run의 transmitter에 대응한다.

왜 band를 분리하는가:
- 2.4GHz와 5GHz는 재질 감쇠, 다중경로 특성, 전파 범위가 다르다.
- 동일 Sionna 파라미터로 두 band를 한꺼번에 시뮬하면 물리적으로 부정확하다.
- band별 calibration slope/intercept도 분리해야 한다.

RSSI 합산 금지 원칙:
- 복수 AP/radio가 같은 위치에 있어도 RSSI는 합산되지 않는다.
- cell별 coverage는 max(rssi_from_radio_1, rssi_from_radio_2, ...) 로 평가한다.
- 채널/혼잡 완화 효과는 별도 capacity/congestion 관점으로 다룬다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

BandLiteral = Literal["2.4G", "5G"]

# ─── band default frequencies ────────────────────────────────
BAND_DEFAULT_FREQ_MHZ: dict[str, int] = {
    "2.4G": 2437,  # channel 6
    "5G": 5180,    # channel 36
}

BAND_DEFAULT_FREQ_GHZ: dict[str, float] = {
    "2.4G": 2.437,
    "5G": 5.18,
}

# ─── IEEE 802.11 channel table (MHz → channel number) ────────
_CHANNEL_TABLE: dict[int, int] = {
    # 2.4GHz (802.11b/g/n)
    2412: 1, 2417: 2, 2422: 3, 2427: 4, 2432: 5,
    2437: 6, 2442: 7, 2447: 8, 2452: 9, 2457: 10,
    2462: 11, 2467: 12, 2472: 13,
    # 5GHz UNII-1
    5180: 36, 5200: 40, 5220: 44, 5240: 48,
    # UNII-2A
    5260: 52, 5280: 56, 5300: 60, 5320: 64,
    # UNII-2C
    5500: 100, 5520: 104, 5540: 108, 5560: 112,
    5580: 116, 5600: 120, 5620: 124, 5640: 128,
    5660: 132, 5680: 136, 5700: 140, 5720: 144,
    # UNII-3
    5745: 149, 5765: 153, 5785: 157, 5805: 161, 5825: 165,
}

_SAME_POSITION_TOLERANCE_M: float = 0.3


# ─── helpers ────────────────────────────────────────────────

def infer_band_from_mhz(freq_mhz: int) -> BandLiteral | None:
    """주파수(MHz)로 Wi-Fi band를 추론한다. 알 수 없으면 None."""
    if 2400 <= freq_mhz <= 2500:
        return "2.4G"
    if 4900 <= freq_mhz <= 5900:
        return "5G"
    return None


def mhz_to_channel(freq_mhz: int) -> int | None:
    """주파수(MHz)를 IEEE 802.11 채널 번호로 변환한다. 테이블에 없으면 None."""
    return _CHANNEL_TABLE.get(freq_mhz)


def ghz_to_mhz(freq_ghz: float) -> int:
    return round(freq_ghz * 1000)


# ─── schemas ────────────────────────────────────────────────

class RadioInterfaceInput(BaseModel):
    """Physical AP 내부의 송신 radio.

    radio는 자신의 좌표를 갖지 않는다 — parent Physical AP의 x, y, z를 그대로 사용한다.
    """

    id: str | None = None
    band: BandLiteral | None = None
    frequency_mhz: int | None = None
    frequency_ghz: float | None = None
    channel: int | None = None
    ssid: str | None = None
    bssid: str | None = None
    tx_power_dbm: float | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _resolve_freq_band_channel(self) -> "RadioInterfaceInput":
        # Resolve frequency_mhz ↔ frequency_ghz
        if self.frequency_mhz is None and self.frequency_ghz is not None:
            self.frequency_mhz = ghz_to_mhz(self.frequency_ghz)
        if self.frequency_ghz is None and self.frequency_mhz is not None:
            self.frequency_ghz = self.frequency_mhz / 1000.0

        # 두 값이 모두 있으면 일관성 검증 (±5 MHz 허용)
        if self.frequency_mhz is not None and self.frequency_ghz is not None:
            expected_mhz = ghz_to_mhz(self.frequency_ghz)
            if abs(self.frequency_mhz - expected_mhz) > 5:
                raise ValueError(
                    f"frequency_mhz ({self.frequency_mhz}) and frequency_ghz "
                    f"({self.frequency_ghz}) are inconsistent."
                )

        # band 추론 (frequency_mhz 기반)
        if self.band is None and self.frequency_mhz is not None:
            self.band = infer_band_from_mhz(self.frequency_mhz)

        # channel 추론 (frequency_mhz 기반)
        if self.channel is None and self.frequency_mhz is not None:
            self.channel = mhz_to_channel(self.frequency_mhz)

        return self

    def effective_frequency_ghz(self) -> float:
        """Sionna transmitter에 넣을 실효 주파수(GHz). 미지정이면 band default."""
        if self.frequency_ghz is not None:
            return self.frequency_ghz
        if self.band is not None:
            return BAND_DEFAULT_FREQ_GHZ[self.band]
        return BAND_DEFAULT_FREQ_GHZ["5G"]

    def effective_tx_power_dbm(self, fallback: float = 20.0) -> float:
        return self.tx_power_dbm if self.tx_power_dbm is not None else fallback


class PhysicalApInput(BaseModel):
    """실제 설치/이동 가능한 물리 AP 장비.

    - 하나 이상의 RadioInterfaceInput을 가진다.
    - radios가 0개면 backward-compat을 위해 default 5G radio 1개가 생성된다.
    - AP 추천에서 candidate 위치는 Physical AP 단위로 평가된다.
    - 모든 radio는 이 AP의 x, y, z 좌표를 공유한다.
    """

    id: str | None = None
    name: str | None = None
    x: float
    y: float
    z: float = Field(default=2.0)
    movable: bool = True
    radios: list[RadioInterfaceInput] = Field(default_factory=list)

    def effective_radios(self) -> list[RadioInterfaceInput]:
        """활성화된 radio 목록. 없으면 default 5G radio를 반환한다."""
        enabled = [r for r in self.radios if r.enabled]
        if enabled:
            return enabled
        # backward compat: radio 미지정 → default 5G
        ap_id = self.id or "ap"
        return [RadioInterfaceInput(id=f"{ap_id}-5g-default", band="5G")]

    def radios_for_band(self, band: BandLiteral) -> list[RadioInterfaceInput]:
        return [r for r in self.effective_radios() if r.band == band]
