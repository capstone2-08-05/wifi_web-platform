import type { SceneDraft, SceneVersion } from '@/types/scene';

/**
 * SceneVersion 을 SceneDraft 형식으로 변환 (캔버스 read-only 렌더링용).
 * §7.2 GET /scene-versions/{id} 응답이 walls/rooms/openings/objects 를 포함해야 동작.
 */
export function versionToDraftShape(v: SceneVersion): SceneDraft {
  return {
    id: v.id,
    project_id: v.project_id,
    floor_id: v.floor_id,
    source_mode: v.source_mode,
    source_method: v.source_method,
    source_asset_id: v.source_asset_id,
    status: 'promoted',
    created_at: v.created_at,
    updated_at: v.created_at,
    summary_json: {},
    rooms: v.rooms ?? [],
    walls: v.walls ?? [],
    openings: v.openings ?? [],
    objects: v.objects ?? [],
  };
}
