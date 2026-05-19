import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  LayoutGrid,
  Map,
  Radio,
  Smartphone,
  Activity,
  Settings,
  Wifi,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { ProjectSelector } from '@/features/header/ProjectSelector';
import { FloorSelector } from '@/features/header/FloorSelector';
import { ProfileMenu } from '@/features/header/ProfileMenu';
import { InferenceModeToggle } from '@/features/header/InferenceModeToggle';
import { MobileConnectModal } from '@/features/mobile/MobileConnectModal';

const NAV = [
  { to: '/dashboard', label: '대시보드', icon: LayoutGrid },
  { to: '/editor', label: '공간 편집', icon: Map },
  { to: '/simulation', label: '시뮬레이션', icon: Radio },
  { to: '/measurement', label: '실측/진단', icon: Activity },
  { to: '/mobile', label: '모바일 앱', icon: Smartphone },
] as const;

export function AppLayout() {
  const [mobileConnectOpen, setMobileConnectOpen] = useState(false);
  // /mobile 페이지에선 헤더의 "모바일 앱 연결" 버튼을 숨기고 페이지 내 카드 하단에 배치.
  const location = useLocation();
  const isMobileAppPage = location.pathname.startsWith('/mobile');

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
          <div className="flex items-center gap-3">
            <ProjectSelector />
            <span className="text-muted-foreground/50">/</span>
            <FloorSelector />
          </div>
          <div className="flex items-center gap-2">
            <InferenceModeToggle />
            {!isMobileAppPage && (
              <button
                type="button"
                onClick={() => setMobileConnectOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-sm font-medium text-foreground/80 shadow-sm transition-colors hover:bg-accent"
              >
                <Smartphone className="h-4 w-4" />
                모바일 앱 연결
              </button>
            )}
            <ProfileMenu />
          </div>
        </header>

        <main className="flex-1 overflow-hidden bg-background">
          <Outlet />
        </main>
      </div>

      <MobileConnectModal open={mobileConnectOpen} onClose={() => setMobileConnectOpen(false)} />
    </div>
  );
}

