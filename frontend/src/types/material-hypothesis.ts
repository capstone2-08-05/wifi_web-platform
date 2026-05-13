import type { ISODateString, UUID } from './common';

// 백엔드 §12.3 Material Hypothesis — 자동 추출된 재질 후보.
// scene_version_id 기반이므로 Draft 단계에선 비어있을 수 있음.

export interface MaterialHypothesis {
  id: UUID;
  scene_version_id: UUID;
  target_type: 'wall' | 'room' | 'opening' | 'object' | string;
  target_id: UUID;
  material_name: string;
  confidence: string | null;
  source_method: string | null;
  is_selected: boolean;
  evidence_json: Record<string, unknown>;
  created_at: ISODateString;
}
