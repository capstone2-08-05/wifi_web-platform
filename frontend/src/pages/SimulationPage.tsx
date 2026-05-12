export default function SimulationPage() {
  return (
    <div className="h-full space-y-6 overflow-auto p-6">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">시뮬레이션</h1>
        <p className="text-sm text-muted-foreground">
          저장된 도면을 불러와 가구와 AP를 자유롭게 배치하고 예상 품질을 비교합니다.
        </p>
      </header>
      <div className="flex h-[60vh] items-center justify-center rounded-xl border bg-muted/30 text-sm text-muted-foreground">
        (RF 시뮬레이션 + AP 배치 — RF/AP API 연결 예정)
      </div>
    </div>
  );
}
