import { useQuery } from '@tanstack/react-query';
import { materialApi } from '@/api/material';
import type { UUID } from '@/types/common';

/** §12.1 — 활성 재질 목록. 백엔드 Materials DB 와 연동. */
export function useMaterials() {
  return useQuery({
    queryKey: ['materials', { is_active: true }] as const,
    queryFn: () => materialApi.list({ is_active: true }),
    staleTime: 10 * 60 * 1000, // 10분
  });
}

/** §12.2 — 특정 재질의 RF 프로파일 (Sionna 입력용 메타). */
export function useMaterialRfProfile(materialId: UUID | null) {
  return useQuery({
    queryKey: ['material-rf-profile', materialId] as const,
    queryFn: () => materialApi.getRfProfile(materialId as UUID),
    enabled: !!materialId,
    staleTime: 10 * 60 * 1000,
  });
}
