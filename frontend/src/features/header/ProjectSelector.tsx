import { useEffect, useState } from 'react';
import { Check, ChevronDown, Plus } from 'lucide-react';
import { Popover } from '@/components/ui/Popover';
import { useCreateProject, useProjects } from '@/hooks/use-projects';
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
}: {
  projects: Project[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreated: (p: Project) => void;
}) {
  const [creating, setCreating] = useState(false);
  return (
    <div>
      <ul className="max-h-72 overflow-y-auto py-1">
        {projects.length === 0 && !creating && (
          <li className="px-3 py-3 text-xs text-muted-foreground">프로젝트가 없습니다.</li>
        )}
        {projects.map((p) => (
          <li key={p.id}>
            <button
              onClick={() => onSelect(p.id)}
              className={cn(
                'flex w-full items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-accent',
                p.id === selectedId && 'bg-accent/60 font-medium',
              )}
            >
              <span className="truncate">{p.name}</span>
              {p.id === selectedId && <Check className="h-3.5 w-3.5 text-primary" />}
            </button>
          </li>
        ))}
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
