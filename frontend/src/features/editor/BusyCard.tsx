import { Loader2 } from 'lucide-react';

export function BusyCard({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex h-72 flex-col items-center justify-center gap-3 rounded-xl border bg-card shadow-sm">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="text-sm font-medium">{title}</p>
      {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
    </div>
  );
}
