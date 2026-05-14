import { Activity, Smartphone } from 'lucide-react';
import { HelpFab } from '@/components/HelpFab';
import { useAppStore } from '@/stores/app-store';
import { useFloorVersions } from '@/hooks/use-scene-version';

export default function MeasurementPage() {
  const floorId = useAppStore((s) => s.selectedFloorId);
  const versionsQuery = useFloorVersions(floorId);
  const hasVersion = (versionsQuery.data?.length ?? 0) > 0;

  return (
    <div className="relative flex h-full flex-col p-6">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">실측 및 진단</h1>
        <p className="text-sm text-muted-foreground">
          모바일 기기로 측정한 실제 와이파이 품질 데이터와 시뮬레이션을 통합하여 분석합니다.
        </p>
      </header>

      <div className="mt-5 flex flex-1 items-center justify-center">
        <div className="flex max-w-lg flex-col items-center gap-3 rounded-2xl border border-dashed bg-background p-10 text-center shadow-sm">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
            <Activity className="h-6 w-6 text-primary" strokeWidth={1.8} />
          </div>
          {!floorId ? (
            <>
              <p className="text-base font-semibold">층을 먼저 선택해주세요</p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                상단 셀렉터에서 작업할 도면(층)을 선택하면 측정 시작 흐름이 표시됩니다.
              </p>
            </>
          ) : !hasVersion ? (
            <>
              <p className="text-base font-semibold">확정된 도면이 필요합니다</p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                공간 편집에서 도면을 분석·확정한 후 모바일 앱으로 실측을 진행할 수 있습니다.
              </p>
            </>
          ) : (
            <>
              <p className="text-base font-semibold">측정 데이터가 없습니다</p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                상단 헤더의 <span className="inline-flex items-center gap-1 align-middle font-medium text-foreground"><Smartphone className="h-3.5 w-3.5" /> 모바일 앱 연결</span> 버튼으로 QR을 발급해 측정을 시작하세요. 측정이 완료되면 결과 시각화가 이곳에 표시됩니다.
              </p>
            </>
          )}
        </div>
      </div>

      <HelpFab />
    </div>
  );
}
