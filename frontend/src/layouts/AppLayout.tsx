import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  LayoutGrid,
  Map,
  Radio,
  Sparkles,
  Activity,
  Settings,
  Wifi,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { ProjectSelector } from '@/features/header/ProjectSelector';
import { FloorSelector } from '@/features/header/FloorSelector';
import { ProfileMenu } from '@/features/header/ProfileMenu';
import { InferenceModeToggle } from '@/features/header/InferenceModeToggle';

const NAV = [
  { to: '/dashboard', label: '대시보드', icon: LayoutGrid, step: null },
  { to: '/editor', label: '공간 편집', icon: Map, step: '01' },
  { to: '/simulation', label: '시뮬레이션', icon: Radio, step: '02' },
  { to: '/measurement', label: '실측/진단', icon: Activity, step: '03' },
  { to: '/mobile', label: 'AP 배치 추천', icon: Sparkles, step: '04' },
] as const;

export function AppLayout() {
  const location = useLocation();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <aside
        className="flex w-70 shrink-0 flex-col border-r"
        style={{ background: 'linear-gradient(180deg, #F8FBFF 0%, #F2F6FB 100%)', borderColor: '#E5EAF0' }}
      >
        <div className="flex h-16 items-center gap-3 border-b px-5" style={{ borderColor: '#E5EAF0' }}>
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white"
            style={{ background: 'linear-gradient(135deg, #0A74FF, #37B6FF)' }}
          >
            <Wifi className="h-5 w-5" />
          </div>
          <span className="text-sm font-semibold">Wi-Fi Space</span>
        </div>
        <nav className="flex-1 space-y-0.5 p-3">
          {NAV.map(({ to, label, icon: Icon, step }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'relative flex items-center gap-3 rounded-xl py-2.75 pr-4 text-sm transition-all duration-200',
                  isActive
                    ? 'pl-3 font-bold'
                    : 'pl-4 font-medium text-slate-500 hover:bg-blue-50/60 hover:text-slate-700',
                )
              }
              style={({ isActive }) =>
                isActive
                  ? { background: '#EAF3FF', color: '#0A74FF', boxShadow: '0 4px 16px rgba(10,116,255,0.10)' }
                  : undefined
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute left-0 top-1/2 h-5 w-0.75 -translate-y-1/2 rounded-r-full bg-[#0A74FF]" />
                  )}
                  {step ? (
                    <span
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold transition-colors"
                      style={
                        isActive
                          ? { background: '#0A74FF', color: 'white' }
                          : { background: '#EEF2F6', color: '#6B7280' }
                      }
                    >
                      {step}
                    </span>
                  ) : (
                    <Icon className="h-4 w-4 shrink-0" />
                  )}
                  {step && <Icon className="h-3.75 w-3.75 shrink-0 opacity-50" />}
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-3" style={{ borderColor: '#E5EAF0' }}>
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              cn(
                'relative flex items-center gap-3 rounded-xl py-2.75 pr-4 text-sm transition-all duration-200',
                isActive
                  ? 'pl-3 font-bold'
                  : 'pl-4 font-medium text-slate-500 hover:bg-blue-50/60 hover:text-slate-700',
              )
            }
            style={({ isActive }) =>
              isActive
                ? { background: '#EAF3FF', color: '#0A74FF', boxShadow: '0 4px 16px rgba(10,116,255,0.10)' }
                : undefined
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-0 top-1/2 h-5 w-0.75 -translate-y-1/2 rounded-r-full bg-[#0A74FF]" />
                )}
                <Settings className="h-4 w-4 shrink-0" />
                설정
              </>
            )}
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
            <ProfileMenu />
          </div>
        </header>

        <main className="flex-1 overflow-hidden bg-background">
          <div
            key={location.key}
            className="h-full"
            style={{ animation: 'page-enter 0.45s cubic-bezier(0.16, 1, 0.3, 1) both' }}
          >
            <Outlet />
          </div>
        </main>
      </div>

    </div>
  );
}

