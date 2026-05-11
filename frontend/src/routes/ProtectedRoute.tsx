import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { env } from '@/config/env';
import { useAuthStore } from '@/stores/auth-store';

export function ProtectedRoute() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated());
  const location = useLocation();
  if (env.bypassAuth) return <Outlet />;
  if (!isAuthed) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/auth/login?next=${next}`} replace />;
  }
  return <Outlet />;
}
