import { useMutation } from '@tanstack/react-query';
import { measurementLinkApi } from '@/api/measurement-link';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { UUID } from '@/types/common';

/**
 * §10.0 — 모바일 앱 연결용 측정 토큰 / QR payload 발급.
 * 응답의 qr_payload 문자열을 프론트가 QR 로 렌더링.
 */
export function useCreateMeasurementLink() {
  return useMutation({
    mutationFn: ({
      floorId,
      recommendedPurpose = 'calibration',
      sceneVersionId,
    }: {
      floorId: UUID;
      recommendedPurpose?: 'calibration' | 'reference' | 'validation' | 'unknown';
      sceneVersionId?: UUID | null;
    }) => measurementLinkApi.create(floorId, recommendedPurpose, sceneVersionId),
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error(
        'QR 코드 생성 실패',
        e?.message ?? '잠시 후 다시 시도해주세요.',
      );
    },
  });
}
