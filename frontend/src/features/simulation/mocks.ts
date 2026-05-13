import type { FloorScene, HeatmapRegion } from '@/types/floor-scene';
import type { SimulationHistoryItem } from './SimulationHistory';

// 백엔드: §13 RF Run 응답 + (도면 노출 후) Scene Version → 매핑 예정.
export const MOCK_SIMULATION_FLOOR_SCENE: FloorScene = {
  viewBox: { width: 800, height: 520 },
  rooms: [
    { id: 'room-kitchen', label: '주방 / 카운터', x: 100, y: 140, width: 160, height: 100 },
    { id: 'room-storage', label: '창고', x: 100, y: 280, width: 160, height: 100 },
  ],
  objects: [
    { id: 'obj-table-1', label: '테이블', shape: 'circle', cx: 600, cy: 190, r: 42 },
    { id: 'obj-table-2', label: '테이블', shape: 'circle', cx: 380, cy: 380, r: 38 },
    { id: 'obj-group', label: '단체석', shape: 'rect', x: 610, y: 370, width: 90, height: 48 },
    { id: 'obj-selected', label: '', shape: 'rect', x: 440, y: 290, width: 140, height: 80 },
  ],
  aps: [
    { id: 'ap-1', label: 'AP 1', cx: 430, cy: 190, tone: 'primary' },
    { id: 'ap-2', label: 'AP 2', cx: 685, cy: 465, tone: 'primary' },
  ],
  selectedObjectId: 'obj-selected',
};

// 시뮬레이션 완료 시 보여줄 히트맵.
// 백엔드: §13.3 GET /rf-runs/{id}/maps 로 받은 RSSI 맵을 region 으로 변환 예정.
export const MOCK_SIMULATION_HEATMAP: HeatmapRegion[] = [
  { cx: 500, cy: 280, rx: 280, ry: 200, intensity: 'good' },
  { cx: 600, cy: 200, rx: 160, ry: 120, intensity: 'good' },
  { cx: 170, cy: 400, rx: 160, ry: 130, intensity: 'bad' },
  { cx: 540, cy: 380, rx: 80, ry: 60, intensity: 'warn' },
];

// 시뮬레이션 기록 — 백엔드: GET /jobs?job_type=rf_run + RF Run metrics 결합 예정.
export const MOCK_SIMULATION_HISTORY_BASE: SimulationHistoryItem[] = [
  {
    id: 'sim-base',
    label: '초기 배치 (어제)',
    timeLabel: '14:20',
    avgRssiDbm: -72,
    coveragePercent: 65,
  },
];

export const MOCK_SIMULATION_NEW_RESULT: SimulationHistoryItem = {
  id: 'sim-new',
  label: '새로운 가구 배치 (방금 전)',
  timeLabel: '오후 02:18',
  avgRssiDbm: -62,
  coveragePercent: 85,
  active: true,
};
