import { api } from './client';
import type { UUID } from '@/types/common';
import type { Material, MaterialRfProfile } from '@/types/material';

export const materialApi = {
  // §12.1 GET /materials  (?is_active=true)
  list: (params?: { is_active?: boolean }) =>
    api.get<Material[]>('/materials', { params }).then((r) => r.data),

  // §12.2 GET /materials/{id}/rf-profile
  getRfProfile: (id: UUID, freqGhz?: number) =>
    api
      .get<MaterialRfProfile>(`/materials/${id}/rf-profile`, {
        params: freqGhz != null ? { freq_ghz: freqGhz } : undefined,
      })
      .then((r) => r.data),
};
