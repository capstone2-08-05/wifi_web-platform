/**
 * AP Radio 설정 패널.
 * SimulationCanvas 위에 absolute overlay 로 표시 — AP 라벨 클릭 시 열린다.
 * key={ap.id} 로 마운트해야 AP 전환 시 state 가 올바르게 리셋된다.
 */
import { useState } from 'react';
import { X } from 'lucide-react';
import type { PlacedAp } from './SimulationCanvas';
import type { RadioInterface } from '@/types/rf';
import {
  channelToMhz,
  mhzToChannel,
  inferBandFromMhz,
  get24GChannels,
  get5GChannels,
  DEFAULT_RADIO_5G,
  DEFAULT_RADIO_24G,
} from '@/lib/wifi-channel';
import { cn } from '@/lib/utils';

type RadioMode = '5g-only' | '2.4g-only' | 'dual';

function modeFromRadios(radios: RadioInterface[]): RadioMode {
  const has5G = radios.some((r) => r.band === '5G' && r.enabled);
  const has24G = radios.some((r) => r.band === '2.4G' && r.enabled);
  if (has5G && has24G) return 'dual';
  if (has24G) return '2.4g-only';
  return '5g-only';
}

function buildRadiosFromMode(
  mode: RadioMode,
  apId: string,
  existing: RadioInterface[],
): RadioInterface[] {
  const existing5G = existing.find((r) => r.band === '5G');
  const existing24G = existing.find((r) => r.band === '2.4G');

  const radio5G: RadioInterface = existing5G ?? {
    id: `${apId}-5g`,
    ...DEFAULT_RADIO_5G,
  };
  const radio24G: RadioInterface = existing24G ?? {
    id: `${apId}-2.4g`,
    ...DEFAULT_RADIO_24G,
  };

  switch (mode) {
    case '5g-only':
      return [{ ...radio5G, enabled: true }, { ...radio24G, enabled: false }];
    case '2.4g-only':
      return [{ ...radio5G, enabled: false }, { ...radio24G, enabled: true }];
    case 'dual':
      return [{ ...radio5G, enabled: true }, { ...radio24G, enabled: true }];
  }
}

interface RadioCardProps {
  radio: RadioInterface;
  onChange: (updated: RadioInterface) => void;
}

