import { Bell, CheckCheck, ChevronRight } from 'lucide-react';
import { Popover } from '@/components/ui/Popover';
import { cn } from '@/lib/utils';

type NotificationKind = 'analysis' | 'measurement' | 'simulation' | 'system';

interface Notification {
  id: string;
  kind: NotificationKind;
  title: string;
  description: string;
  timeLabel: string;
  unread: boolean;
}

// 백엔드 알림 엔드포인트 없음. 추후 별도 협의 시 useQuery 로 교체 예정.
const MOCK_NOTIFICATIONS: Notification[] = [
  {
    id: 'n-1',
    kind: 'analysis',
    title: '도면 분석 완료',
    description: '1층 도면 분석이 완료되었습니다.',
    timeLabel: '방금 전',
    unread: true,
  },
  {
    id: 'n-2',
    kind: 'measurement',
    title: '새 실측 데이터 수신',
    description: '카운터 주변 17개 포인트 측정됨.',
    timeLabel: '12분 전',
    unread: true,
  },
  {
    id: 'n-3',
    kind: 'simulation',
    title: '시뮬레이션 완료',
    description: '평균 -62dBm, 커버리지 85%',
    timeLabel: '어제',
    unread: false,
  },
];

const KIND_DOT: Record<NotificationKind, string> = {
  analysis: 'bg-primary',
  measurement: 'bg-emerald-500',
  simulation: 'bg-violet-500',
  system: 'bg-slate-400',
};

export function NotificationsMenu() {
  const unreadCount = MOCK_NOTIFICATIONS.filter((n) => n.unread).length;
  return (
    <Popover
      align="end"
      contentClassName="w-80 p-0"
      trigger={({ toggle }) => (
        <button
          onClick={toggle}
          aria-label="알림"
          className="relative rounded-md p-2 hover:bg-accent"
        >
          <Bell className="h-5 w-5 text-muted-foreground" />
          {unreadCount > 0 && (
            <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-destructive" />
          )}
        </button>
      )}
    >
      {({ close }) => (
        <div className="flex max-h-96 flex-col">
          <header className="flex items-center justify-between border-b px-4 py-3">
            <h3 className="text-sm font-semibold">알림</h3>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <CheckCheck className="h-3 w-3" />
              모두 읽음
            </button>
          </header>

          <ul className="flex-1 overflow-y-auto">
            {MOCK_NOTIFICATIONS.length === 0 ? (
              <li className="px-4 py-8 text-center text-xs text-muted-foreground">
                새 알림이 없습니다.
              </li>
            ) : (
              MOCK_NOTIFICATIONS.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={close}
                    className="flex w-full items-start gap-2.5 border-b px-4 py-3 text-left hover:bg-accent/40"
                  >
                    <span
                      className={cn(
                        'mt-1.5 block h-2 w-2 shrink-0 rounded-full',
                        n.unread ? KIND_DOT[n.kind] : 'bg-transparent ring-1 ring-border',
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <p className="truncate text-sm font-medium">{n.title}</p>
                        <span className="shrink-0 text-[10px] text-muted-foreground">
                          {n.timeLabel}
                        </span>
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                        {n.description}
                      </p>
                    </div>
                  </button>
                </li>
              ))
            )}
          </ul>

          <footer className="border-t p-2">
            <button
              type="button"
              className="inline-flex w-full items-center justify-center gap-1 rounded-md py-1.5 text-xs font-medium text-primary hover:bg-primary/5"
            >
              전체 알림 보기
              <ChevronRight className="h-3 w-3" />
            </button>
          </footer>
        </div>
      )}
    </Popover>
  );
}
