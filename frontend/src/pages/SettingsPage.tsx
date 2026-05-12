import { useAuthStore } from '@/stores/auth-store';

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  return (
    <div className="h-full space-y-6 overflow-auto p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">설정</h1>
      </header>
      <section className="rounded-xl border bg-card p-5 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold">계정</h2>
        <dl className="space-y-2 text-sm">
          <Row label="이름" value={user?.name ?? '-'} />
          <Row label="이메일" value={user?.email ?? '-'} />
        </dl>
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b py-2 last:border-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
