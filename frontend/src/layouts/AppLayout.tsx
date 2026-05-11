import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutGrid,
  Map,
  Radio,
  Smartphone,
  Activity,
  Settings,
  Bell,
  Wifi,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/stores/auth-store';
import { useLogout } from '@/hooks/use-auth';
import { ProjectSelector } from '@/features/header/ProjectSelector';
import { FloorSelector } from '@/features/header/FloorSelector';

const NAV = [
  { to: '/dashboard', label: '대시보드', icon: LayoutGrid },
  { to: '/editor', label: '공간 편집', icon: Map },
  { to: '/simulation', label: '시뮬레이션', icon: Radio },
  { to: '/measurement', label: '실측·진단', icon: Activity },
  { to: '/mobile', label: '모바일 앱', icon: Smartphone },
] as const;

export function AppLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useLogout();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <aside className="flex w-60 shrink-0 flex-col border-r bg-sidebar">
        <div className="flex h-16 items-center gap-2 px-5 border-b">
          <Wifi className="h-5 w-5 text-primary" />
          <span className="text-base font-semibold">Wi-Fang!</span>
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
          <div className="flex items-center gap-3">
            <ProjectSelector />
            <span className="text-muted-foreground/50">/</span>
            <FloorSelector />
          </div>
          <div className="flex items-center gap-3">
            <button className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent">
              <span className="inline-flex items-center gap-1.5">
                <Smartphone className="h-3.5 w-3.5" />
                모바일 앱 연결
              </span>
            </button>
            <button className="relative rounded-md p-2 hover:bg-accent" aria-label="알림">
              <Bell className="h-4 w-4" />
              <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-destructive" />
            </button>
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-xs font-medium">
                {(user?.name ?? '?').slice(0, 1)}
              </div>
              <button
                onClick={logout}
                className="rounded-md border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                로그아웃
              </button>
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

