import { ChevronDown, RotateCcw, ScanLine, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface SelectedObject {
  typeLabel: string;
  scanned?: boolean;
  width: number;
  height: number;
  x: number;
  y: number;
  material: string;
  materialHint?: string;
}

interface PropertiesPanelProps {
  selected: SelectedObject | null;
  onChange?: (next: SelectedObject) => void;
  onRotate?: () => void;
  onDelete?: () => void;
}

const MATERIAL_OPTIONS = [
  '목재 테이블 (신호 감쇠 보통)',
  '금속 캐비닛 (신호 감쇠 높음)',
  '유리 (신호 감쇠 낮음)',
  '플라스틱 (신호 감쇠 매우 낮음)',
];

export function PropertiesPanel({
  selected,
  onChange,
  onRotate,
  onDelete,
}: PropertiesPanelProps) {
  return (
    <aside className="flex w-80 shrink-0 flex-col gap-5 overflow-y-auto border-l bg-background p-5">
      <h2 className="text-sm font-semibold tracking-tight text-foreground">
        속성 (선택된 객체)
      </h2>

      {selected ? (
        <SelectedBody
          selected={selected}
          onChange={onChange}
          onRotate={onRotate}
          onDelete={onDelete}
        />
      ) : (
        <EmptyBody />
      )}

      <MobileScanCard />
    </aside>
  );
}

function SelectedBody({
  selected,
  onChange,
  onRotate,
  onDelete,
}: {
  selected: SelectedObject;
  onChange?: (next: SelectedObject) => void;
  onRotate?: () => void;
  onDelete?: () => void;
}) {
  const update = <K extends keyof SelectedObject>(key: K, value: SelectedObject[K]) => {
    onChange?.({ ...selected, [key]: value });
  };

  return (
    <>
      <Section label="객체 유형">
        <div className="flex items-center gap-3 rounded-lg border bg-background p-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/10">
            <span className="block h-3 w-3 rounded-full bg-primary/80" />
          </div>
          <div className="flex-1 space-y-0.5">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-medium text-foreground">
                {selected.typeLabel}
              </span>
              {selected.scanned && (
                <span className="rounded-md bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">
                  스캔됨
                </span>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground">
              마우스로 끌어서 위치/크기 수정
            </p>
          </div>
        </div>
      </Section>

      <Section label="크기 및 위치">
        <div className="grid grid-cols-2 gap-2.5">
          <PxField
            label="가로 (W)"
            value={selected.width}
            onChange={(v) => update('width', v)}
          />
          <PxField
            label="세로 (H)"
            value={selected.height}
            onChange={(v) => update('height', v)}
          />
          <PxField
            label="X 좌표"
            value={selected.x}
            onChange={(v) => update('x', v)}
          />
          <PxField
            label="Y 좌표"
            value={selected.y}
            onChange={(v) => update('y', v)}
          />
        </div>
      </Section>

      <Section label="장애물 재질 설정">
        <div className="relative">
          <select
            value={selected.material}
            onChange={(e) => update('material', e.target.value)}
            className="w-full appearance-none rounded-md border bg-background px-3 py-2.5 pr-9 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {MATERIAL_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
            {/* 현재 값이 옵션 목록에 없을 경우 fallback */}
            {!MATERIAL_OPTIONS.includes(selected.material) && (
              <option value={selected.material}>{selected.material}</option>
            )}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        </div>
        <p className="mt-2 rounded-md bg-primary/5 px-3 py-2 text-[11px] leading-relaxed text-primary/90">
          {selected.materialHint ?? '가구의 재질에 따라 와이파이 품질에 미치는 영향이 달라집니다.'}
        </p>
      </Section>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onRotate}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border bg-background px-3 py-2 text-sm font-medium text-foreground/80 shadow-sm hover:bg-accent"
        >
          <RotateCcw className="h-4 w-4" />
          회전
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-destructive/30 bg-background px-3 py-2 text-sm font-medium text-destructive shadow-sm hover:bg-destructive/5"
        >
          <Trash2 className="h-4 w-4" />
          삭제
        </button>
      </div>
    </>
  );
}

function EmptyBody() {
  return (
    <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-8 text-center">
      <p className="text-sm font-medium text-muted-foreground">
        선택된 객체가 없습니다
      </p>
      <p className="mt-1 text-[11px] text-muted-foreground/80">
        캔버스의 객체를 클릭하면 속성이 표시됩니다.
      </p>
    </div>
  );
}

function MobileScanCard() {
  return (
    <div className="mt-auto rounded-xl bg-primary p-4 text-primary-foreground shadow-sm">
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/15">
          <ScanLine className="h-4 w-4" />
        </div>
        <span className="text-sm font-semibold">모바일 가구 스캔</span>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-primary-foreground/90">
        카메라로 공간을 비추기만 하세요.
        <br />
        가구 크기와 위치를 자동으로 측정합니다.
      </p>
    </div>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold text-foreground/80">{label}</h3>
      {children}
    </div>
  );
}

function PxField({
  label,
  value,
  onChange,
  className,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
  className?: string;
}) {
  return (
    <label className={cn('flex flex-col gap-1.5', className)}>
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <div className="relative">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full rounded-md border bg-background px-2.5 py-1.5 pr-8 text-sm font-medium tabular-nums focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-muted-foreground">
          px
        </span>
      </div>
    </label>
  );
}
