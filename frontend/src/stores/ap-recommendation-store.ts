import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ApRecommendationArea } from '@/features/ap-recommendation/recommendation-utils';
import type { ApRecommendationResult } from '@/types/ap-recommendation';
import type { UUID } from '@/types/common';

/** 도면 버전별 와이파이 추천 UI 기록. */
export interface ApRecommendationSession {
  sceneVersionId: UUID | null;
  areas: ApRecommendationArea[];
  recommendations: ApRecommendationResult[];
  selectedRank: number | null;
  savedRank: number | null;
  compareWithMeasurement: boolean;
  updatedAt: string | null;
}

export const EMPTY_AP_RECOMMENDATION_SESSION: ApRecommendationSession = {
  sceneVersionId: null,
  areas: [],
  recommendations: [],
  selectedRank: null,
  savedRank: null,
  compareWithMeasurement: false,
  updatedAt: null,
};

interface ApRecommendationStore {
  byScene: Record<string, ApRecommendationSession>;
  patchScene: (sceneVersionId: UUID, patch: Partial<ApRecommendationSession>) => void;
  clearScene: (sceneVersionId: UUID) => void;
}

export const useApRecommendationStore = create<ApRecommendationStore>()(
  persist(
    (set) => ({
      byScene: {},
      patchScene: (sceneVersionId, patch) =>
        set((s) => ({
          byScene: {
            ...s.byScene,
            [sceneVersionId]: {
              ...EMPTY_AP_RECOMMENDATION_SESSION,
              ...s.byScene[sceneVersionId],
              sceneVersionId,
              ...patch,
            },
          },
        })),
      clearScene: (sceneVersionId) =>
        set((s) => {
          const next = { ...s.byScene };
          delete next[sceneVersionId];
          return { byScene: next };
        }),
    }),
    {
      name: 'wifang.ap-recommendation',
      partialize: (s) => ({
        byScene: Object.fromEntries(
          Object.entries(s.byScene).filter(
            ([, v]) =>
              v.areas.length > 0 ||
              v.recommendations.length > 0 ||
              v.savedRank != null,
          ),
        ),
      }),
    },
  ),
);
