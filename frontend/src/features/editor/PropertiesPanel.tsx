import { ChevronDown, RotateCcw, ScanLine, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type {
  DraftObject,
  DraftOpening,
  DraftRoom,
  DraftWall,
  SelectedEntityResolved,
} from '@/types/scene';

interface PropertiesPanelProps {
  selected: SelectedEntityResolved | null;
  /** 선택된 엔티티 삭제 (백엔드 DELETE 호출). */
  onDelete?: () => void;
  /** 선택된 엔티티 90° 시계방향 회전. 객체(Point) 는 회전 무의미. */
  onRotate?: () => void;
  /** 벽의 material_label 변경. 백엔드 PATCH /draft-walls/{id}. */
  onUpdateMaterial?: (next: string) => void;
  /** 작업 진행 중 표시 */
  isSaving?: boolean;
  isDeleting?: boolean;
}

const KIND_LABELS: Record<SelectedEntityResolved['kind'], string> = {
  wall: '벽',
  room: '방',
  opening: '개구부',
  object: '객체',
};

const MATERIAL_OPTIONS = [
  '목재 테이블 (신호 감쇠 보통)',
  '금속 캐비닛 (신호 감쇠 높음)',
  '유리 (신호 감쇠 낮음)',
  '플라스틱 (신호 감쇠 매우 낮음)',
  '콘크리트 벽 (신호 감쇠 매우 높음)',
];

export function PropertiesPanel({
  selected,
  onDelete,
  onRotate,
  onUpdateMaterial,
  isSaving,
  isDeleting,
}: PropertiesPanelProps) {
  return (
    <aside className="flex w-80 shrink-0 flex-col gap-5 overflow-y-auto border-l bg-background p-5">
      <h2 className="text-sm font-semibold tracking-tight text-foreground">
        속성 (선택된 객체)
      </h2>

      {selected ? (
        <SelectedBody
          selected={selected}
          onDelete={onDelete}
          onRotate={onRotate}
          onUpdateMaterial={onUpdateMaterial}
          isSaving={!!isSaving}
          isDeleting={!!isDeleting}
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
  onDelete,
  onRotate,
  onUpdateMaterial,
  isSaving,
  isDeleting,
}: {
  selected: SelectedEntityResolved;
  onDelete?: () => void;
  onRotate?: () => void;
  onUpdateMaterial?: (next: string) => void;
  isSaving: boolean;
  isDeleting: boolean;
}) {
  return (
    <>
      <Section label="객체 유형">
        <TypeHeader selected={selected} />
      </Section>

      <Section label="속성">
        {selected.kind === 'wall' && <WallFields wall={selected.data} />}
        {selected.kind === 'room' && <RoomFields room={selected.data} />}
        {selected.kind === 'opening' && <OpeningFields opening={selected.data} />}
        {selected.kind === 'object' && <ObjectFields object={selected.data} />}
      </Section>

      {selected.kind === 'wall' && (
        <Section label="장애물 재질 설정">
          <MaterialSelect
            value={getMaterial(selected)}
            onChange={onUpdateMaterial}
            disabled={isSaving}
          />
          <p className="mt-2 rounded-md bg-primary/5 px-3 py-2 text-[11px] leading-relaxed text-primary/90">
            재질에 따라 와이파이 품질에 미치는 영향이 달라집니다.
            {isSaving && ' 저장 중…'}
          </p>
        </Section>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onRotate}
          disabled={isSaving || !onRotate || selected.kind === 'object'}
          title={
            selected.kind === 'object'
              ? '점 객체는 회전이 적용되지 않습니다'
              : '90° 시계방향 회전'
          }
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border bg-background px-3 py-2 text-sm font-medium text-foreground/80 shadow-sm hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RotateCcw className="h-4 w-4" />
          {isSaving ? '회전 중…' : '회전 90°'}
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={isDeleting || !onDelete}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-destructive/30 bg-background px-3 py-2 text-sm font-medium text-destructive shadow-sm hover:bg-destructive/5 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Trash2 className="h-4 w-4" />
          {isDeleting ? '삭제 중…' : '삭제'}
        </button>
      </div>

      <div className="rounded-md bg-muted/40 p-3">
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">ID</p>
        <p className="mt-0.5 break-all font-mono text-[11px]">{getEntityId(selected)}</p>
      </div>
    </>
  );
}

function TypeHeader({ selected }: { selected: SelectedEntityResolved }) {
  const label = KIND_LABELS[selected.kind];
  const subLabel = getEntitySubLabel(selected);
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-background p-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/10">
        <span className="block h-3 w-3 rounded-full bg-primary/80" />
      </div>
      <div className="flex-1 space-y-0.5">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-foreground">{label}</span>
          {subLabel && (
            <span className="rounded-md bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">
              {subLabel}
            </span>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground">캔버스에서 클릭으로 선택됨</p>
      </div>
    </div>
  );
}

function WallFields({ wall }: { wall: DraftWall }) {
  return (
    <Grid>
      <Row label="역할" value={wall.wall_role} />
      <Row label="두께" value={fmtDecimal(wall.thickness_m, 'm')} />
      <Row label="높이" value={fmtDecimal(wall.height_m, 'm')} />
      <Row label="재질" value={wall.material_label ?? '-'} />
      <Row label="신뢰도" value={fmtConfidence(wall.confidence)} />
    </Grid>
  );
}

function RoomFields({ room }: { room: DraftRoom }) {
  return (
    <Grid>
      <Row label="이름" value={room.room_name ?? '-'} />
      <Row label="용도" value={room.room_type ?? '-'} />
      <Row label="신뢰도" value={fmtConfidence(room.confidence)} />
    </Grid>
  );
}

function OpeningFields({ opening }: { opening: DraftOpening }) {
  return (
    <Grid>
      <Row label="종류" value={opening.opening_type} />
      <Row label="너비" value={fmtDecimal(opening.width_m, 'm')} />
      <Row label="높이" value={fmtDecimal(opening.height_m, 'm')} />
      <Row label="턱 높이" value={fmtDecimal(opening.sill_height_m, 'm')} />
      <Row label="신뢰도" value={fmtConfidence(opening.confidence)} />
    </Grid>
  );
}

function ObjectFields({ object }: { object: DraftObject }) {
  return (
    <Grid>
      <Row label="종류" value={object.object_type} />
      <Row label="높이" value={fmtDecimal(object.z_m, 'm')} />
      <Row label="신뢰도" value={fmtConfidence(object.confidence)} />
    </Grid>
  );
}

function MaterialSelect({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange?: (next: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        disabled={disabled || !onChange}
        className="w-full appearance-none rounded-md border bg-background px-3 py-2.5 pr-9 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-70"
      >
        {!MATERIAL_OPTIONS.includes(value) && value && (
          <option value={value}>{value}</option>
        )}
        {MATERIAL_OPTIONS.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
        {!value && <option value="">재질 미지정</option>}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}

function EmptyBody() {
  return (
    <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-8 text-center">
      <p className="text-sm font-medium text-muted-foreground">
        선택된 객체가 없습니다
      </p>
      <p className="mt-1 text-[11px] text-muted-foreground/80">
        캔버스의 도형을 클릭하면 속성이 표시됩니다.
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

function Grid({ children }: { children: React.ReactNode }) {
  return <dl className="space-y-1 rounded-md border bg-background/60 p-3">{children}</dl>;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b py-1.5 last:border-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className={cn('text-sm font-medium tabular-nums', value === '-' && 'text-muted-foreground')}>
        {value}
      </dd>
    </div>
  );
}

// ============================================
// helpers
// ============================================

function fmtDecimal(value: string | null | undefined, unit = ''): string {
  if (value == null || value === '') return '-';
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return `${n.toFixed(2)}${unit ? ' ' + unit : ''}`;
}

function fmtConfidence(value: string | null | undefined): string {
  if (value == null) return '-';
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return `${Math.round(n * 100)}%`;
}

function getMaterial(selected: SelectedEntityResolved): string {
  if (selected.kind === 'wall') return selected.data.material_label ?? '';
  if (selected.kind === 'object') {
    const raw = selected.data.metadata_json as { raw?: { material?: string } };
    return raw?.raw?.material ?? '';
  }
  return '';
}

function getEntityId(selected: SelectedEntityResolved): string {
  return selected.data.id;
}

function getEntitySubLabel(selected: SelectedEntityResolved): string | null {
  switch (selected.kind) {
    case 'wall':
      return selected.data.wall_role || null;
    case 'room':
      return selected.data.room_type || null;
    case 'opening':
      return selected.data.opening_type;
    case 'object':
      return selected.data.object_type;
  }
}
