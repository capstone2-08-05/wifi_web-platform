import { useCallback, useEffect, useState } from 'react';
import {
  EMPTY_AP_RECOMMENDATION_SESSION,
  useApRecommendationStore,
  type ApRecommendationSession,
} from '@/stores/ap-recommendation-store';
import type { MeterBBox } from '@/features/ap-recommendation/recommendation-utils';
import type { ApRecommendationResult } from '@/types/ap-recommendation';
import type { UUID } from '@/types/common';

function isPersistedSession(
  session: ApRecommendationSession | undefined,
  sceneVersionId: UUID | null,
): session is ApRecommendationSession {
  if (!session || session.savedRank == null) return false;
  if (
    sceneVersionId &&
    session.sceneVersionId &&
    session.sceneVersionId !== sceneVersionId
  ) {
    return false;
  }
  return true;
}

/**
 * AP 배치 추천 UI 세션.
 * - 페이지 내 편집: useState (추천만 받고 저장 안 한 상태는 유지하지 않음)
 * - 「이 위치 선택」 저장 성공 후에만 localStorage persist
 */
export function useApRecommendationSession(
  floorId: UUID | null,
  sceneVersionId: UUID | null,
) {
  const patchFloor = useApRecommendationStore((s) => s.patchFloor);
  const clearFloor = useApRecommendationStore((s) => s.clearFloor);

  const [selectionBBox, setSelectionBBox] = useState<MeterBBox | null>(null);
  const [recommendations, setRecommendations] = useState<ApRecommendationResult[]>([]);
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const [savedRank, setSavedRank] = useState<number | null>(null);

  useEffect(() => {
    const stored = floorId
      ? useApRecommendationStore.getState().byFloor[floorId]
      : undefined;

    if (isPersistedSession(stored, sceneVersionId)) {
      setSelectionBBox(stored.selectionBBox);
      setRecommendations(stored.recommendations);
      setSelectedRank(stored.selectedRank);
      setSavedRank(stored.savedRank);
      return;
    }

    setSelectionBBox(EMPTY_AP_RECOMMENDATION_SESSION.selectionBBox);
    setRecommendations(EMPTY_AP_RECOMMENDATION_SESSION.recommendations);
    setSelectedRank(EMPTY_AP_RECOMMENDATION_SESSION.selectedRank);
    setSavedRank(EMPTY_AP_RECOMMENDATION_SESSION.savedRank);
  }, [floorId, sceneVersionId]);

  const persistSavedSession = useCallback(
    (session: ApRecommendationSession) => {
      if (!floorId || session.savedRank == null) return;
      patchFloor(floorId, session);
    },
    [floorId, patchFloor],
  );

  const resetSession = useCallback(() => {
    if (floorId) clearFloor(floorId);
    setSelectionBBox(null);
    setRecommendations([]);
    setSelectedRank(null);
    setSavedRank(null);
  }, [floorId, clearFloor]);

  return {
    selectionBBox,
    recommendations,
    selectedRank,
    savedRank,
    setSelectionBBox,
    setRecommendations,
    setSelectedRank,
    setSavedRank,
    persistSavedSession,
    resetSession,
  };
}
