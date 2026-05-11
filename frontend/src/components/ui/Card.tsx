import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function Card({
  title,
  action,
  children,
  className,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn('rounded-xl border bg-card p-5 shadow-sm', className)}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between">
          {title && <h2 className="text-sm font-semibold">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
