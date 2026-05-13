import { Activity, AlertTriangle, ChevronRight, MapPin, QrCode } from 'lucide-react';

// 우측 진단 패널 - 선택된 측정 포인트의 예측치/실측치 비교, 상세지표, 원인 분석 mock.
// 실제로는 GET /measurement-sessions/{id}/points + simulated value 조합으로 채워질 예정.

export function DiagnosticPanel() {
  return (
    <aside className="flex w-90 shrink-0 flex-col gap-4">
      <CombinedDiagnosisCard />
      <CauseAnalysisCard />
      <MobileConnectCard />
    </aside>
  );
}

function CombinedDiagnosisCard() {
  return (
    <section className="rounded-2xl border bg-background p-5 shadow-sm">
      <header className="mb-4 flex items-center gap-2">
        <Activity className="h-4 w-4 text-primary" strokeWidth={2} />
        <h3 className="text-sm font-bold">예측·실측 통합 진단</h3>
      </header>

      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <MapPin className="h-4 w-4 text-red-500" />
          <span className="text-base font-bold">
            창고 앞 구석 <span className="text-foreground/70">(P-05)</span>
          </span>
        </div>
        <span className="shrink-0 rounded-full bg-red-100 px-2.5 py-1 text-[11px] font-semibold text-red-600">
          상태 불량
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 rounded-lg border bg-muted/30 p-3">
        <MetricCompare label="예측치 (시뮬레이션)" value="-72" unit="dBm" />
        <MetricCompare label="실측치 (어제 15:00)" value="-84" unit="dBm" valueColor="text-red-500" />
      </div>

      <div className="mt-4">
        <h4 className="text-xs font-semibold text-foreground/80">상세 품질 지표</h4>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <Metric value="55ms" label="지연시간" />
          <Metric value="4.2Mbps" label="다운로드" />
          <Metric value="2.4GHz" label="대역" />
        </div>
      </div>
    </section>
  );
}

function CauseAnalysisCard() {
  return (
    <section className="rounded-2xl border bg-background p-5 shadow-sm">
      <header className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-amber-500" strokeWidth={2} />
        <h3 className="text-sm font-bold">원인 분석 및 조치</h3>
      </header>

      <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-[13px] leading-relaxed text-foreground/85">
        예측보다 실측 수치가 훨씬 낮습니다. 창고 가벽의 전파 흡수율이 예상보다
        높거나, 주변에 전파 간섭을 일으키는 금속성 물체가 있을 수 있습니다.
      </p>

      <button
        type="button"
        className="mt-4 inline-flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-sm font-medium text-foreground/80 hover:bg-accent"
      >
        조치 방법 확인하기
        <ChevronRight className="h-4 w-4" />
      </button>
    </section>
  );
}

function MobileConnectCard() {
  return (
    <section className="rounded-2xl border bg-background p-5 shadow-sm">
      <header className="flex items-center gap-2">
        <QrCode className="h-4 w-4 text-primary" strokeWidth={2} />
        <h3 className="text-sm font-bold">모바일 기기 연결</h3>
      </header>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        새로운 실측을 시작하려면 모바일 앱에서 QR 코드를 스캔해주세요.
      </p>
    </section>
  );
}

function MetricCompare({
  label,
  value,
  unit,
  valueColor,
}: {
  label: string;
  value: string;
  unit: string;
  valueColor?: string;
}) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-bold">
        <span className={valueColor}>{value}</span>
        <span className="ml-1 text-[12px] font-medium text-muted-foreground">{unit}</span>
      </p>
    </div>
  );
}

function Metric({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-md border bg-background p-2 text-center">
      <p className="text-[13px] font-bold">{value}</p>
      <p className="mt-0.5 text-[10px] text-muted-foreground">{label}</p>
    </div>
  );
}
