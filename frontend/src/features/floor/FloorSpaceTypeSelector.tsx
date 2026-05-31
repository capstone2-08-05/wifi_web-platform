/**
 * Floor.space_type 을 읽고 변경하는 dropdown 위젯 — source of truth 는 backend Floor.
 *
 * 시뮬 페이지 / 측정 페이지 등 여러 곳에서 같은 UX 로 노출. 어디서 바꿔도 Floor 가
 * 즉시 업데이트 → 다음 calibration 이 자동으로 그 값을 prior 로 사용.
 *
 * 사용:
 *   <FloorSpaceTypeSelector floorId={...} projectId={...} />
 */
import { useEffect, useState } from 'react';
import { Building2 } from 'lucide-react';
import { useFloors, useUpdateFloor } from '@/hooks/use-floors';
import type { SpaceType } from '@/types/calibration-run';
import { cn } from '@/lib/utils';

const SPACE_TYPE_OPTIONS: { value: SpaceType; label: string }[] = [
  { value: 'unknown', label: '미지정' },
  { value: 'cafe', label: '카페' },
  { value: 'study_room', label: '스터디룸' },
  { value: 'classroom', label: '강의실' },
  { value: 'office', label: '오피스' },
  { value: 'residential', label: '원룸/주거' },
];

interface Props {
  floorId: string | null;
  projectId: string | null;
  /** 추가 클래스 (배치 보조). */
  className?: string;
  /** select 요소 전용 클래스. */
  selectClassName?: string;
  /** 라벨 표시 여부 — compact 모드면 false. */
  showLabel?: boolean;
}

export function FloorSpaceTypeSelector({
  floorId,
  projectId,
  className,
  selectClassName,
  showLabel = true,
}: Props) {
  const floorsQuery = useFloors(projectId);
  const updateFloor = useUpdateFloor(projectId);
  const currentFloor = floorsQuery.data?.find((f) => f.id === floorId) ?? null;
  // 로컬 state 로 즉시 반영 (optimistic) — onChange 시 서버에도 PATCH.
  const [value, setValue] = useState<SpaceType>(currentFloor?.space_type ?? 'unknown');
  useEffect(() => {
    setValue(currentFloor?.space_type ?? 'unknown');
  }, [currentFloor?.space_type]);

  const disabled = !floorId || !projectId || updateFloor.isPending;

  const handleChange = (next: SpaceType) => {
    if (!floorId) return;
    setValue(next);  // 즉시 UI 반영
    updateFloor.mutate({ id: floorId, body: { space_type: next } });
  };

  return (
    <div className={'inline-flex items-center gap-1.5 ' + (className ?? '')}>
      {showLabel && (
        <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
          <Building2 className="h-3.5 w-3.5" />
          공간 유형
        </span>
      )}
      <select
        value={value}
        onChange={(e) => handleChange(e.target.value as SpaceType)}
        disabled={disabled}
        title="이 도면(층) 의 공간 유형 — calibration 보정의 초기 가정에 사용. 변경시 즉시 저장."
        className={cn(
          selectClassName ??
            'rounded-md border bg-background px-2.5 py-1.5 text-xs font-medium shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-50',
        )}
      >
        {SPACE_TYPE_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
