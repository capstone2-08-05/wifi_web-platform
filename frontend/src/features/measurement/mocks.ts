import type { FloorScene, HeatmapRegion } from '@/types/floor-scene';

// 백엔드 §10 측정 도메인이 GET 엔드포인트를 구현하면 이쪽 mock 을 useQuery 로 대체.

export type MeasurementSeverity = 'good' | 'warning' | 'bad';

export interface MeasurementPoint {
  id: string;
  x: number;
  y: number;
  severity: MeasurementSeverity;
}

// 선택된 측정 포인트에 대한 진단 (현재 명세에 별도 엔드포인트 없음 — 백엔드와 협의 필요).
export interface PointDiagnosis {
  pointLabel: string;
  pointCode: string;
  severity: MeasurementSeverity;
  predictedRssiDbm: number;
  measuredRssiDbm: number;
  measuredAtLabel: string;
  latencyMs: number;
  downloadMbps: number;
  bandLabel: string;
  causeText: string;
}

export const MOCK_MEASUREMENT_FLOOR_SCENE: FloorScene = {
  viewBox: { width: 800, height: 520 },
  rooms: [
    { id: 'room-kitchen', label: '주방 / 카운터', x: 100, y: 140, width: 160, height: 100 },
    { id: 'room-storage', label: '창고', x: 100, y: 280, width: 160, height: 100 },
  ],
  objects: [
    { id: 'obj-table-1', label: '테이블', shape: 'circle', cx: 600, cy: 190, r: 42 },
    { id: 'obj-table-2', label: '테이블', shape: 'circle', cx: 380, cy: 380, r: 38 },
    { id: 'obj-group', label: '단체석', shape: 'rect', x: 610, y: 370, width: 90, height: 48 },
  ],
  aps: [
    { id: 'ap-1', label: 'AP 1', cx: 430, cy: 190, tone: 'primary' },
    { id: 'ap-2', label: 'AP 2', cx: 685, cy: 465, tone: 'primary' },
  ],
};

// 측정 경로의 포인트 시퀀스. 백엔드: GET /measurement-sessions/{id}/points (§10.4, 미구현).
export const MOCK_MEASUREMENT_POINTS: MeasurementPoint[] = [
  { id: 'P-01', x: 420, y: 180, severity: 'good' },
  { id: 'P-02', x: 510, y: 180, severity: 'good' },
  { id: 'P-03', x: 510, y: 280, severity: 'good' },
  { id: 'P-04', x: 320, y: 280, severity: 'good' },
  { id: 'P-05', x: 320, y: 380, severity: 'bad' },
  { id: 'P-06', x: 510, y: 340, severity: 'warning' },
  { id: 'P-07', x: 640, y: 340, severity: 'good' },
  { id: 'P-08', x: 640, y: 440, severity: 'good' },
];

// 히트맵 영역 (실측 데이터를 그라데이션으로 변환한 결과).
export const MOCK_MEASUREMENT_HEATMAP: HeatmapRegion[] = [
  { cx: 480, cy: 270, rx: 260, ry: 190, intensity: 'good' },
  { cx: 540, cy: 340, rx: 100, ry: 70, intensity: 'warn' },
  { cx: 180, cy: 400, rx: 140, ry: 110, intensity: 'bad' },
];

export const MOCK_POINT_DIAGNOSIS: PointDiagnosis = {
  pointLabel: '창고 앞 구석',
  pointCode: 'P-05',
  severity: 'bad',
  predictedRssiDbm: -72,
  measuredRssiDbm: -84,
  measuredAtLabel: '어제 15:00',
  latencyMs: 55,
  downloadMbps: 4.2,
  bandLabel: '2.4GHz',
  causeText:
    '예측보다 실측 수치가 훨씬 낮습니다. 창고 가벽의 전파 흡수율이 예상보다 높거나, 주변에 전파 간섭을 일으키는 금속성 물체가 있을 수 있습니다.',
};
