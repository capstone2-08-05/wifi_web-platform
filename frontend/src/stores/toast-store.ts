import { create } from 'zustand';

export type ToastKind = 'success' | 'error' | 'info';

export interface Toast {
  id: string;
  kind: ToastKind;
  title: string;
  description?: string;
  /** ms. 기본 4000. 0이면 수동 닫기만. */
  durationMs?: number;
}

interface ToastStore {
  toasts: Toast[];
  show: (toast: Omit<Toast, 'id'>) => string;
  dismiss: (id: string) => void;
  clearAll: () => void;
}

let counter = 0;
const nextId = () => {
  counter += 1;
  return `t-${Date.now()}-${counter}`;
};

export const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],
  show: (toast) => {
    const id = nextId();
    set((state) => ({ toasts: [...state.toasts, { id, ...toast }] }));

    const duration = toast.durationMs ?? 4000;
    if (duration > 0) {
      window.setTimeout(() => get().dismiss(id), duration);
    }
    return id;
  },
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
  clearAll: () => set({ toasts: [] }),
}));

// 편의 함수
export const toast = {
  success: (title: string, description?: string) =>
    useToastStore.getState().show({ kind: 'success', title, description }),
  error: (title: string, description?: string) =>
    useToastStore.getState().show({ kind: 'error', title, description }),
  info: (title: string, description?: string) =>
    useToastStore.getState().show({ kind: 'info', title, description }),
};
