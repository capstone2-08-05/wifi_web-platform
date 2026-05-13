import type { FloorScene } from '@/types/floor-scene';

// 백엔드 GET /scene-versions/{id} (도형 노출 후) 로 교체될 예정.
export const MOCK_DASHBOARD_FLOOR_SCENE: FloorScene = {
  viewBox: { width: 800, height: 500 },
  rooms: [
    { id: 'room-kitchen', label: '주방 / 카운터', x: 100, y: 120, width: 160, height: 120 },
    { id: 'room-storage', label: '창고', x: 100, y: 280, width: 160, height: 120 },
  ],
  objects: [
    { id: 'obj-table-1', label: '테이블', shape: 'circle', cx: 600, cy: 170, r: 44 },
    { id: 'obj-table-2', label: '테이블', shape: 'circle', cx: 370, cy: 340, r: 40 },
    { id: 'obj-group', label: '단체석', shape: 'rect', x: 620, y: 320, width: 100, height: 50 },
    { id: 'obj-selected', label: '', shape: 'rect', x: 440, y: 290, width: 140, height: 80 },
  ],
  aps: [
    { id: 'ap-1', label: 'AP 1', cx: 430, cy: 170, tone: 'primary' },
    { id: 'ap-2', label: 'AP 2', cx: 680, cy: 420, tone: 'primary' },
  ],
  selectedObjectId: 'obj-selected',
};

// 백엔드 진단 엔드포인트는 명세에 없음. 추후 별도 협의 필요.
import type { Diagnostic } from './DiagnosticsList';

export const MOCK_DIAGNOSTICS: Diagnostic[] = [
  {
    id: 'd-1',
    location: '창고 앞 구석 테이블',
    timeLabel: '방금 전',
    severity: 'critical',
    statusText: '신호 끊김 (-85dBm)',
    description: '고객 클레임 다수 발생 구역. 철제 수납장 영향 의심됨.',
  },
  {
    id: 'd-2',
    location: '카운터 포스기 주변',
    timeLabel: '2시간 전',
    severity: 'warning',
    statusText: '간헐적 속도 저하',
    description: '결제 시 지연 발생. 채널 간섭 확인 필요.',
  },
  {
    id: 'd-3',
    location: '메인 홀 중앙',
    timeLabel: '어제',
    severity: 'good',
    statusText: '양호 (-45dBm)',
    description: '특이사항 없음. 정상 서비스 중.',
  },
  {
    id: 'd-4',
    location: '화장실 앞 복도',
    timeLabel: '3일 전',
    severity: 'weak',
    statusText: '신호 약함 (-72dBm)',
    description: '콘크리트 벽체 영향으로 보임. 사용상 큰 무리는 없음.',
  },
];
