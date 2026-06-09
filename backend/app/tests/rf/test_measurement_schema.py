from app.schemas.rf.measurement import MeasurementPointInputDTO
from app.services.rf.measurement_service import _measurement_point_metadata


def test_android_measurement_point_accepts_channel_observation_fields():
    point = MeasurementPointInputDTO.model_validate(
        {
            "client_point_id": "p-1",
            "floor_position": {"x": 1.0, "y": 2.0, "z": 1.2},
            "rssi_dbm": -61,
            "sinrDb": 23.5,
            "latencyMs": 14.2,
            "throughputMbps": 312.8,
            "ap_bssid": "aa:bb:cc:dd:ee:ff",
            "ap_ssid": "Office WiFi",
            "channel": 6,
            "frequencyMhz": 2437,
            "channelWidthMhz": 20,
            "linkSpeedMbps": 433,
            "wifiStandard": "802.11ac",
            "wifiScanResults": [
                {
                    "bssid": "aa:bb:cc:dd:ee:ff",
                    "ssid": "Office WiFi",
                    "level": -61,
                    "channel": 6,
                    "frequency": 2437,
                    "channelWidth": 20,
                },
                {
                    "bssid": "11:22:33:44:55:66",
                    "ssid": "Neighbor",
                    "rssiDbm": -72,
                    "channel": 7,
                    "frequencyMhz": 2442,
                },
            ],
        }
    )

    assert point.sinr_db == 23.5
    assert point.latency_ms == 14.2
    assert point.throughput_mbps == 312.8
    assert point.frequency_mhz == 2437
    assert point.channel_width_mhz == 20
    assert point.link_speed_mbps == 433
    assert point.wifi_scan_results[0].rssi_dbm == -61

    metadata = _measurement_point_metadata(point)
    observation = metadata["channel_observation"]
    assert observation["connected_ap"]["channel"] == 6
    assert observation["connected_ap"]["wifi_standard"] == "802.11ac"
    assert observation["scan_result_count"] == 2
    assert observation["same_channel_count"] == 1
    assert observation["adjacent_channel_count"] == 1
