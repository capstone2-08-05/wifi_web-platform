import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { ProtectedRoute } from './ProtectedRoute';
import { AppLayout } from '@/layouts/AppLayout';

const LoginPage = lazy(() => import('@/pages/auth/LoginPage'));
const SignupPage = lazy(() => import('@/pages/auth/SignupPage'));
const DashboardPage = lazy(() => import('@/pages/DashboardPage'));
const EditorPage = lazy(() => import('@/pages/EditorPage'));
const SimulationPage = lazy(() => import('@/pages/SimulationPage'));
const MeasurementPage = lazy(() => import('@/pages/MeasurementPage'));
const MobileAppPage = lazy(() => import('@/pages/MobileAppPage'));
const SettingsPage = lazy(() => import('@/pages/SettingsPage'));

const Loading = () => (
  <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
    로딩 중…
  </div>
);

const router = createBrowserRouter([
  {
    path: '/auth/login',
    element: (
      <Suspense fallback={<Loading />}>
        <LoginPage />
      </Suspense>
    ),
  },
  {
    path: '/auth/signup',
    element: (
      <Suspense fallback={<Loading />}>
        <SignupPage />
      </Suspense>
    ),
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },
          {
            path: 'dashboard',
            element: (
              <Suspense fallback={<Loading />}>
                <DashboardPage />
              </Suspense>
            ),
          },
          {
            path: 'editor',
            element: (
              <Suspense fallback={<Loading />}>
                <EditorPage />
              </Suspense>
            ),
          },
          {
            path: 'simulation',
            element: (
              <Suspense fallback={<Loading />}>
                <SimulationPage />
              </Suspense>
            ),
          },
          {
            path: 'measurement',
            element: (
              <Suspense fallback={<Loading />}>
                <MeasurementPage />
              </Suspense>
            ),
          },
          {
            path: 'mobile',
            element: (
              <Suspense fallback={<Loading />}>
                <MobileAppPage />
              </Suspense>
            ),
          },
          {
            path: 'settings',
            element: (
              <Suspense fallback={<Loading />}>
                <SettingsPage />
              </Suspense>
            ),
          },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
