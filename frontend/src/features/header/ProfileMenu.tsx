import { LogIn, LogOut, Settings, User } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Popover } from '@/components/ui/Popover';
import { useAuthStore } from '@/stores/auth-store';
import { useLogout } from '@/hooks/use-auth';

export function ProfileMenu() {
  const user = useAuthStore((s) => s.user);
  const logout = useLogout();
  const isAuthed = !!user;

  return (
    <Popover
      align="end"
      contentClassName="w-64 p-0"
      trigger={({ toggle }) => (
        <button
          onClick={toggle}
          aria-label="프로필"
          className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-muted-foreground hover:bg-accent"
        >
          {user?.name ? (
            <span className="text-xs font-medium">{user.name.slice(0, 1)}</span>
          ) : (
            <User className="h-4 w-4" />
          )}
        </button>
      )}
    >
      {({ close }) => (
        <div>
          <div className="border-b p-3.5">
            <p className="truncate text-sm font-semibold">
              {isAuthed ? user.name : '게스트'}
            </p>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {isAuthed ? user.email : '로그인되지 않음'}
            </p>
          </div>
          <ul className="py-1">
            <li>
              <Link
                to="/settings"
                onClick={close}
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-accent"
              >
                <Settings className="h-3.5 w-3.5 text-muted-foreground" />
                설정
              </Link>
            </li>
            {isAuthed ? (
              <li>
                <button
                  type="button"
                  onClick={() => {
                    close();
                    logout();
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm text-destructive hover:bg-destructive/5"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  로그아웃
                </button>
              </li>
            ) : (
              <li>
                <Link
                  to="/auth/login"
                  onClick={close}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/5"
                >
                  <LogIn className="h-3.5 w-3.5" />
                  로그인
                </Link>
              </li>
            )}
          </ul>
        </div>
      )}
    </Popover>
  );
}
