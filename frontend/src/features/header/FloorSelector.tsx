import { useEffect, useState } from 'react';
import { Check, ChevronDown, Pencil, Plus, Trash2 } from 'lucide-react';
import { Popover } from '@/components/ui/Popover';
import {
  useCreateFloor,
  useDeleteFloor,
  useFloors,
  useUpdateFloor,
} from '@/hooks/use-floors';
import { useAppStore } from '@/stores/app-store';
import { cn } from '@/lib/utils';
import type { Floor } from '@/types/floor';

export function FloorSelector() {
  const projectId = useAppStore((s) => s.selectedProjectId);
  const selectedFloorId = useAppStore((s) => s.selectedFloorId);
  const setFloor = useAppStore((s) => s.setFloor);
  const { data: floors = [], isLoading } = useFloors(projectId);

  const selected = floors.find((f) => f.id === selectedFloorId) ?? null;

  // Auto-select first floor when project changes and we don't have one selected.
  useEffect(() => {
    if (projectId && !selectedFloorId && floors.length > 0) {
      setFloor(floors[0].id);
    }
  }, [projectId, selectedFloorId, floors, setFloor]);

  const disabled = !projectId;

  return (
    <Popover
      contentClassName="w-72 p-0"
      trigger={({ toggle }) => (
        <button
          onClick={() => !disabled && toggle()}
          disabled={disabled}
          className="flex min-w-32 items-center justify-between rounded-md border bg-background px-3 py-2 text-sm hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-background"
        >
          <div className="flex flex-col items-start">
            <span className="text-[10px] text-muted-foreground">도면(층)</span>
            <span className="truncate font-medium">
              {disabled
                ? '프로젝트 선택 필요'
                : isLoading
                  ? '불러오는 중…'
                  : (selected?.floor_name ?? '층 선택')}
            </span>
          </div>
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        </button>
      )}
    >
      {({ close }) => (
        <FloorMenu
          floors={floors}
          selectedFloorId={selectedFloorId}
          projectId={projectId!}
          onSelect={(id) => {
            setFloor(id);
            close();
          }}
          onCreated={(f) => {
            setFloor(f.id);
            close();
          }}
          onDeleted={(deletedId) => {
            // 현재 선택된 층이 삭제됐으면, 남은 첫 층으로 자동 전환 (없으면 null).
            if (deletedId === selectedFloorId) {
              const remaining = floors.filter((f) => f.id !== deletedId);
              setFloor(remaining[0]?.id ?? null);
            }
          }}
        />
      )}
    </Popover>
  );
}

function FloorMenu({
  floors,
  selectedFloorId,
  projectId,
  onSelect,
  onCreated,
  onDeleted,
}: {
  floors: Floor[];
  selectedFloorId: string | null;
  projectId: string;
  onSelect: (id: string) => void;
  onCreated: (f: Floor) => void;
  onDeleted: (deletedId: string) => void;
}) {
  const [creating, setCreating] = useState(false);
  // 인라인 삭제 확인 상태. 두 번째 클릭에 진짜 삭제 — 모달 없이 가볍게.
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  // 인라인 편집 상태. ✏️ 클릭 시 폼 노출.
  const [editingId, setEditingId] = useState<string | null>(null);
  const deleteFloor = useDeleteFloor(projectId);
  const updateFloor = useUpdateFloor(projectId);
  const sorted = [...floors].sort((a, b) => a.floor_order - b.floor_order);

  const handleDeleteClick = (e: React.MouseEvent, floorId: string) => {
    e.stopPropagation();
    if (confirmingDeleteId !== floorId) {
      setConfirmingDeleteId(floorId);
      return;
    }
    deleteFloor.mutate(floorId, {
      onSuccess: () => {
        setConfirmingDeleteId(null);
        onDeleted(floorId);
      },
      onError: () => setConfirmingDeleteId(null),
    });
  };

  return (
    <div>
      <ul className="max-h-72 overflow-y-auto py-1">
        {sorted.length === 0 && !creating && (
          <li className="px-3 py-3 text-xs text-muted-foreground">층이 없습니다.</li>
        )}
        {sorted.map((f) => {
          if (editingId === f.id) {
            return (
              <li key={f.id} className="px-3 py-2">
                <EditFloorForm
                  floor={f}
                  isSaving={updateFloor.isPending}
                  onSave={(body) =>
                    updateFloor.mutate(
                      { id: f.id, body },
                      { onSuccess: () => setEditingId(null) },
                    )
                  }
                  onCancel={() => setEditingId(null)}
                />
              </li>
            );
          }
          const confirming = confirmingDeleteId === f.id;
          const deleting = deleteFloor.isPending && confirmingDeleteId === f.id;
          return (
            <li key={f.id} className="group flex items-center">
              <button
                onClick={() => onSelect(f.id)}
                className={cn(
                  'flex flex-1 items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-accent',
                  f.id === selectedFloorId && 'bg-accent/60 font-medium',
                )}
              >
                <div className="flex flex-col items-start">
                  <span className="truncate">{f.floor_name}</span>
                  <span className="text-[10px] text-muted-foreground">
                    높이 {f.height_m}m
                  </span>
                </div>
                {f.id === selectedFloorId && <Check className="h-3.5 w-3.5 text-primary" />}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmingDeleteId(null);
                  setEditingId(f.id);
                }}
                aria-label="층 정보 수정"
                title="이름·높이 수정"
                className="inline-flex h-7 w-7 items-center justify-center text-muted-foreground opacity-0 hover:bg-accent hover:text-foreground group-hover:opacity-100"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={(e) => handleDeleteClick(e, f.id)}
                disabled={deleting}
                aria-label={confirming ? '삭제 확인' : '층 삭제'}
                title={confirming ? '한 번 더 누르면 삭제됩니다' : '층 삭제'}
                className={cn(
                  'mr-1 inline-flex h-7 items-center justify-center rounded-md px-2 text-[10px] font-medium transition-colors disabled:opacity-50',
                  confirming
                    ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
                    : 'text-muted-foreground opacity-0 hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100',
                )}
              >
                {confirming ? (
                  deleting ? '삭제 중…' : '확인'
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
              </button>
            </li>
          );
        })}
      </ul>
      <div className="border-t p-2">
        {creating ? (
          <CreateFloorForm
            projectId={projectId}
            nextOrder={(sorted.at(-1)?.floor_order ?? 0) + 1}
            onCancel={() => setCreating(false)}
            onCreated={(f) => {
              setCreating(false);
              onCreated(f);
            }}
          />
        ) : (
          <button
            onClick={() => setCreating(true)}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" />
            새 층
          </button>
        )}
      </div>
    </div>
  );
}

