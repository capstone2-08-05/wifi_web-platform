import { useEffect, useState } from 'react';
import { Check, ChevronDown, Pencil, Plus, Trash2 } from 'lucide-react';
import { Popover } from '@/components/ui/Popover';
import {
  useCreateProject,
  useDeleteProject,
  useProjects,
  useUpdateProject,
} from '@/hooks/use-projects';
import { useAppStore } from '@/stores/app-store';
import { cn } from '@/lib/utils';
import type { Project } from '@/types/project';

export function ProjectSelector() {
  const selectedId = useAppStore((s) => s.selectedProjectId);
  const setProject = useAppStore((s) => s.setProject);
  const { data, isLoading } = useProjects();

  const projects = data?.items ?? [];
  const selected = projects.find((p) => p.id === selectedId) ?? null;

  // Auto-select first project on first load if nothing is selected and projects exist.
  useEffect(() => {
    if (!selectedId && projects.length > 0) {
      setProject(projects[0].id);
    }
  }, [selectedId, projects, setProject]);

  return (
    <Popover
      contentClassName="w-72 p-0"
      trigger={({ toggle }) => (
        <button
          onClick={toggle}
          className="flex min-w-44 items-center justify-between rounded-md border bg-background px-3 py-2 text-sm hover:bg-accent"
        >
          <div className="flex flex-col items-start">
            <span className="text-[10px] text-muted-foreground">프로젝트</span>
            <span className="truncate font-medium">
              {isLoading ? '불러오는 중…' : (selected?.name ?? '프로젝트 선택')}
            </span>
          </div>
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        </button>
      )}
    >
      {({ close }) => (
        <ProjectMenu
          projects={projects}
          selectedId={selectedId}
          onSelect={(id) => {
            setProject(id);
            close();
          }}
          onCreated={(p) => {
            setProject(p.id);
            close();
          }}
          onDeleted={(deletedId) => {
            if (deletedId === selectedId) {
              const remaining = projects.filter((p) => p.id !== deletedId);
              setProject(remaining[0]?.id ?? null);
            }
          }}
        />
      )}
    </Popover>
  );
}

function ProjectMenu({
  projects,
  selectedId,
  onSelect,
  onCreated,
  onDeleted,
}: {
  projects: Project[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreated: (p: Project) => void;
  onDeleted: (deletedId: string) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const updateProject = useUpdateProject();
  const deleteProject = useDeleteProject();

  const handleDeleteClick = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (confirmingDeleteId !== id) {
      setConfirmingDeleteId(id);
      return;
    }
    deleteProject.mutate(id, {
      onSuccess: () => {
        setConfirmingDeleteId(null);
        onDeleted(id);
      },
      onError: () => setConfirmingDeleteId(null),
    });
  };

  return (
    <div>
      <ul className="max-h-72 overflow-y-auto py-1">
        {projects.length === 0 && !creating && (
          <li className="px-3 py-3 text-xs text-muted-foreground">프로젝트가 없습니다.</li>
        )}
        {projects.map((p) => {
          if (editingId === p.id) {
            return (
              <li key={p.id} className="px-3 py-2">
                <RenameProjectForm
                  project={p}
                  isSaving={updateProject.isPending}
                  onSave={(name) =>
                    updateProject.mutate(
                      { id: p.id, body: { name } },
                      { onSuccess: () => setEditingId(null) },
                    )
                  }
                  onCancel={() => setEditingId(null)}
                />
              </li>
            );
          }
          const confirming = confirmingDeleteId === p.id;
          const deleting = deleteProject.isPending && confirming;
          return (
            <li key={p.id} className="group flex items-center">
              <button
                onClick={() => onSelect(p.id)}
                className={cn(
                  'flex flex-1 items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-accent',
                  p.id === selectedId && 'bg-accent/60 font-medium',
                )}
              >
                <span className="truncate">{p.name}</span>
                {p.id === selectedId && <Check className="h-3.5 w-3.5 text-primary" />}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmingDeleteId(null);
                  setEditingId(p.id);
                }}
                aria-label="이름 변경"
                title="이름 변경"
                className="inline-flex h-7 w-7 items-center justify-center text-muted-foreground opacity-0 hover:bg-accent hover:text-foreground group-hover:opacity-100"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={(e) => handleDeleteClick(e, p.id)}
                disabled={deleting}
                aria-label={confirming ? '삭제 확인' : '프로젝트 삭제'}
                title={confirming ? '한 번 더 누르면 삭제됩니다' : '프로젝트 삭제'}
                className={cn(
                  'mr-1 inline-flex h-7 items-center justify-center rounded-md px-2 text-[10px] font-medium transition-colors disabled:opacity-50',
                  confirming
                    ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
                    : 'text-muted-foreground opacity-0 hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100',
                )}
              >
                {confirming ? (deleting ? '삭제 중…' : '확인') : <Trash2 className="h-3.5 w-3.5" />}
              </button>
            </li>
          );
        })}
      </ul>
      <div className="border-t p-2">
        {creating ? (
          <CreateProjectForm
            onCancel={() => setCreating(false)}
            onCreated={(p) => {
              setCreating(false);
              onCreated(p);
            }}
          />
        ) : (
          <button
            onClick={() => setCreating(true)}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" />
            새 프로젝트
          </button>
        )}
      </div>
    </div>
  );
}

function RenameProjectForm({
  project,
  isSaving,
  onSave,
  onCancel,
}: {
  project: Project;
  isSaving: boolean;
  onSave: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(project.name);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || trimmed === project.name) {
      onCancel();
      return;
    }
    onSave(trimmed);
  };
  return (
    <form onSubmit={submit} className="space-y-2">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel();
        }}
        className="w-full rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
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

function CreateProjectForm({
  onCreated,
  onCancel,
}: {
  onCreated: (p: Project) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState('');
  const create = useCreateProject();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    create.mutate(
      { name: trimmed },
      { onSuccess: (p) => onCreated(p) },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="프로젝트 이름"
        className="w-full rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
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
