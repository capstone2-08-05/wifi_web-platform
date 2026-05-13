import { useState } from 'react';
import { Clock, Smartphone } from 'lucide-react';
import { cn } from '@/lib/utils';
import { HelpFab } from '@/components/HelpFab';
import {
  MeasurementCanvas,
  type MeasurementView,
} from '@/features/measurement/MeasurementCanvas';
import { DiagnosticPanel } from '@/features/measurement/DiagnosticPanel';

const TABS: { id: MeasurementView; label: string }[] = [
  { id: 'path', label: '측정 경로 보기' },
  { id: 'heatmap', label: '실측 히트맵' },
  { id: 'combined', label: '예측·실측 통합 분석' },
];

export default function MeasurementPage() {
  const [view, setView] = useState<MeasurementView>('path');

  return (
    <div className="relative flex h-full flex-col p-6">
      <PageHeader />
      <div className="mt-5">
        <Tabs view={view} onChange={setView} />
      </div>

      <div className="mt-5 grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1fr_360px]">
        <div className="min-h-0 rounded-2xl border bg-background p-4 shadow-sm">
          <MeasurementCanvas view={view} />
        </div>
        <aside className="flex min-h-0 flex-col overflow-y-auto pr-1">
          <DiagnosticPanel />
        </aside>
      </div>

      <HelpFab />
    </div>
  );
}

function PageHeader() {
  return (
    <header className="flex items-start justify-between gap-4">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">실측 및 진단</h1>
        <p className="text-sm text-muted-foreground">
          모바일 기기로 측정한 실제 와이파이 품질 데이터와 시뮬레이션을 통합하여 분석합니다.
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm font-medium text-foreground/80 shadow-sm hover:bg-accent"
        >
          <Clock className="h-4 w-4 text-muted-foreground" />
          이력 보기 <span className="text-muted-foreground">(어제 오후 3:15)</span>
        </button>
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
        >
          <Smartphone className="h-4 w-4" />
          새로운 측정 시작
        </button>
      </div>
    </header>
  );
}

function Tabs({
  view,
  onChange,
}: {
  view: MeasurementView;
  onChange: (next: MeasurementView) => void;
}) {
  return (
    <nav className="flex items-center gap-6 border-b" role="tablist">
      {TABS.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={view === t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            '-mb-px border-b-2 pb-3 text-sm font-semibold transition-colors',
            view === t.id
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
        >
          {t.label}
        </button>
      ))}
    </nav>
  );
}

