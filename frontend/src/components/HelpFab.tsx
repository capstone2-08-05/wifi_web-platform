// 페이지 우하단 고정 도움말 버튼. 대시보드/실측·진단/시뮬레이션에서 공용.
// 실제 도움말 동작은 추후 (예: 채널 안내 모달, 가이드 투어 등) 들어갈 자리.

export function HelpFab({ onClick }: { onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="도움말"
      className="fixed bottom-6 right-6 z-20 flex h-10 w-10 items-center justify-center rounded-full border bg-background text-muted-foreground shadow-md hover:bg-accent hover:text-foreground"
    >
      <span className="text-base font-semibold">?</span>
    </button>
  );
}
