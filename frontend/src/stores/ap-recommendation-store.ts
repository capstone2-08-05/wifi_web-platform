import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { MeterBBox } from '@/features/ap-recommendation/recommendation-utils';
import type { ApRecommendationResult } from '@/types/ap-recommendation';
import type { UUID } from '@/types/common';

/** 층(floor)별 AP 배치 추천 UI 세션 — 페이지 이동 후에도 복원. */
export interface ApRecommendationSession {
  sceneVersionId: UUID | null;
  selectionBBox: MeterBBox | null;
  recommendations: ApRecommendationResult[];
  selectedRank: number | null;
  savedRank: number | null;
}

export const EMPTY_AP_RECOMMENDATION_SESSION: ApRecommendationSession = {
  sceneVersionId: null,
  selectionBBox: null,
  recommendations: [],
  selectedRank: null,
  savedRank: null,
};

interface ApRecommendationStore {
  byFloor: Record<string, ApRecommendationSession>;
  patchFloor: (floorId: string, patch: Partial<ApRecommendationSession>) => void;
  clearFloor: (floorId: string) => void;
}

export const useApRecommendationStore = create<ApRecommendationStore>()(
  persist(
    (set) => ({
      byFloor: {},
      patchFloor: (floorId, patch) =>
        set((s) => ({
          byFloor: {
            ...s.byFloor,
            [floorId]: {
              ...EMPTY_AP_RECOMMENDATION_SESSION,
              ...s.byFloor[floorId],
              ...patch,
            },
          },
        })),
      clearFloor: (floorId) =>
        set((s) => {
          const next = { ...s.byFloor };
          delete next[floorId];
          return { byFloor: next };
        }),
    }),
    {
      name: 'wifang.ap-recommendation',
      partialize: (s) => ({
        byFloor: Object.fromEntries(
          Object.entries(s.byFloor).filter(([, v]) => v.savedRank != null),
        ),
      }),
    },
  ),
);
