import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User } from '@/types/auth';

interface AuthState {
  token: string | null;
  user: User | null;
  expiresAt: number | null;
  setSession: (token: string, expiresInSec: number, user: User) => void;
  setUser: (user: User) => void;
  clear: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      expiresAt: null,
      setSession: (token, expiresInSec, user) =>
        set({
          token,
          user,
          expiresAt: Date.now() + expiresInSec * 1000,
        }),
      setUser: (user) => set({ user }),
      clear: () => set({ token: null, user: null, expiresAt: null }),
      isAuthenticated: () => {
        const { token, expiresAt } = get();
        if (!token) return false;
        if (expiresAt && Date.now() >= expiresAt) return false;
        return true;
      },
    }),
    {
      name: 'wifang.auth',
      partialize: (s) => ({ token: s.token, user: s.user, expiresAt: s.expiresAt }),
    },
  ),
);
