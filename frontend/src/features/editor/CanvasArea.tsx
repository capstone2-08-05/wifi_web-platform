import { useState } from 'react';
import { Image as ImageIcon, Upload } from 'lucide-react';
import { cn } from '@/lib/utils';

const ALLOWED_MIME = ['image/png', 'image/jpeg', 'application/pdf'];
const ALLOWED_EXT = ['png', 'jpg', 'jpeg', 'pdf'];

function isAllowed(file: File) {
  if (ALLOWED_MIME.includes(file.type)) return true;
  const ext = file.name.split('.').pop()?.toLowerCase();
  return !!ext && ALLOWED_EXT.includes(ext);
}

interface CanvasAreaProps {
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  isPending?: boolean;
  errorMessage?: string;
  selectedFileName?: string | null;
  onFile: (file: File) => void;
}

export function CanvasArea({
  fileInputRef,
  isPending,
  errorMessage,
  selectedFileName,
  onFile,
}: CanvasAreaProps) {
  const [dragOver, setDragOver] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const accept = (f: File) => {
    if (!isAllowed(f)) {
      setLocalError('PNG / JPG / JPEG / PDF 파일만 업로드 가능합니다.');
      return;
    }
    setLocalError(null);
    onFile(f);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) accept(f);
  };

  const handlePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) accept(f);
    e.target.value = '';
  };

  const openPicker = () => fileInputRef.current?.click();
  const error = localError ?? errorMessage ?? null;

  return (
    <div className="relative flex flex-1 items-center justify-center overflow-hidden bg-muted/30 p-10">
      <input
        ref={fileInputRef}
        type="file"
        accept={ALLOWED_MIME.join(',')}
        onChange={handlePick}
        className="hidden"
      />
      <div
        onDragEnter={() => setDragOver(true)}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={cn(
          'flex max-w-3xl flex-1 flex-col items-center justify-center rounded-2xl border-2 border-dashed bg-background/60 px-10 py-16 text-center transition-colors',
          dragOver ? 'border-primary bg-primary/5' : 'border-border',
        )}
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <ImageIcon className="h-7 w-7" strokeWidth={1.8} />
        </div>
        <h3 className="mt-5 text-lg font-semibold text-foreground">
          도면 이미지를 업로드해주세요
        </h3>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
          매장의 도면(JPG, PNG)을 업로드하여 와이파이 환경을 설계할 수
          있습니다.
        </p>
        <button
          type="button"
          onClick={openPicker}
          disabled={isPending}
          className="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          <Upload className="h-4 w-4" />
          {isPending ? '분석 중…' : '컴퓨터에서 도면 찾기'}
        </button>

        {selectedFileName && !isPending && (
          <p className="mt-4 text-xs text-muted-foreground">
            선택된 파일: <span className="font-medium text-foreground">{selectedFileName}</span>
          </p>
        )}

        {error && (
          <p className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
