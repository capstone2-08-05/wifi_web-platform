export default function MeasurementPage() {
  return (
    <div className="space-y-6">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">실측·진단</h1>
        <p className="text-sm text-muted-foreground">
          모바일 기기로 측정한 실제 와이파이 품질 데이터와 시뮬레이션을 통합하여 분석합니다.
        </p>
      </header>
      <div className="flex h-[60vh] items-center justify-center rounded-xl border bg-muted/30 text-sm text-muted-foreground">
        (측정 경로 / 히트맵 / 통합 분석 — 실측 API 연결 예정)
      </div>
    </div>
  );
}
