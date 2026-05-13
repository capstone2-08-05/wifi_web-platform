import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  LayoutGrid,
  Map,
  Radio,
  Smartphone,
  Activity,
  Settings,
  Bell,
  Wifi,
  FolderOpen,
  Save,
  User,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/stores/auth-store';
import { useLogout } from '@/hooks/use-auth';
import { useEditorStore } from '@/stores/editor-store';
import { ProjectSelector } from '@/features/header/ProjectSelector';
import { FloorSelector } from '@/features/header/FloorSelector';

const NAV = [
  { to: '/dashboard', label: '대시보드', icon: LayoutGrid },
  { to: '/editor', label: '공간 편집', icon: Map },
  { to: '/simulation', label: '시뮬레이션', icon: Radio },
  { to: '/measurement', label: '실측/진단', icon: Activity },
  { to: '/mobile', label: '모바일 앱', icon: Smartphone },
] as const;

export function AppLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useLogout();
  const location = useLocation();
  const editorActions = useEditorStore((s) => s.actions);
  const isEditor = location.pathname.startsWith('/editor');

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <aside className="flex w-60 shrink-0 flex-col border-r bg-sidebar">
        <div className="flex h-16 items-center gap-2 px-5 border-b">
          <Wifi className="h-5 w-5 text-primary" />
          <span className="text-base font-semibold">Wi-Fi Space</span>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                    : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-3">
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                  : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
              )
            }
          >
            <Settings className="h-4 w-4" />
            설정
          </NavLink>
        </div>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-16 shrink-0 items-center justify-between border-b bg-background px-6">
          <div className="flex items-center gap-2">
            {isEditor ? (
              <>
                <button
                  type="button"
                  onClick={editorActions.onLoadFloorplan}
                  className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-sm font-medium text-foreground/80 shadow-sm transition-colors hover:bg-accent"
                >
                  <FolderOpen className="h-4 w-4" />
                  도면 불러오기
                </button>
                <button
                  type="button"
                  onClick={editorActions.onSaveFloorplan}
                  disabled={!editorActions.onSaveFloorplan}
                  title={!editorActions.onSaveFloorplan ? '저장할 분석 결과가 없습니다' : undefined}
                  className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-sm font-medium text-foreground/80 shadow-sm transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-background"
                >
                  <Save className="h-4 w-4" />
                  도면 저장하기
                </button>
              </>
            ) : (
              <div className="flex items-center gap-3">
                <ProjectSelector />
                <span className="text-muted-foreground/50">/</span>
                <FloorSelector />
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-sm font-medium text-foreground/80 shadow-sm transition-colors hover:bg-accent">
              <Smartphone className="h-4 w-4" />
              모바일 앱 연결
            </button>
            <button className="relative rounded-md p-2 hover:bg-accent" aria-label="알림">
              <Bell className="h-5 w-5 text-muted-foreground" />
              <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-destructive" />
            </button>
            <div className="flex items-center gap-2">
              <button
                aria-label="프로필"
                className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-muted-foreground hover:bg-accent"
              >
                {user?.name ? (
                  <span className="text-xs font-medium">
                    {user.name.slice(0, 1)}
                  </span>
                ) : (
                  <User className="h-4 w-4" />
                )}
              </button>
              <button
                onClick={logout}
                className="rounded-md border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                로그아웃
              </button>
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-hidden bg-background">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

