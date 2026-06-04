import { useCallback, useEffect, useState } from 'react';
import {
  EMPTY_AP_RECOMMENDATION_SESSION,
  useApRecommendationStore,
  type ApRecommendationSession,
} from '@/stores/ap-recommendation-store';
import type { ApRecommendationArea } from '@/features/ap-recommendation/recommendation-utils';
import type { ApRecommendationResult } from '@/types/ap-recommendation';
import type { UUID } from '@/types/common';

function getStoredSession(sceneVersionId: UUID | null): ApRecommendationSession | null {
  if (!sceneVersionId) return null;
  return useApRecommendationStore.getState().byScene[sceneVersionId] ?? null;
}

export function useApRecommendationSession(
  _floorId: UUID | null,
  sceneVersionId: UUID | null,
) {
  const patchScene = useApRecommendationStore((s) => s.patchScene);
  const clearScene = useApRecommendationStore((s) => s.clearScene);

  const [areas, setAreas] = useState<ApRecommendationArea[]>([]);
  const [recommendations, setRecommendations] = useState<ApRecommendationResult[]>([]);
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const [savedRank, setSavedRank] = useState<number | null>(null);
  const [compareWithMeasurement, setCompareWithMeasurement] = useState(false);

  useEffect(() => {
    const stored = getStoredSession(sceneVersionId);

    if (stored) {
      setAreas(stored.areas);
      setRecommendations(stored.recommendations);
      setSelectedRank(stored.selectedRank);
      setSavedRank(stored.savedRank);
      setCompareWithMeasurement(stored.compareWithMeasurement);
      return;
    }

    setAreas(EMPTY_AP_RECOMMENDATION_SESSION.areas);
    setRecommendations(EMPTY_AP_RECOMMENDATION_SESSION.recommendations);
    setSelectedRank(EMPTY_AP_RECOMMENDATION_SESSION.selectedRank);
    setSavedRank(EMPTY_AP_RECOMMENDATION_SESSION.savedRank);
    setCompareWithMeasurement(EMPTY_AP_RECOMMENDATION_SESSION.compareWithMeasurement);
  }, [sceneVersionId]);

  const persistSession = useCallback(
    (patch: Partial<ApRecommendationSession>) => {
      if (!sceneVersionId) return;
      patchScene(sceneVersionId, {
        sceneVersionId,
        updatedAt: new Date().toISOString(),
        ...patch,
      });
    },
    [patchScene, sceneVersionId],
  );

  const resetSession = useCallback(() => {
    if (sceneVersionId) clearScene(sceneVersionId);
    setAreas([]);
    setRecommendations([]);
    setSelectedRank(null);
    setSavedRank(null);
    setCompareWithMeasurement(false);
  }, [clearScene, sceneVersionId]);

  return {
    areas,
    recommendations,
    selectedRank,
    savedRank,
    compareWithMeasurement,
    setAreas,
    setRecommendations,
    setSelectedRank,
    setSavedRank,
    setCompareWithMeasurement,
    persistSession,
    resetSession,
  };
}
