import { api } from './client';
import type { UUID } from '@/types/common';
import type { MeasurementLinkCreated } from '@/types/measurement-link';

export const measurementLinkApi = {
  // §10.0 POST /floors/{floor_id}/measurement-links — 측정용 QR 토큰 생성
  create: (
    floorId: UUID,
    recommendedPurpose = 'calibration',
    sceneVersionId?: UUID | null,
  ) =>
    api
      .post<MeasurementLinkCreated>(`/floors/${floorId}/measurement-links`, null, {
        params: {
          recommended_measurement_purpose: recommendedPurpose,
          scene_version_id: sceneVersionId ?? undefined,
        },
      })
      .then((r) => r.data),
};
