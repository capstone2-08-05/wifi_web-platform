import { api } from './client';
import type { UUID } from '@/types/common';
import type { MeasurementLinkCreated } from '@/types/measurement-link';

export const measurementLinkApi = {
  // §10.0 POST /floors/{floor_id}/measurement-links — 측정용 QR 토큰 생성
  create: (floorId: UUID) =>
    api
      .post<MeasurementLinkCreated>(`/floors/${floorId}/measurement-links`)
      .then((r) => r.data),
};
