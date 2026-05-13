import { CheckCircle2, Info, X, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useToastStore, type Toast, type ToastKind } from '@/stores/toast-store';

const KIND_STYLES: Record<ToastKind, { icon: typeof CheckCircle2; iconClass: string; ring: string }> = {
  success: {
    icon: CheckCircle2,
    iconClass: 'text-emerald-500',
    ring: 'ring-emerald-200',
  },
  error: {
    icon: XCircle,
    iconClass: 'text-red-500',
    ring: 'ring-red-200',
  },
  info: {
    icon: Info,
    iconClass: 'text-primary',
    ring: 'ring-primary/30',
  },
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-50 flex w-full max-w-sm flex-col gap-2">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const style = KIND_STYLES[toast.kind];
  const Icon = style.icon;
  return (
    <div
      role="status"
      className={cn(
        'pointer-events-auto flex items-start gap-3 rounded-xl border bg-background p-3.5 shadow-lg ring-1',
        style.ring,
      )}
    >
      <Icon className={cn('mt-0.5 h-5 w-5 shrink-0', style.iconClass)} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">{toast.title}</p>
        {toast.description && (
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            {toast.description}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="닫기"
        className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
