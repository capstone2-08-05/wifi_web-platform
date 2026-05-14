import {
  MousePointer2,
  Upload,
  Square,
  Circle,
  Hexagon,
  DoorOpen,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { EditorTool } from '@/stores/editor-store';

interface CanvasToolbarProps {
  tool: EditorTool;
  onChangeTool: (tool: EditorTool) => void;
  onUploadClick: () => void;
}

interface ToolDef {
  id: EditorTool;
  icon: LucideIcon;
  label: string;
  onClick?: 'change' | 'upload';
}

const TOP_TOOLS: ToolDef[] = [
  { id: 'select', icon: MousePointer2, label: '선택', onClick: 'change' },
  { id: 'upload', icon: Upload, label: '도면 업로드', onClick: 'upload' },
];

const SHAPE_TOOLS: ToolDef[] = [
  { id: 'rect', icon: Square, label: '벽/구조물', onClick: 'change' },
  { id: 'polygon', icon: Hexagon, label: '방 만들기', onClick: 'change' },
  { id: 'opening', icon: DoorOpen, label: '문/창 추가', onClick: 'change' },
  { id: 'circle', icon: Circle, label: '가구 배치', onClick: 'change' },
];

export function CanvasToolbar({ tool, onChangeTool, onUploadClick }: CanvasToolbarProps) {
  const handleClick = (t: ToolDef) => {
    if (t.onClick === 'upload') {
      onUploadClick();
    } else {
      onChangeTool(t.id);
    }
  };

  return (
    <div className="flex w-14 shrink-0 flex-col items-center gap-1.5 border-r bg-background py-3">
      {TOP_TOOLS.map((t) => (
        <ToolButton
          key={t.id}
          icon={t.icon}
          label={t.label}
          active={tool === t.id}
          onClick={() => handleClick(t)}
        />
      ))}
      <div className="my-1 h-px w-7 bg-border" />
      {SHAPE_TOOLS.map((t) => (
        <ToolButton
          key={t.id}
          icon={t.icon}
          label={t.label}
          active={tool === t.id}
          onClick={() => handleClick(t)}
        />
      ))}
    </div>
  );
}

function ToolButton({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <div className="group relative">
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        className={cn(
          'flex h-9 w-9 items-center justify-center rounded-md transition-colors',
          active
            ? 'bg-primary/10 text-primary ring-1 ring-primary/30'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground',
        )}
      >
        <Icon className="h-4 w-4" strokeWidth={2} />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute left-full top-1/2 z-10 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white opacity-0 shadow-md transition-opacity group-hover:visible group-hover:opacity-100"
      >
        {label}
      </span>
    </div>
  );
}
