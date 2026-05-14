import type { ISODateString } from './common';

// 백엔드 §10.0 POST /floors/{floor_id}/measurement-links 응답.
// 모바일 앱이 QR 또는 deep_link 로 접근 → /measurement-links/{token}/context 조회.

export interface MeasurementLinkCreated {
  token: string;
  expires_at: ISODateString;
  deep_link: string;
  web_fallback_url: string;
  qr_payload: string;
}
