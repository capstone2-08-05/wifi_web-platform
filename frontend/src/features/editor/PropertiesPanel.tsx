import { useState } from 'react';
import { Check, ChevronDown, RotateCcw, ScanLine, Sparkles, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { objectTypeLabel, OBJECT_TYPE_OPTIONS, openingTypeLabel } from '@/lib/labels';
import type {
  DraftObject,
  DraftOpening,
  DraftRoom,
  DraftWall,
  SelectedEntityRef,
  SelectedEntityResolved,
} from '@/types/scene';
import type { Material } from '@/types/material';
import type { MaterialHypothesis } from '@/types/material-hypothesis';
import { useMaterials } from '@/hooks/use-materials';
import {
  useSelectMaterialHypothesis,
  useWallMaterialHypotheses,
} from '@/hooks/use-material-hypotheses';

interface PropertiesPanelProps {
  selected: SelectedEntityResolved | null;
  /** 선택된 엔티티 삭제 (백엔드 DELETE 호출). */
  onDelete?: () => void;
  /** 선택된 엔티티 90° 시계방향 회전. 객체(Point) 는 회전 무의미. */
  onRotate?: () => void;
  /** 벽의 material_label 변경. 백엔드 PATCH /draft-walls/{id}. */
  onUpdateMaterial?: (next: string) => void;
  /** 객체의 object_type 변경. 백엔드 PATCH /draft-objects/{id}. */
  onUpdateObjectType?: (next: string) => void;
  /** 객체 위치(X/Y) 변경 — 보류 편집에 저장. */
  onUpdateObjectPosition?: (ref: SelectedEntityRef, x: number, y: number) => void;
  /** 객체 크기(W/H) 변경 — 즉시 PATCH. */
  onUpdateObjectSize?: (ref: SelectedEntityRef, widthM: number, heightM: number) => void;
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

export function PropertiesPanel({
  selected,
  onDelete,
  onRotate,
  onUpdateMaterial,
  onUpdateObjectType,
  onUpdateObjectPosition,
  onUpdateObjectSize,
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
          onUpdateObjectType={onUpdateObjectType}
          onUpdateObjectPosition={onUpdateObjectPosition}
          onUpdateObjectSize={onUpdateObjectSize}
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
  onUpdateObjectType,
  onUpdateObjectPosition,
  onUpdateObjectSize,
  isSaving,
  isDeleting,
}: {
  selected: SelectedEntityResolved;
  onDelete?: () => void;
  onRotate?: () => void;
  onUpdateMaterial?: (next: string) => void;
  onUpdateObjectType?: (next: string) => void;
  onUpdateObjectPosition?: (ref: SelectedEntityRef, x: number, y: number) => void;
  onUpdateObjectSize?: (ref: SelectedEntityRef, widthM: number, heightM: number) => void;
  isSaving: boolean;
  isDeleting: boolean;
}) {
  return (
    <>
      <Section label="객체 유형">
        <TypeHeader selected={selected} />
      </Section>

      {selected.kind !== 'object' && (
        <Section label="속성">
          {selected.kind === 'wall' && <WallFields wall={selected.data} />}
          {selected.kind === 'room' && <RoomFields room={selected.data} />}
          {selected.kind === 'opening' && <OpeningFields opening={selected.data} />}
        </Section>
      )}

      {selected.kind === 'object' && (
        <>
          <Section label="객체 종류 변경">
            <ObjectTypeSelect
              value={selected.data.object_type}
              onChange={onUpdateObjectType}
              disabled={isSaving}
            />
            <p className="mt-2 rounded-md bg-primary/5 px-3 py-2 text-[11px] leading-relaxed text-primary/90">
              AI 가 추정한 종류가 틀렸으면 직접 바꿔주세요.
              {isSaving && ' 저장 중…'}
            </p>
          </Section>

          <ObjectSizePositionSection
            object={selected.data}
            onUpdatePosition={
              onUpdateObjectPosition
                ? (x, y) => onUpdateObjectPosition({ kind: 'object', id: selected.data.id }, x, y)
                : undefined
            }
            onUpdateSize={
              onUpdateObjectSize
                ? (w, h) => onUpdateObjectSize({ kind: 'object', id: selected.data.id }, w, h)
                : undefined
            }
            disabled={isSaving}
          />
        </>
      )}

      {selected.kind === 'wall' && (
        <Section label="장애물 재질 설정">
          <MaterialSelectWired
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

      {selected.kind === 'wall' && (
        <WallHypothesesSection wallId={selected.data.id} />
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
  // 개구부·객체는 generic 라벨 대신 실제 종류를 메인 라벨로 (사용자 친화).
  let label = KIND_LABELS[selected.kind];
  if (selected.kind === 'opening') label = openingTypeLabel(selected.data.opening_type);
  else if (selected.kind === 'object') label = objectTypeLabel(selected.data.object_type);
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
      <Row label="이름" value={room.room_name?.trim() || '-'} />
      <Row label="용도" value={room.room_type ?? '-'} />
    </Grid>
  );
}

function OpeningFields({ opening }: { opening: DraftOpening }) {
  return (
    <Grid>
      <Row label="종류" value={openingTypeLabel(opening.opening_type)} />
      <Row label="너비" value={fmtDecimal(opening.width_m, 'm')} />
      <Row label="높이" value={fmtDecimal(opening.height_m, 'm')} />
      <Row label="소속 벽" value={opening.wall_id ? shortId(opening.wall_id) : '-'} />
    </Grid>
  );
}

function shortId(id: string): string {
  return id.slice(0, 6) + '…';
}

/** 객체 종류 변경 select. value 는 백엔드 enum 값, 표시는 한국어 라벨. */
function ObjectTypeSelect({
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
        {/* 옵션에 없는 현재값(AI 가 낸 미상 종류)도 유지 */}
        {value && !OBJECT_TYPE_OPTIONS.includes(value) && (
          <option value={value}>{objectTypeLabel(value)}</option>
        )}
        {OBJECT_TYPE_OPTIONS.map((t) => (
          <option key={t} value={t}>
            {objectTypeLabel(t)}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}

/**
 * 객체 위치(X/Y) + 크기(W/H) 입력 섹션.
 * 입력 또는 캔버스 드래그가 부모(EditorPage)의 보류 편집 상태를 업데이트하고,
 * "저장" 버튼을 눌러야 백엔드에 PATCH. "취소"로 폐기.
 * 표시되는 값은 항상 보류 편집이 반영된 object props.
 */
function ObjectSizePositionSection({
  object,
  onUpdatePosition,
  onUpdateSize,
  disabled,
}: {
  object: DraftObject;
  onUpdatePosition?: (x: number, y: number) => void;
  onUpdateSize?: (widthM: number, heightM: number) => void;
  disabled?: boolean;
}) {
  const point = extractPoint(object.point_geom);
  const meta = (object.metadata_json ?? {}) as Record<string, unknown>;
  // metadata 에 저장된 값이 없으면 캔버스 기본 박스 크기(1.6m)를 표시 — 캔버스와 일관성 유지.
  const SPACE_DEFAULT_SIZE_M = 1.6;
  const widthM = typeof meta.width_m === 'number' ? meta.width_m : SPACE_DEFAULT_SIZE_M;
  const heightM = typeof meta.height_m === 'number' ? meta.height_m : SPACE_DEFAULT_SIZE_M;

  return (
    <Section label="크기 및 위치">
      <div className="grid grid-cols-2 gap-2">
        <NumberInputBound
          label="가로 (W)"
          value={widthM}
          unit="m"
          step={0.1}
          min={0.2}
          disabled={disabled || !onUpdateSize}
          onCommit={(next) => onUpdateSize?.(next, heightM ?? next)}
        />
        <NumberInputBound
          label="세로 (H)"
          value={heightM}
          unit="m"
          step={0.1}
          min={0.2}
          disabled={disabled || !onUpdateSize}
          onCommit={(next) => onUpdateSize?.(widthM ?? next, next)}
        />
        <NumberInputBound
          label="X 좌표"
          value={point?.[0] ?? null}
          unit="m"
          step={0.1}
          disabled={disabled || !onUpdatePosition || !point}
          onCommit={(next) => point && onUpdatePosition?.(next, point[1])}
        />
        <NumberInputBound
          label="Y 좌표"
          value={point?.[1] ?? null}
          unit="m"
          step={0.1}
          disabled={disabled || !onUpdatePosition || !point}
          onCommit={(next) => point && onUpdatePosition?.(point[0], next)}
        />
      </div>

    </Section>
  );
}

/** 외부 값에 묶이는 숫자 입력 — 외부 값 변경 시 자동 동기화, blur/Enter 시 commit. */
function NumberInputBound({
  label,
  value,
  unit,
  step,
  min,
  disabled,
  onCommit,
}: {
  label: string;
  value: number | null;
  unit?: string;
  step?: number;
  min?: number;
  disabled?: boolean;
  onCommit?: (next: number) => void;
}) {
  const [draft, setDraft] = useState<string>(value != null ? value.toFixed(2) : '');
  // 외부 value 가 바뀌면 draft 동기화 — useEffect 대신 render-time 비교 (cascading render 회피).
  const [prevValue, setPrevValue] = useState(value);
  if (prevValue !== value) {
    setPrevValue(value);
    setDraft(value != null ? value.toFixed(2) : '');
  }

  const commit = () => {
    const n = Number(draft);
    if (!Number.isFinite(n)) {
      setDraft(value != null ? value.toFixed(2) : '');
      return;
    }
    const clamped = min != null && n < min ? min : n;
    if (value != null && Math.abs(clamped - value) < 1e-6) return;
    onCommit?.(clamped);
  };

  const handleChange = (next: string) => {
    setDraft(next);
    // 유효 숫자면 즉시 commit (캔버스에서 실시간 반영). 빈 문자열·NaN 은 무시.
    if (next.trim() === '') return;
    const n = Number(next);
    if (!Number.isFinite(n)) return;
    const clamped = min != null && n < min ? min : n;
    if (value != null && Math.abs(clamped - value) < 1e-6) return;
    onCommit?.(clamped);
  };

  return (
    <label className="block rounded-md border bg-background px-2.5 py-1.5">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <div className="mt-0.5 flex items-baseline gap-1">
        <input
          type="number"
          inputMode="decimal"
          step={step ?? 0.01}
          value={draft}
          disabled={disabled}
          onChange={(e) => handleChange(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              commit();
            }
          }}
          className="w-full bg-transparent text-base font-semibold tabular-nums outline-none disabled:cursor-not-allowed disabled:opacity-50"
        />
        {unit && <span className="text-[11px] text-muted-foreground">{unit}</span>}
      </div>
    </label>
  );
}

function extractPoint(geom: Record<string, unknown> | null | undefined): [number, number] | null {
  if (!geom) return null;
  const coords = (geom as { coordinates?: unknown }).coordinates;
  if (Array.isArray(coords) && coords.length >= 2) {
    const x = Number(coords[0]);
    const y = Number(coords[1]);
    if (Number.isFinite(x) && Number.isFinite(y)) return [x, y];
  }
  return null;
}

/**
 * 백엔드 §12.1 GET /materials 결과를 옵션으로 사용.
 * 로딩 중이거나 비어있으면 fallback 옵션으로 동작.
 */
function MaterialSelectWired({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange?: (next: string) => void;
  disabled?: boolean;
}) {
  const { data: materials, isLoading } = useMaterials();
  return (
    <MaterialSelect
      value={value}
      onChange={onChange}
      disabled={disabled || isLoading || !onChange}
      materials={materials ?? []}
      sourceLabel={
        materials && materials.length > 0
          ? '백엔드 재질 DB'
          : isLoading
          ? '재질 목록 불러오는 중...'
          : '기본 재질 목록 사용 (백엔드 비어있음)'
      }
    />
  );
}

/** 현재 값(예: AI 가 넣은 "concrete") 이 material_code 와 매칭되면 material_name 으로 정규화. */
function normalizeMaterialValue(value: string, materials: Material[]): string {
  if (!value) return value;
  // 이미 material_name 과 일치하면 그대로
  if (materials.some((m) => m.material_name === value)) return value;
  // material_code 매칭 → 한글 이름으로 변환
  const matched = materials.find(
    (m) => m.material_code?.toLowerCase() === value.toLowerCase(),
  );
  return matched ? matched.material_name : value;
}

function MaterialSelect({
  value,
  onChange,
  disabled,
  materials,
  sourceLabel,
}: {
  value: string;
  onChange?: (next: string) => void;
  disabled?: boolean;
  materials: Material[];
  sourceLabel?: string;
}) {
  const normalizedValue = normalizeMaterialValue(value, materials);
  const optionNames = materials.map((m) => m.material_name);
  const showRawValue = !!normalizedValue && !optionNames.includes(normalizedValue);
  return (
    <div className="relative">
      <select
        value={normalizedValue}
        onChange={(e) => onChange?.(e.target.value)}
        disabled={disabled || !onChange}
        className="w-full appearance-none rounded-md border bg-background px-3 py-2.5 pr-9 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-70"
      >
        {showRawValue && <option value={normalizedValue}>{normalizedValue}</option>}
        {optionNames.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
        {!normalizedValue && <option value="">재질 미지정</option>}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      {sourceLabel && (
        <p className="mt-1 text-[10px] text-muted-foreground/80">{sourceLabel}</p>
      )}
    </div>
  );
}

/**
 * §12.3 — 벽의 자동 추출된 재질 후보 목록.
 * 백엔드는 *확정본 Wall* 기준이라 Draft 단계에선 빈 응답 가능.
 * 비어있거나 에러면 섹션 자체를 안 보임 (조용히 graceful 처리).
 */
function WallHypothesesSection({ wallId }: { wallId: string }) {
  const { data, isError } = useWallMaterialHypotheses(wallId);
  const select = useSelectMaterialHypothesis();

  if (isError || !data || data.length === 0) return null;

  return (
    <Section label="추출된 재질 후보">
      <ul className="space-y-1.5">
        {data.map((h) => (
          <HypothesisRow
            key={h.id}
            hypothesis={h}
            onSelect={() => select.mutate(h.id)}
            disabled={select.isPending}
          />
        ))}
      </ul>
      <p className="mt-2 text-[10px] text-muted-foreground/80">
        AI 가 추출한 후보. 클릭하면 해당 후보로 확정됩니다.
      </p>
    </Section>
  );
}

function HypothesisRow({
  hypothesis,
  onSelect,
  disabled,
}: {
  hypothesis: MaterialHypothesis;
  onSelect: () => void;
  disabled: boolean;
}) {
  const confidence = parseConfidencePercent(hypothesis.confidence);
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        disabled={disabled || hypothesis.is_selected}
        className={cn(
          'flex w-full items-center justify-between gap-2 rounded-md border bg-background px-3 py-2 text-left text-sm shadow-sm transition-colors hover:bg-accent disabled:cursor-not-allowed',
          hypothesis.is_selected && 'border-primary/40 bg-primary/5 disabled:opacity-100',
        )}
      >
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{hypothesis.material_name}</p>
          {confidence != null && (
            <p className="text-[11px] text-muted-foreground">신뢰도 {confidence}%</p>
          )}
        </div>
        {hypothesis.is_selected ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
            <Check className="h-3 w-3" />
            적용됨
          </span>
        ) : (
          <Sparkles className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
      </button>
    </li>
  );
}

function parseConfidencePercent(value: string | null): number | null {
  if (value == null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.round(n * 100);
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
    // 개구부·객체는 메인 라벨이 이미 종류('문'/'창문'/'가구'…) 라 sub 태그 생략.
    case 'opening':
      return null;
    case 'object':
      return null;
  }
}
