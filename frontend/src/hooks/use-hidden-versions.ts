import { useCallback, useEffect, useState } from 'react';

/**
 * 프론트엔드 전용 버전 숨김 처리.
 * 백엔드는 DELETE 미지원이라 로컬에서만 가려둠. localStorage 에 ID 보관.
 */
const STORAGE_KEY = 'hidden-scene-versions';

function readSet(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? new Set(arr.filter((x) => typeof x === 'string')) : new Set();
  } catch {
    return new Set();
  }
}

function writeSet(set: Set<string>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...set]));
  } catch {
    /* quota / disabled — 조용히 무시 */
  }
}

export function useHiddenVersions() {
  const [hidden, setHidden] = useState<Set<string>>(() => readSet());

  // 다른 탭에서 변경되면 동기화 (선택적).
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setHidden(readSet());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const hide = useCallback((id: string) => {
    setHidden((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      writeSet(next);
      return next;
    });
  }, []);

  const unhide = useCallback((id: string) => {
    setHidden((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      writeSet(next);
      return next;
    });
  }, []);

  const clearAll = useCallback(() => {
    setHidden(new Set());
    writeSet(new Set());
  }, []);

  return { hidden, hide, unhide, clearAll, isHidden: (id: string) => hidden.has(id) };
}
