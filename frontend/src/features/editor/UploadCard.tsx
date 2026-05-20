import { useRef, useState } from 'react';
import { Image as ImageIcon, Upload, X } from 'lucide-react';
import { cn } from '@/lib/utils';

const ALLOWED_MIME = ['image/png', 'image/jpeg', 'application/pdf'];
const ALLOWED_EXT = ['png', 'jpg', 'jpeg', 'pdf'];

function isAllowed(file: File) {
  if (ALLOWED_MIME.includes(file.type)) return true;
  const ext = file.name.split('.').pop()?.toLowerCase();
  return !!ext && ALLOWED_EXT.includes(ext);
}

interface UploadCardProps {
  isPending?: boolean;
  errorMessage?: string;
  onSubmit: (file: File) => void;
}

export function UploadCard({ isPending, errorMessage, onSubmit }: UploadCardProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const accept = (f: File) => {
    if (!isAllowed(f)) {
      setLocalError('PNG / JPG / JPEG / PDF 파일만 업로드 가능합니다.');
      return;
    }
    setLocalError(null);
    setFile(f);
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

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    onSubmit(file);
  };

  const error = localError ?? errorMessage ?? null;

  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm">
      <form onSubmit={submit} className="space-y-4">
        <div
          onDragEnter={() => setDragOver(true)}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={cn(
            'flex h-72 flex-col items-center justify-center rounded-lg border-2 border-dashed bg-muted/20 p-6 text-center transition-colors',
            dragOver ? 'border-primary bg-primary/5' : 'border-border',
          )}
        >
          {file ? (
            <div className="flex flex-col items-center gap-2">
              <ImageIcon className="h-10 w-10 text-primary" />
              <p className="text-sm font-medium">{file.name}</p>
              <p className="text-xs text-muted-foreground">
                {(file.size / 1024).toFixed(0)} KB · {file.type || '확장자 기반'}
              </p>
              <button
                type="button"
                onClick={() => setFile(null)}
                className="mt-2 inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-accent"
              >
                <X className="h-3 w-3" />
                다시 선택
              </button>
            </div>
          ) : (
            <>
              <ImageIcon className="h-10 w-10 text-primary/70" />
              <h3 className="mt-3 text-sm font-semibold">도면 이미지를 업로드해주세요</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                매장의 도면 (JPG/PNG/PDF) 을 업로드하여 와이파이 환경을 설계할 수 있습니다.
              </p>
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Upload className="h-4 w-4" />
                컴퓨터에서 도면 찾기
              </button>
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={ALLOWED_MIME.join(',')}
            onChange={handlePick}
            className="hidden"
          />
        </div>

        <p className="text-[11px] text-muted-foreground">
          AI 가 도면 치수를 자동으로 읽어 scale 을 추정합니다. 분석 후 벽별 실측값으로
          보정할 수 있습니다.
        </p>

        {error && (
          <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        )}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={!file || isPending}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {isPending ? '분석 중…' : '업로드 후 분석'}
          </button>
        </div>
      </form>
    </div>
  );
}
