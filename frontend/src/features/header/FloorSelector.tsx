import { useEffect, useState } from 'react';
import { Check, ChevronDown, Plus } from 'lucide-react';
import { Popover } from '@/components/ui/Popover';
import { useCreateFloor, useFloors } from '@/hooks/use-floors';
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
}: {
  floors: Floor[];
  selectedFloorId: string | null;
  projectId: string;
  onSelect: (id: string) => void;
  onCreated: (f: Floor) => void;
}) {
  const [creating, setCreating] = useState(false);
  const sorted = [...floors].sort((a, b) => a.floor_order - b.floor_order);
  return (
    <div>
      <ul className="max-h-72 overflow-y-auto py-1">
        {sorted.length === 0 && !creating && (
          <li className="px-3 py-3 text-xs text-muted-foreground">층이 없습니다.</li>
        )}
        {sorted.map((f) => (
          <li key={f.id}>
            <button
              onClick={() => onSelect(f.id)}
              className={cn(
                'flex w-full items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-accent',
                f.id === selectedFloorId && 'bg-accent/60 font-medium',
              )}
            >
              <div className="flex flex-col items-start">
                <span className="truncate">{f.floor_name}</span>
                <span className="text-[10px] text-muted-foreground">
                  순서 {f.floor_order} · 높이 {f.height_m}m
                </span>
              </div>
              {f.id === selectedFloorId && <Check className="h-3.5 w-3.5 text-primary" />}
            </button>
          </li>
        ))}
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
  const [order, setOrder] = useState(nextOrder);
  const [height, setHeight] = useState(3.2);
  const create = useCreateFloor(projectId);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    create.mutate(
      { floor_name: trimmed, floor_order: order, height_m: height },
      { onSuccess: (f) => onCreated(f) },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="층 이름 (예: 1층)"
        className="w-full rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-[10px] text-muted-foreground">순서</span>
          <input
            type="number"
            value={order}
            onChange={(e) => setOrder(Number(e.target.value))}
            className="w-full rounded-md border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </label>
        <label className="block">
          <span className="text-[10px] text-muted-foreground">높이(m)</span>
          <input
            type="number"
            step="0.1"
            value={height}
            onChange={(e) => setHeight(Number(e.target.value))}
            className="w-full rounded-md border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </label>
      </div>
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
