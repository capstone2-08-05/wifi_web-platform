import { Wifi } from 'lucide-react';

// "AP 추가하기" 플로팅 메뉴 (idle 상태에서만 노출).
// 클릭 시 캔버스에 AP 마커를 떨어뜨리는 인터랙션이 들어가야 하지만, 현재는 정적 메뉴.

export function ApPaletteMenu() {
  return (
    <div className="w-32 rounded-xl border bg-background p-3 shadow-md">
      <h4 className="mb-2 text-center text-xs font-semibold text-foreground/80">
        AP 추가하기
      </h4>
      <div className="flex flex-col items-center gap-2.5">
        <ApOption tone="primary" label="일반 AP" />
        <ApOption tone="indigo" label="고성능 AP" />
      </div>
    </div>
  );
}

function ApOption({ tone, label }: { tone: 'primary' | 'indigo'; label: string }) {
  const bg = tone === 'primary' ? 'bg-primary' : 'bg-indigo-600';
  return (
    <button
      type="button"
      className="flex flex-col items-center gap-1 rounded-md p-1.5 hover:bg-accent"
    >
      <div
        className={`flex h-10 w-10 items-center justify-center rounded-full ${bg} text-primary-foreground shadow-sm`}
      >
        <Wifi className="h-4 w-4" />
      </div>
      <span className="text-[11px] font-medium text-foreground/80">{label}</span>
    </button>
  );
}