function RadioCard({ radio, onChange }: RadioCardProps) {
  const channels = radio.band === '5G' ? get5GChannels() : get24GChannels();

  const handleChannelChange = (ch: number) => {
    const freq = channelToMhz(ch, radio.band);
    onChange({ ...radio, channel: ch, frequency_mhz: freq ?? radio.frequency_mhz });
  };

  const handleFreqChange = (raw: string) => {
    const mhz = parseInt(raw, 10);
    if (!Number.isFinite(mhz)) return;
    const ch = mhzToChannel(mhz);
    const band = inferBandFromMhz(mhz);
    onChange({
      ...radio,
      frequency_mhz: mhz,
      channel: ch ?? radio.channel,
      ...(band ? { band } : {}),
    });
  };

  const freqOutOfRange =
    radio.frequency_mhz != null &&
    inferBandFromMhz(radio.frequency_mhz) !== radio.band;

  return (
    <div className={cn('rounded-lg border p-3 text-xs', radio.enabled ? 'border-slate-200 bg-white' : 'border-slate-100 bg-slate-50 opacity-60')}>
      <div className="mb-2.5 flex items-center justify-between">
        <span className={cn('inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-bold text-white', radio.band === '5G' ? 'bg-[oklch(0.55_0.16_145)]' : 'bg-[oklch(0.60_0.15_55)]')}>
          {radio.band}
        </span>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            checked={radio.enabled}
            onChange={(e) => onChange({ ...radio, enabled: e.target.checked })}
            className="h-3.5 w-3.5 rounded accent-blue-500"
          />
          <span className="text-[11px] text-slate-600">{radio.enabled ? '활성' : '비활성'}</span>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-x-2 gap-y-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-slate-500">채널</span>
          <select
            value={radio.channel ?? ''}
            onChange={(e) => handleChannelChange(Number(e.target.value))}
            disabled={!radio.enabled}
            className="h-6 rounded border border-slate-200 bg-white px-1 text-[11px] text-slate-800 focus:border-blue-300 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="">—</option>
            {channels.map((ch) => (
              <option key={ch} value={ch}>{ch}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-slate-500">주파수 (MHz)</span>
          <input
            type="number"
            value={radio.frequency_mhz ?? ''}
            onChange={(e) => handleFreqChange(e.target.value)}
            disabled={!radio.enabled}
            className={cn(
              'h-6 rounded border bg-white px-1.5 text-[11px] tabular-nums text-slate-800 [appearance:textfield] focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 [&::-webkit-inner-spin-button]:appearance-none',
              freqOutOfRange ? 'border-amber-400 focus:border-amber-400' : 'border-slate-200 focus:border-blue-300',
            )}
          />
          {freqOutOfRange && (
            <span className="text-[10px] text-amber-600">band와 불일치</span>
          )}
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-slate-500">출력 (dBm)</span>
          <input
            type="number"
            min={0}
            max={30}
            value={radio.tx_power_dbm ?? ''}
            onChange={(e) => onChange({ ...radio, tx_power_dbm: Number(e.target.value) })}
            disabled={!radio.enabled}
            className="h-6 rounded border border-slate-200 bg-white px-1.5 text-[11px] tabular-nums text-slate-800 [appearance:textfield] focus:border-blue-300 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 [&::-webkit-inner-spin-button]:appearance-none"
          />
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-slate-500">SSID</span>
          <input
            type="text"
            value={radio.ssid ?? ''}
            onChange={(e) => onChange({ ...radio, ssid: e.target.value || undefined })}
            disabled={!radio.enabled}
            placeholder="(선택)"
            className="h-6 rounded border border-slate-200 bg-white px-1.5 text-[11px] text-slate-800 placeholder:text-slate-300 focus:border-blue-300 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
        </label>
      </div>
    </div>
  );
}

interface ApRadioPanelProps {
  ap: PlacedAp;
  onUpdateRadios: (id: string, radios: RadioInterface[]) => void;
  onClose: () => void;
}

export function ApRadioPanel({ ap, onUpdateRadios, onClose }: ApRadioPanelProps) {
  const [radios, setRadios] = useState<RadioInterface[]>(() => {
    if (ap.radios && ap.radios.length > 0) return ap.radios;
    return [{ id: `${ap.id}-5g`, ...DEFAULT_RADIO_5G }];
  });

  const mode = modeFromRadios(radios);

  const handleModeChange = (newMode: RadioMode) => {
    const updated = buildRadiosFromMode(newMode, ap.id, radios);
    setRadios(updated);
    onUpdateRadios(ap.id, updated);
  };

  const handleRadioChange = (updated: RadioInterface) => {
    const next = radios.map((r) => (r.id === updated.id ? updated : r));
    setRadios(next);
    onUpdateRadios(ap.id, next);
  };

  const modeBtnClass = (active: boolean) =>
    cn(
      'inline-flex h-7 items-center rounded-md px-2.5 text-[11px] transition-colors',
      active ? 'bg-blue-50 font-semibold text-blue-700' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
    );

  const visibleRadios = radios.filter((r) => r.band === '5G' || r.band === '2.4G');

  return (
    <div className="absolute right-2 top-2 z-20 w-64 rounded-xl border border-slate-200 bg-white shadow-lg">
      {/* header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2.5">
        <div>
          <span className="text-sm font-semibold text-slate-800">{ap.id.toUpperCase()}</span>
          <span className="ml-2 text-[11px] text-slate-400">
            ({ap.x_m.toFixed(2)}, {ap.y_m.toFixed(2)}) · z={ap.z_m.toFixed(1)}m
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          aria-label="닫기"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* radio mode */}
      <div className="border-b border-slate-100 px-3 py-2">
        <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">라디오 모드</p>
        <div className="inline-flex items-center rounded-lg bg-slate-50 p-0.5">
          <button type="button" className={modeBtnClass(mode === '5g-only')} onClick={() => handleModeChange('5g-only')}>5GHz</button>
          <button type="button" className={modeBtnClass(mode === '2.4g-only')} onClick={() => handleModeChange('2.4g-only')}>2.4GHz</button>
          <button type="button" className={modeBtnClass(mode === 'dual')} onClick={() => handleModeChange('dual')}>Dual</button>
        </div>
      </div>

      {/* radio cards */}
      <div className="space-y-2 p-3">
        {visibleRadios
          .sort((a) => (a.band === '5G' ? -1 : 1))
          .map((radio) => (
            <RadioCard key={radio.id} radio={radio} onChange={handleRadioChange} />
          ))}
      </div>

      {/* RSSI semantics hint */}
      <div className="border-t border-slate-100 px-3 py-2">
        <p className="text-[10px] leading-relaxed text-slate-400">
          커버리지는 여러 AP의 RSSI를 합산하지 않고 각 위치에서 가장 강한 AP값으로 평가합니다.
        </p>
      </div>
    </div>
  );
}
