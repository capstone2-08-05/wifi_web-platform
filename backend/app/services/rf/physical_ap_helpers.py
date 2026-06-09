"""Physical AP / Radio Interface 정규화 및 band grouping 헬퍼.

이 모듈은 다음을 담당한다:
1. 기존 existing_aps (list[dict]) 를 PhysicalApInput 구조로 변환.
2. 새 physical_aps 요청을 그대로 수용.
3. band별 transmitter 그룹 생성.
4. RF run payload 빌드 시 band별 AP 분리.

coverage 계산 원칙:
- 복수 AP/radio의 RSSI는 합산하지 않는다.
- cell별 best RSSI = max(rssi_from_radio_1, rssi_from_radio_2, ...) 로 평가한다.
- 채널/혼잡 완화는 capacity/congestion 관점의 별도 작업이다 (TODO: congestion score).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from app.schemas.rf.physical_ap import (
    BAND_DEFAULT_FREQ_GHZ,
    BandLiteral,
    PhysicalApInput,
    RadioInterfaceInput,
    _SAME_POSITION_TOLERANCE_M,
    infer_band_from_mhz,
)

logger = logging.getLogger(__name__)

_SAME_POSITION_TOL = _SAME_POSITION_TOLERANCE_M


# ─── internal transmitter DTO ─────────────────────────────────

@dataclass
class RadioTransmitter:
    """Sionna RF run에 넣을 단일 transmitter.

    physical_ap_id, radio_id를 유지해 결과 metadata에 매칭할 수 있게 한다.
    """
    id: str
    physical_ap_id: str
    radio_id: str | None
    band: BandLiteral
    x: float
    y: float
    z: float
    frequency_ghz: float
    tx_power_dbm: float
    ssid: str | None = None
    bssid: str | None = None
    channel: int | None = None


# ─── normalize ───────────────────────────────────────────────

def normalize_physical_aps_from_request(
    *,
    physical_aps: list[PhysicalApInput] | None,
    existing_aps: list[dict[str, Any]] | None,
    candidate_tx_power_dbm: float = 20.0,
) -> list[PhysicalApInput]:
    """요청에서 Physical AP 목록을 반환한다.

    우선순위:
    1. physical_aps가 있으면 그대로 사용.
    2. 없으면 existing_aps를 PhysicalApInput으로 변환 (legacy compat).
    """
    if physical_aps:
        return physical_aps
    return _legacy_existing_aps_to_physical(
        existing_aps or [],
        fallback_tx_power_dbm=candidate_tx_power_dbm,
    )


def _legacy_existing_aps_to_physical(
    raw: list[dict[str, Any]],
    fallback_tx_power_dbm: float = 20.0,
) -> list[PhysicalApInput]:
    """기존 existing_aps dict list를 PhysicalApInput list로 변환한다.

    처리 규칙:
    - physical_ap_id가 같은 항목은 하나의 Physical AP로 묶어 radios에 추가한다.
    - physical_ap_id가 없고 좌표가 매우 가까우면 (< 0.3m) 같은 AP로 병합한다
      (단, 자동 병합은 warning을 남기고 보수적으로 처리한다).
    - x, y가 없는 항목은 건너뛴다.
    """
    # physical_ap_id로 먼저 그룹핑
    groups: dict[str, list[dict[str, Any]]] = {}
    ungrouped: list[dict[str, Any]] = []

    for item in raw:
        phys_id = item.get("physical_ap_id")
        if phys_id:
            groups.setdefault(str(phys_id), []).append(item)
        else:
            ungrouped.append(item)

    result: list[PhysicalApInput] = []

    # physical_ap_id 기반 그룹 변환
    for phys_id, items in groups.items():
        anchor = items[0]
        x = _coerce_float(anchor.get("x_m") if anchor.get("x_m") is not None else anchor.get("x"))
        y = _coerce_float(anchor.get("y_m") if anchor.get("y_m") is not None else anchor.get("y"))
        if x is None or y is None:
            continue
        _z_raw = anchor.get("z_m") if anchor.get("z_m") is not None else anchor.get("z")
        z = _coerce_float(_z_raw) if _z_raw is not None else 2.0
        radios = [_item_to_radio(it, i, fallback_tx_power_dbm) for i, it in enumerate(items)]
        result.append(
            PhysicalApInput(
                id=phys_id,
                name=anchor.get("name") or phys_id,
                x=x,
                y=y,
                z=z,
                radios=radios,
            )
        )

    # physical_ap_id 없는 항목: 좌표 근접 자동 병합 (보수적)
    merged_indices: set[int] = set()
    ungrouped_aps: list[PhysicalApInput] = []
    for i, item in enumerate(ungrouped):
        if i in merged_indices:
            continue
        x = _coerce_float(item.get("x_m") if item.get("x_m") is not None else item.get("x"))
        y = _coerce_float(item.get("y_m") if item.get("y_m") is not None else item.get("y"))
        if x is None or y is None:
            continue
        _z_raw = item.get("z_m") if item.get("z_m") is not None else item.get("z")
        z = _coerce_float(_z_raw) if _z_raw is not None else 2.0
        ap_id = str(item.get("id") or item.get("name") or f"ap{i + 1}")
        radios = [_item_to_radio(item, 0, fallback_tx_power_dbm)]

        # 근접 항목 병합 (같은 물리 AP의 다른 band로 간주)
        for j, other in enumerate(ungrouped):
            if j <= i or j in merged_indices:
                continue
            ox = _coerce_float(other.get("x_m") if other.get("x_m") is not None else other.get("x"))
            oy = _coerce_float(other.get("y_m") if other.get("y_m") is not None else other.get("y"))
            if ox is None or oy is None:
                continue
            dist = math.hypot(ox - x, oy - y)
            if dist < _SAME_POSITION_TOL:
                logger.warning(
                    "physical_ap_helpers: AP items %d and %d are %.3fm apart (<%.1fm) — "
                    "auto-merging as same physical AP '%s'. Set physical_ap_id to suppress.",
                    i, j, dist, _SAME_POSITION_TOL, ap_id,
                )
                radios.append(_item_to_radio(other, len(radios), fallback_tx_power_dbm))
                merged_indices.add(j)

        ungrouped_aps.append(
            PhysicalApInput(
                id=ap_id,
                name=item.get("name") or ap_id,
                x=x,
                y=y,
                z=z,
                radios=radios,
            )
        )

    return result + ungrouped_aps


def _item_to_radio(
    item: dict[str, Any],
    idx: int,
    fallback_tx_power_dbm: float,
) -> RadioInterfaceInput:
    """existing_aps 항목 하나를 RadioInterfaceInput으로 변환한다."""
    freq_mhz = item.get("frequency_mhz")
    freq_ghz = item.get("frequency_ghz")
    band_raw = item.get("band")
    band: BandLiteral | None = None
    if band_raw in ("2.4G", "5G"):
        band = band_raw  # type: ignore[assignment]
    elif freq_mhz:
        band = infer_band_from_mhz(int(freq_mhz))
    if band is None:
        band = "5G"  # legacy item에 band/frequency 정보 없으면 5G 기본

    radio_id = item.get("radio_id") or item.get("id")
    if radio_id and idx > 0:
        radio_id = f"{radio_id}-radio{idx}"

    return RadioInterfaceInput(
        id=str(radio_id) if radio_id else None,
        band=band,
        frequency_mhz=int(freq_mhz) if freq_mhz is not None else None,
        frequency_ghz=float(freq_ghz) if freq_ghz is not None else None,
        channel=item.get("channel"),
        ssid=item.get("ssid"),
        bssid=item.get("bssid"),
        tx_power_dbm=next(
            (v for v in (_coerce_float(item.get("tx_power_dbm")), _coerce_float(item.get("power_dbm"))) if v is not None),
            fallback_tx_power_dbm,
        ),
    )


# ─── band grouping ────────────────────────────────────────────

def group_radios_by_band(
    physical_aps: list[PhysicalApInput],
) -> dict[BandLiteral, list[RadioTransmitter]]:
    """Physical AP 목록에서 band별 RadioTransmitter 그룹을 만든다.

    - 2.4G radio → "2.4G" 그룹
    - 5G radio   → "5G" 그룹
    - band 미지정 radio는 "5G" 그룹으로 fallback (경고 출력)

    각 transmitter는 parent physical AP의 x, y, z를 그대로 사용한다.
    """
    bands: dict[BandLiteral, list[RadioTransmitter]] = {"2.4G": [], "5G": []}

    for ap in physical_aps:
        ap_id = ap.id or f"ap_{id(ap)}"
        for radio in ap.effective_radios():
            effective_band: BandLiteral = radio.band or "5G"
            if radio.band is None:
                logger.warning(
                    "Radio %s on AP %s has no band — defaulting to 5G.",
                    radio.id, ap_id,
                )
            tx = RadioTransmitter(
                id=f"{ap_id}-{radio.id or effective_band}",
                physical_ap_id=ap_id,
                radio_id=radio.id,
                band=effective_band,
                x=ap.x,
                y=ap.y,
                z=ap.z,
                frequency_ghz=radio.effective_frequency_ghz(),
                tx_power_dbm=radio.effective_tx_power_dbm(fallback=20.0),
                ssid=radio.ssid,
                bssid=radio.bssid,
                channel=radio.channel,
            )
            bands[effective_band].append(tx)

    return bands


def build_band_metadata(
    physical_aps: list[PhysicalApInput],
    bands_used: list[BandLiteral] | None = None,
) -> dict[str, Any]:
    """RF run 결과 metadata에 포함할 band별 정보를 빌드한다."""
    grouped = group_radios_by_band(physical_aps)
    active_bands: list[BandLiteral] = bands_used or ["5G", "2.4G"]
    out: dict[str, Any] = {}
    for band in active_bands:
        txs = grouped.get(band, [])
        out[band] = {
            "frequency_ghz": BAND_DEFAULT_FREQ_GHZ[band],
            "radio_ids": [tx.radio_id for tx in txs],
            "physical_ap_ids": sorted({tx.physical_ap_id for tx in txs}),
            "transmitter_count": len(txs),
            "calibration_applied": False,  # TODO: band별 calibration 분리 후 갱신
        }
    return out


def physical_aps_to_access_point_list(
    physical_aps: list[PhysicalApInput],
    band: BandLiteral | None = None,
    fallback_tx_power_dbm: float = 20.0,
) -> list[dict[str, Any]]:
    """PhysicalApInput list를 rf_backend_local / SageMaker 호환 access_point dict list로 변환.

    band가 None이면 첫 번째 radio (또는 default 5G)를 사용한다.
    band가 지정되면 해당 band radio만 포함한다.
    """
    result: list[dict[str, Any]] = []
    grouped = group_radios_by_band(physical_aps)

    if band is not None:
        for tx in grouped.get(band, []):
            result.append({
                "id": tx.id,
                "x_m": tx.x,
                "y_m": tx.y,
                "z_m": tx.z,
                "frequency_ghz": tx.frequency_ghz,
                "tx_power_dbm": tx.tx_power_dbm,
                "channel": tx.channel,
                "ssid": tx.ssid,
                "bssid": tx.bssid,
                "band": tx.band,
                "physical_ap_id": tx.physical_ap_id,
                "radio_id": tx.radio_id,
            })
    else:
        # band 미지정: AP별로 첫 번째 radio 사용 (legacy single-band 호환)
        for ap in physical_aps:
            radios = ap.effective_radios()
            if not radios:
                continue
            radio = radios[0]
            ap_id = ap.id or f"ap_{id(ap)}"
            result.append({
                "id": ap_id,
                "x_m": ap.x,
                "y_m": ap.y,
                "z_m": ap.z,
                "frequency_ghz": radio.effective_frequency_ghz(),
                "tx_power_dbm": radio.effective_tx_power_dbm(fallback_tx_power_dbm),
                "channel": radio.channel,
                "ssid": radio.ssid,
                "bssid": radio.bssid,
                "band": radio.band or "5G",
                "physical_ap_id": ap_id,
                "radio_id": radio.id,
            })
    return result


# ─── RSSI merge semantics ─────────────────────────────────────

def merge_rssi_max_per_cell(rssi_values: list[float]) -> float:
    """여러 AP/radio의 RSSI를 cell별 max로 병합한다.

    올바른 coverage 계산 원칙:
    - RSSI dBm 값을 단순 합산하지 않는다.
    - 같은 위치에 AP가 여러 대 있다고 coverage가 2배 강해지는 것이 아니다.
    - 채널/혼잡 완화 효과는 별도 capacity/congestion 관점으로 다룬다.

    Args:
        rssi_values: 같은 cell에서 여러 radio가 예측한 RSSI(dBm) 목록.

    Returns:
        그 중 가장 강한 (숫자가 큰) RSSI 값.
    """
    if not rssi_values:
        return float("-inf")
    return max(rssi_values)


# ─── internal utils ───────────────────────────────────────────

def _coerce_float(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None
