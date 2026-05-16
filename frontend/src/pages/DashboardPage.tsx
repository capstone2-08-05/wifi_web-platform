import { Link } from 'react-router-dom';
import {
  Activity,
  ChevronRight,
  ImageOff,
  Loader2,
  Map,
  Radio,
  Smartphone,
  type LucideIcon,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { HelpFab } from '@/components/HelpFab';
import { cn } from '@/lib/utils';
import { useAppStore } from '@/stores/app-store';
import { useFloorVersions, useSceneVersion } from '@/hooks/use-scene-version';
import { useAssetDownloadUrl, useFloorAssets } from '@/hooks/use-assets';
import { useLocalFloorplanImage } from '@/hooks/use-local-floorplan-image';
import { DraftSceneCanvas } from '@/features/editor/DraftSceneCanvas';
import { versionToDraftShape } from '@/features/editor/version-as-draft';

type Tone = 'blue' | 'purple' | 'green';

const TONE: Record<
  Tone,
  { iconBg: string; iconText: string; hoverBg: string; hoverBorder: string }
> = {
  blue: {
    iconBg: 'bg-blue-100',
    iconText: 'text-blue-600',
    hoverBg: 'hover:bg-blue-50',
    hoverBorder: 'hover:border-blue-300',
  },
  purple: {
    iconBg: 'bg-purple-100',
    iconText: 'text-purple-600',
    hoverBg: 'hover:bg-purple-50',
    hoverBorder: 'hover:border-purple-300',
  },
  green: {
    iconBg: 'bg-emerald-100',
    iconText: 'text-emerald-600',
    hoverBg: 'hover:bg-emerald-50',
    hoverBorder: 'hover:border-emerald-300',
  },
};

const QUICK_ACTIONS = [
  {
    to: '/mobile',
    icon: Smartphone,
    label: '현장 모바일 앱 연결',
    sub: 'QR 스캔으로 기기 연동',
    tone: 'blue',
  },
  {
    to: '/editor',
    icon: Map,
    label: '공간 및 가구 편집',
    sub: '도면 수정 및 장애물 배치',
    tone: 'purple',
  },
  {
    to: '/simulation',
    icon: Radio,
    label: '품질 시뮬레이션',
    sub: '가상 AP 배치 및 커버리지 확인',
    tone: 'green',
  },
] as const satisfies ReadonlyArray<{
  to: string;
  icon: LucideIcon;
  label: string;
  sub: string;
  tone: Tone;
}>;

export default function DashboardPage() {
  const projectId = useAppStore((s) => s.selectedProjectId);
  const floorId = useAppStore((s) => s.selectedFloorId);
  const hasFloorSelected = !!projectId && !!floorId;
  const versionsQuery = useFloorVersions(floorId);
  const currentVersion =
    versionsQuery.data?.find((v) => v.is_current) ?? versionsQuery.data?.[0] ?? null;
  const versionDetailQuery = useSceneVersion(currentVersion?.id ?? null);
  const versionAsDraft = versionDetailQuery.data
    ? versionToDraftShape(versionDetailQuery.data)
    : null;
  // Asset.storage_url 이 s3:// URI 라서 직접 못 쓰고, /download-url 로 presigned 받음.
  const sourceAssetId = versionAsDraft?.source_asset_id ?? null;
  const floorAssetsQuery = useFloorAssets(floorId, 'floorplan');
  const fallbackAsset = (floorAssetsQuery.data ?? [])
    .slice()
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  const effectiveAssetId = sourceAssetId ?? fallbackAsset?.id ?? null;
  const assetUrlQuery = useAssetDownloadUrl(effectiveAssetId);
  const localImage = useLocalFloorplanImage(floorId);
  const backgroundImageUrl =
    assetUrlQuery.data?.url ?? localImage ?? null;

  return (
    <div className="relative h-full overflow-auto p-6">
      <div className="space-y-6">
        <header className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">대시보드</h1>
          <p className="text-sm text-muted-foreground">
            현장 앱과 연동된 매장 도면 및 최신 진단 내역을 확인하세요.
          </p>
        </header>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_minmax(320px,1fr)]">
          <Card title="현재 작업 중인 도면" className="min-h-140">
            <div className="h-120">
              {!hasFloorSelected ? (
                <FloorEmptyState hasProject={!!projectId} />
              ) : !currentVersion ? (
                <FloorNotConfirmedState />
              ) : versionDetailQuery.isLoading ? (
                <FloorLoadingState />
              ) : versionAsDraft ? (
                <div className="relative flex h-full overflow-hidden rounded-md border bg-background">
                  <div className="pointer-events-none flex-1">
                    <DraftSceneCanvas
                      draft={versionAsDraft}
                      selectedRef={null}
                      onSelect={() => {}}
                      onDragEnd={() => {}}
                      tool="select"
                      onCreate={() => {}}
                      backgroundImageUrl={backgroundImageUrl}
                    />
                  </div>
                  <div className="pointer-events-none absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-md bg-card/90 px-2.5 py-1 text-[11px] font-medium shadow-sm backdrop-blur">
                    <Map className="h-3 w-3 text-primary" />
                    버전 #{currentVersion.version_no} · 미리보기
                  </div>
                </div>
              ) : (
                <FloorConfirmedState />
              )}
            </div>
          </Card>

          <div className="space-y-6">
            <Card title="빠른 실행">
              <ul className="space-y-3">
                {QUICK_ACTIONS.map((a) => (
                  <QuickAction key={a.to} {...a} />
                ))}
              </ul>
            </Card>

            <Card title="현장 앱 최근 진단">
              <DiagnosticsEmptyState />
            </Card>
          </div>
        </div>
      </div>

      <HelpFab />
    </div>
  );
}

