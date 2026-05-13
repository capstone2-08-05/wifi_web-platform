import { Code2, LogIn, LogOut, Mail, User2, Info, FileText } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuthStore } from '@/stores/auth-store';
import { useLogout } from '@/hooks/use-auth';

const APP_VERSION = '0.1.0';

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  const logout = useLogout();
  const isAuthed = !!user;

  return (
    <div className="h-full overflow-auto p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <header className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">설정</h1>
          <p className="text-sm text-muted-foreground">
            계정 정보와 앱 환경을 관리합니다.
          </p>
        </header>

        <Card title="계정">
          <ul className="space-y-1">
            <Row
              icon={<User2 className="h-4 w-4 text-muted-foreground" />}
              label="이름"
              value={user?.name ?? '게스트'}
            />
            <Row
              icon={<Mail className="h-4 w-4 text-muted-foreground" />}
              label="이메일"
              value={user?.email ?? '로그인되지 않음'}
            />
          </ul>
          <div className="mt-5 flex justify-end">
            {isAuthed ? (
              <button
                type="button"
                onClick={logout}
                className="inline-flex items-center gap-1.5 rounded-md border border-destructive/30 bg-background px-3 py-1.5 text-xs font-medium text-destructive shadow-sm hover:bg-destructive/5"
              >
                <LogOut className="h-3.5 w-3.5" />
                로그아웃
              </button>
            ) : (
              <Link
                to="/auth/login"
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90"
              >
                <LogIn className="h-3.5 w-3.5" />
                로그인
              </Link>
            )}
          </div>
        </Card>

        <Card title="앱 정보">
          <ul className="space-y-1">
            <Row
              icon={<Info className="h-4 w-4 text-muted-foreground" />}
              label="버전"
              value={`v${APP_VERSION}`}
            />
            <Row
              icon={<FileText className="h-4 w-4 text-muted-foreground" />}
              label="프로젝트"
              value="Wi-Fi Space (캡스톤 08조)"
            />
            <Row
              icon={<Code2 className="h-4 w-4 text-muted-foreground" />}
              label="저장소"
              value="capstone2-08-05"
            />
          </ul>
        </Card>

        <p className="text-center text-[11px] text-muted-foreground">
          © 2026 Wi-Fi Space — 캡스톤 08조
        </p>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border bg-card p-5 shadow-sm">
      <h2 className="mb-4 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Row({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <li className="flex items-center justify-between gap-3 border-b py-2.5 last:border-0">
      <div className="flex items-center gap-2.5">
        {icon}
        <span className="text-sm text-muted-foreground">{label}</span>
      </div>
      <span className="text-sm font-medium">{value}</span>
    </li>
  );
}