function EditFloorForm({
  floor,
  isSaving,
  onSave,
  onCancel,
}: {
  floor: Floor;
  isSaving: boolean;
  onSave: (body: { floor_name?: string; height_m?: number }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(floor.floor_name);
  const [height, setHeight] = useState(floor.height_m);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    const body: { floor_name?: string; height_m?: number } = {};
    if (trimmed !== floor.floor_name) body.floor_name = trimmed;
    if (Number.isFinite(height) && height > 0 && height !== floor.height_m) {
      body.height_m = height;
    }
    if (Object.keys(body).length === 0) {
      onCancel();
      return;
    }
    onSave(body);
  };
  return (
    <form onSubmit={submit} className="space-y-2">
      <label className="block">
        <span className="text-[10px] text-muted-foreground">층 이름</span>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onCancel();
          }}
          className="w-full rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </label>
      <label className="block">
        <span className="text-[10px] text-muted-foreground">높이 (m)</span>
        <input
          type="number"
          step="0.1"
          value={height}
          onChange={(e) => setHeight(Number(e.target.value))}
          className="w-full rounded-md border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </label>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={isSaving || !name.trim()}
          className="flex-1 rounded-md bg-primary px-2 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {isSaving ? '저장 중…' : '저장'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border px-2 py-1.5 text-xs hover:bg-accent"
        >
          취소
        </button>
      </div>
    </form>
  );
}

function CreateFloorForm({
  projectId,
  nextOrder,
  onCreated,
  onCancel,
}: {
  projectId: string;
  nextOrder: number;
  onCreated: (f: Floor) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(`${nextOrder}층`);
  const [height, setHeight] = useState(3.2);
  const create = useCreateFloor(projectId);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    // floor_order 는 사용자에게 노출하지 않고 자동 부여 (마지막 + 1).
    create.mutate(
      { floor_name: trimmed, floor_order: nextOrder, height_m: height },
      { onSuccess: (f) => onCreated(f) },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <label className="block">
        <span className="text-[10px] text-muted-foreground">층 이름</span>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="예: 1층, B1, 옥상"
          className="w-full rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </label>
      <label className="block">
        <span className="text-[10px] text-muted-foreground">높이 (m)</span>
        <input
          type="number"
          step="0.1"
          value={height}
          onChange={(e) => setHeight(Number(e.target.value))}
          className="w-full rounded-md border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </label>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={create.isPending || !name.trim()}
          className="flex-1 rounded-md bg-primary px-2 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {create.isPending ? '생성 중…' : '생성'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border px-2 py-1.5 text-xs hover:bg-accent"
        >
          취소
        </button>
      </div>
    </form>
  );
}
