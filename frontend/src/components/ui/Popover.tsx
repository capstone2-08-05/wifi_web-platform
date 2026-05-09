import { useEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface PopoverProps {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  children: (props: { close: () => void }) => ReactNode;
  align?: 'start' | 'end';
  contentClassName?: string;
}

/**
 * Minimal controlled popover. Closes on outside click and Escape.
 * Render-prop API so trigger and content can react to open state and close themselves.
 */
export function Popover({ trigger, children, align = 'start', contentClassName }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const close = () => setOpen(false);
  const toggle = () => setOpen((v) => !v);

  return (
    <div ref={wrapRef} className="relative inline-flex">
      {trigger({ open, toggle })}
      {open && (
        <div
          role="dialog"
          className={cn(
            'absolute top-full z-30 mt-2 min-w-56 rounded-md border bg-popover text-popover-foreground shadow-lg',
            align === 'end' ? 'right-0' : 'left-0',
            contentClassName,
          )}
        >
          {children({ close })}
        </div>
      )}
    </div>
  );
}
