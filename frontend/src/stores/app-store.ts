import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { UUID } from '@/types/common';

interface AppState {
  selectedProjectId: UUID | null;
  selectedFloorId: UUID | null;
  setProject: (id: UUID | null) => void;
  setFloor: (id: UUID | null) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      selectedProjectId: null,
      selectedFloorId: null,
      setProject: (id) => set({ selectedProjectId: id, selectedFloorId: null }),
      setFloor: (id) => set({ selectedFloorId: id }),
    }),
    {
      name: 'wifang.app',
    },
  ),
);
