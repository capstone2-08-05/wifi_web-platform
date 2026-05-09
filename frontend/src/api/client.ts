import axios, { AxiosError, type AxiosRequestConfig } from 'axios';
import { env } from '@/config/env';
import { useAuthStore } from '@/stores/auth-store';
import type { ApiError } from '@/types/common';

export const api = axios.create({
  baseURL: env.apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
});

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`);
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiError>) => {
    if (error.response?.status === 401) {
      const code = error.response.data?.code;
      if (code === 'TOKEN_EXPIRED' || code === 'UNAUTHORIZED') {
        useAuthStore.getState().clear();
        if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/auth')) {
          const next = encodeURIComponent(window.location.pathname + window.location.search);
          window.location.href = `/auth/login?next=${next}`;
        }
      }
    }
    return Promise.reject(toApiError(error));
  },
);

export class HttpError extends Error {
  status: number;
  code: string;
  details?: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function toApiError(error: AxiosError<ApiError>): HttpError {
  const status = error.response?.status ?? 0;
  const data = error.response?.data;
  const code = data?.code ?? (status === 0 ? 'NETWORK_ERROR' : 'UNKNOWN_ERROR');
  const message = data?.message ?? error.message ?? 'Unknown error';
  return new HttpError(status, code, message, data?.details);
}

export type { AxiosRequestConfig };