function QuickAction({
  to,
  icon: Icon,
  label,
  sub,
  tone,
}: {
  to: string;
  icon: LucideIcon;
  label: string;
  sub: string;
  tone: Tone;
}) {
  const t = TONE[tone];
  return (
    <li>
      <Link
        to={to}
        className={cn(
          'flex items-center gap-3 rounded-md border bg-background p-3 transition-colors',
          t.hoverBg,
          t.hoverBorder,
        )}
      >
        <div
          className={cn(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-md',
            t.iconBg,
            t.iconText,
          )}
        >
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1">
          <div className="text-sm font-medium">{label}</div>
          <div className="text-xs text-muted-foreground">{sub}</div>
        </div>
        <ChevronRight className="h-4 w-4 text-muted-foreground" />
      </Link>
    </li>
  );
}

function FloorEmptyState({ hasProject }: { hasProject: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-md border border-dashed bg-muted/20 p-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
        <ImageOff className="h-5 w-5 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">
        {hasProject ? '층을 선택해주세요' : '프로젝트를 먼저 선택해주세요'}
      </p>
      <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
        상단 셀렉터에서 작업할 도면(층)을 선택하면 현재 작업 중인 도면 미리보기가 표시됩니다.
      </p>
    </div>
  );
}

function FloorLoadingState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 rounded-md border border-dashed bg-muted/20 p-8 text-center">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      <p className="text-xs text-muted-foreground">도면을 불러오는 중...</p>
    </div>
  );
}

function FloorNotConfirmedState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-md border border-dashed bg-muted/20 p-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
        <Map className="h-5 w-5 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">아직 확정된 도면이 없습니다</p>
      <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
        공간 편집에서 도면을 업로드하고 AI 분석 후 저장하면 이곳에 미리보기가 표시됩니다.
      </p>
      <Link
        to="/editor"
        className="mt-2 inline-flex items-center gap-1 rounded-md border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
      >
        공간 편집으로 이동
        <ChevronRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

function FloorConfirmedState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-md border border-dashed bg-muted/20 p-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100">
        <Map className="h-5 w-5 text-emerald-600" />
      </div>
      <p className="text-sm font-medium">도면이 확정되어 있습니다</p>
      <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
        공간 편집에서 도형을 수정하거나 시뮬레이션을 실행해 품질을 확인하세요.
      </p>
      <div className="mt-2 flex gap-2">
        <Link
          to="/editor"
          className="inline-flex items-center gap-1 rounded-md border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
        >
          공간 편집
          <ChevronRight className="h-3.5 w-3.5" />
        </Link>
        <Link
          to="/simulation"
          className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
        >
          시뮬레이션
          <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}

function DiagnosticsEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-6 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
        <Activity className="h-4 w-4 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">진단된 내역이 없습니다</p>
      <p className="max-w-xs text-[11px] leading-relaxed text-muted-foreground">
        모바일 앱으로 현장을 측정하면 이곳에 신호 약점 / 이상 구역이 표시됩니다.
      </p>
    </div>
  );
}

