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

const dismissTimers = new Map<string, number>();

function toastDedupeKey(toast: Pick<Toast, 'kind' | 'title' | 'description'>): string {
  return `${toast.kind}\0${toast.title}\0${toast.description ?? ''}`;
}

function scheduleDismiss(id: string, durationMs: number, dismiss: (id: string) => void) {
  const prev = dismissTimers.get(id);
  if (prev !== undefined) window.clearTimeout(prev);
  const timer = window.setTimeout(() => {
    dismissTimers.delete(id);
    dismiss(id);
  }, durationMs);
  dismissTimers.set(id, timer);
}

export const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],
  show: (toast) => {
    const key = toastDedupeKey(toast);
    const existing = get().toasts.find((t) => toastDedupeKey(t) === key);
    if (existing) {
      const duration = toast.durationMs ?? 4000;
      if (duration > 0) {
        scheduleDismiss(existing.id, duration, get().dismiss);
      }
      return existing.id;
    }

    const id = nextId();
    set((state) => ({ toasts: [...state.toasts, { id, ...toast }] }));

    const duration = toast.durationMs ?? 4000;
    if (duration > 0) {
      scheduleDismiss(id, duration, get().dismiss);
    }
    return id;
  },
  dismiss: (id) => {
    const timer = dismissTimers.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      dismissTimers.delete(id);
    }
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },
  clearAll: () => {
    for (const timer of dismissTimers.values()) {
      window.clearTimeout(timer);
    }
    dismissTimers.clear();
    set({ toasts: [] });
  },
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
