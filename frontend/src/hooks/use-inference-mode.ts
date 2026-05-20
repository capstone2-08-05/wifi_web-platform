import { useEffect, useState } from 'react';

export type InferenceMode = 'sagemaker' | 'local';

const STORAGE_KEY = 'wf:inference_mode';

/**
 * 추론 백엔드 선택 (SageMaker on/off 토글).
 * - localStorage 에 영속, 탭 간 동기화 (storage event)
 * - default = 'sagemaker' (production 경로)
 * - 'local' = AI_SERVICE_URL (백엔드의 `local_inference_service`) 동기 호출
 */
function readMode(): InferenceMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'local' ? 'local' : 'sagemaker';
  } catch {
    return 'sagemaker';
  }
}

export function useInferenceMode(): {
  mode: InferenceMode;
  setMode: (m: InferenceMode) => void;
  isSagemaker: boolean;
} {
  const [mode, setModeState] = useState<InferenceMode>(readMode);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setModeState(readMode());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const setMode = (m: InferenceMode) => {
    try {
      localStorage.setItem(STORAGE_KEY, m);
    } catch {
      /* localStorage 사용 불가능한 환경 — 메모리에만 유지 */
    }
    setModeState(m);
  };

  return { mode, setMode, isSagemaker: mode === 'sagemaker' };
}

/**
 * 모듈 스코프에서 현재 모드 읽기 — analyze API call site 처럼 hook 사용이 곤란할 때.
 * (탭 간 동기화/리액티브 갱신은 안 됨. 호출 시점에 최신값 1회 조회.)
 */
export function getInferenceModeOnce(): InferenceMode {
  return readMode();
}
