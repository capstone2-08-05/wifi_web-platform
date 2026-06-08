/**
 * IEEE 802.11 channel ↔ frequency 매핑 + band 추론 헬퍼.
 * 백엔드 physical_ap.py 의 mhz_to_channel / infer_band_from_mhz 와 동일 로직.
 */

export type WifiBand = '2.4G' | '5G';

const CHANNEL_MHZ_24G: Record<number, number> = {
  1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432,
  6: 2437, 7: 2442, 8: 2447, 9: 2452, 10: 2457, 11: 2462,
};

const CHANNEL_MHZ_5G: Record<number, number> = {
  36: 5180, 40: 5200, 44: 5220, 48: 5240,
  149: 5745, 153: 5765, 157: 5785, 161: 5805,
};

const MHZ_CHANNEL_24G = Object.fromEntries(
  Object.entries(CHANNEL_MHZ_24G).map(([c, m]) => [m, Number(c)]),
) as Record<number, number>;

const MHZ_CHANNEL_5G = Object.fromEntries(
  Object.entries(CHANNEL_MHZ_5G).map(([c, m]) => [m, Number(c)]),
) as Record<number, number>;

export function inferBandFromMhz(mhz: number): WifiBand | null {
  if (mhz >= 2400 && mhz <= 2500) return '2.4G';
  if (mhz >= 4900 && mhz <= 5900) return '5G';
  return null;
}

export function mhzToChannel(mhz: number): number | null {
  return MHZ_CHANNEL_24G[mhz] ?? MHZ_CHANNEL_5G[mhz] ?? null;
}

export function channelToMhz(channel: number, band: WifiBand): number | null {
  if (band === '2.4G') return CHANNEL_MHZ_24G[channel] ?? null;
  return CHANNEL_MHZ_5G[channel] ?? null;
}

export function get24GChannels(): number[] {
  return Object.keys(CHANNEL_MHZ_24G).map(Number).sort((a, b) => a - b);
}

export function get5GChannels(): number[] {
  return Object.keys(CHANNEL_MHZ_5G).map(Number).sort((a, b) => a - b);
}

export const DEFAULT_RADIO_5G = {
  band: '5G' as WifiBand,
  frequency_mhz: 5180,
  channel: 36,
  tx_power_dbm: 20,
  enabled: true,
} as const;

export const DEFAULT_RADIO_24G = {
  band: '2.4G' as WifiBand,
  frequency_mhz: 2437,
  channel: 6,
  tx_power_dbm: 18,
  enabled: true,
} as const;
