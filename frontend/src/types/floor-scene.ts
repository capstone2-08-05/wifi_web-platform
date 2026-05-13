// 캔버스 시각화용 클라이언트 타입.
// 백엔드 GET /scene-versions/{id} 등의 응답이 도형 컬럼을 노출하기 시작하면,
// 그쪽 GeoJSON → 이 모양으로 매핑하는 adapter 만 추가하면 됨.

export interface FloorRoom {
  id: string;
  label: string;
  /** 좌상단 기준 사각형. 추후 polygon 지원 시 별도 필드 추가 가능. */
  x: number;
  y: number;
  width: number;
  height: number;
}

export type FloorObjectShape = 'circle' | 'rect';

export interface FloorObject {
  id: string;
  label: string;
  shape: FloorObjectShape;
  /** shape === 'circle' 일 때 사용 */
  cx?: number;
  cy?: number;
  r?: number;
  /** shape === 'rect' 일 때 사용 */
  x?: number;
  y?: number;
  width?: number;
  height?: number;
}

export type ApTone = 'primary' | 'indigo';

export interface FloorAp {
  id: string;
  label: string;
  cx: number;
  cy: number;
  /** 일반 AP (primary) / 고성능 AP (indigo) */
  tone?: ApTone;
}

export interface FloorScene {
  viewBox: { width: number; height: number };
  rooms: FloorRoom[];
  objects: FloorObject[];
  aps: FloorAp[];
  /** 캔버스에서 현재 선택된 객체 id (없으면 null) */
  selectedObjectId?: string | null;
}

// 히트맵 영역 (시뮬레이션/실측 공용)
export type HeatmapIntensity = 'good' | 'warn' | 'bad';

export interface HeatmapRegion {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  intensity: HeatmapIntensity;
}
