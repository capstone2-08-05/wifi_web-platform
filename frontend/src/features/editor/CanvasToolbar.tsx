import {
  MousePointer2,
  Upload,
  DoorOpen,
  type LucideIcon,
} from 'lucide-react';
import type { ComponentType } from 'react';
import { cn } from '@/lib/utils';
import type { EditorTool } from '@/stores/editor-store';

interface CanvasToolbarProps {
  tool: EditorTool;
  onChangeTool: (tool: EditorTool) => void;
  onUploadClick: () => void;
}

interface ToolDef {
  id: EditorTool;
  icon: ToolIcon;
  label: string;
  onClick?: 'change' | 'upload';
}

type ToolIcon = LucideIcon | ComponentType<{ className?: string; strokeWidth?: number }>;

const TOP_TOOLS: ToolDef[] = [
  { id: 'select', icon: MousePointer2, label: '선택', onClick: 'change' },
  { id: 'upload', icon: Upload, label: '도면 업로드', onClick: 'upload' },
];

const SHAPE_TOOLS: ToolDef[] = [
  { id: 'rect', icon: WallIcon, label: '벽', onClick: 'change' },
  // [room 비활성화] '방 만들기' 도구 노출 제거. 다시 켜려면 아래 줄 주석 해제.
  // { id: 'polygon', icon: Hexagon, label: '방 만들기', onClick: 'change' },
  { id: 'door', icon: DoorOpen, label: '문 추가', onClick: 'change' },
  { id: 'window', icon: WindowIcon, label: '창문 추가', onClick: 'change' },
  // [object 비활성화] 공간 편집 화면에서 가구/공간성 객체 추가 도구 숨김.
  // { id: 'circle', icon: Circle, label: '가구 배치', onClick: 'change' },
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
  icon: ToolIcon;
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

function WallIcon({
  className,
  strokeWidth = 2,
}: {
  className?: string;
  strokeWidth?: number;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="butt"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 7h16" strokeWidth={strokeWidth + 1.5} />
      <path d="M4 17h16" strokeWidth={strokeWidth + 1.5} />
      <path d="M8 4v16" strokeWidth={strokeWidth + 1.5} />
      <path d="M16 4v16" strokeWidth={strokeWidth + 1.5} />
    </svg>
  );
}

function WindowIcon({
  className,
  strokeWidth = 2,
}: {
  className?: string;
  strokeWidth?: number;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="5" y="6" width="14" height="12" rx="1.5" />
      <path d="M12 6v12" />
      <path d="M5 12h14" />
      <path d="M8 4h8" />
      <path d="M8 20h8" />
    </svg>
  );
}
