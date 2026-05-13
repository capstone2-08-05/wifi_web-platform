import { Activity, AlertTriangle, ChevronRight, MapPin, QrCode } from 'lucide-react';
import type { PointDiagnosis } from './mocks';

interface Props {
  diagnosis: PointDiagnosis;
  onShowFix?: () => void;
}

const SEVERITY_BADGE: Record<PointDiagnosis['severity'], { bg: string; text: string; label: string }> = {
  bad: { bg: 'bg-red-100', text: 'text-red-600', label: '상태 불량' },
  warning: { bg: 'bg-amber-100', text: 'text-amber-700', label: '주의 필요' },
  good: { bg: 'bg-emerald-100', text: 'text-emerald-700', label: '양호' },
};

export function DiagnosticPanel({ diagnosis, onShowFix }: Props) {
  return (
    <aside className="flex w-90 shrink-0 flex-col gap-4">
      <CombinedDiagnosisCard diagnosis={diagnosis} />
      <CauseAnalysisCard diagnosis={diagnosis} onShowFix={onShowFix} />
      <MobileConnectCard />
    </aside>
  );
}

function CombinedDiagnosisCard({ diagnosis }: { diagnosis: PointDiagnosis }) {
  const badge = SEVERITY_BADGE[diagnosis.severity];
  const measuredColor = diagnosis.severity === 'bad' ? 'text-red-500' : 'text-foreground';

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
            {diagnosis.pointLabel}{' '}
            <span className="text-foreground/70">({diagnosis.pointCode})</span>
          </span>
        </div>
        <span
          className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${badge.bg} ${badge.text}`}
        >
          {badge.label}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 rounded-lg border bg-muted/30 p-3">
        <MetricCompare
          label="예측치 (시뮬레이션)"
          value={`${diagnosis.predictedRssiDbm}`}
          unit="dBm"
        />
        <MetricCompare
          label={`실측치 (${diagnosis.measuredAtLabel})`}
          value={`${diagnosis.measuredRssiDbm}`}
          unit="dBm"
          valueColor={measuredColor}
        />
      </div>

      <div className="mt-4">
        <h4 className="text-xs font-semibold text-foreground/80">상세 품질 지표</h4>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <Metric value={`${diagnosis.latencyMs}ms`} label="지연시간" />
          <Metric value={`${diagnosis.downloadMbps}Mbps`} label="다운로드" />
          <Metric value={diagnosis.bandLabel} label="대역" />
        </div>
      </div>
    </section>
  );
}

function CauseAnalysisCard({
  diagnosis,
  onShowFix,
}: {
  diagnosis: PointDiagnosis;
  onShowFix?: () => void;
}) {
  return (
    <section className="rounded-2xl border bg-background p-5 shadow-sm">
      <header className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-amber-500" strokeWidth={2} />
        <h3 className="text-sm font-bold">원인 분석 및 조치</h3>
      </header>

      <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-[13px] leading-relaxed text-foreground/85">
        {diagnosis.causeText}
      </p>

      <button
        type="button"
        onClick={onShowFix}
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
