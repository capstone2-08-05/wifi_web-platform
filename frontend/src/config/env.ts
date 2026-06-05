export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://3.34.1.198:8000',
  /** Dev-only: skip ProtectedRoute auth guard. Ignored in production builds. */
  bypassAuth:
    import.meta.env.DEV && import.meta.env.VITE_BYPASS_AUTH === 'true',
} as const;
