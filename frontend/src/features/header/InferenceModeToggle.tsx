import { Cloud, Cpu } from 'lucide-react';
import { useInferenceMode } from '@/hooks/use-inference-mode';
import { cn } from '@/lib/utils';

/**
 * 우상단 추론 백엔드 토글 (SageMaker ↔ Local).
 * - ON  (default) : SageMaker async (S3 + 폴링)
 * - OFF           : 로컬 AI 서버 (`AI_SERVICE_URL`) 동기 호출
 *
 * 상태는 localStorage 영속. 분석 API 호출 시점에 `getInferenceModeOnce()` 로 읽어 form/body 전달.
 */
export function InferenceModeToggle() {
  const { isSagemaker, setMode } = useInferenceMode();
  const label = isSagemaker ? 'SageMaker' : 'Local';
  const Icon = isSagemaker ? Cloud : Cpu;

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isSagemaker}
      title={
        isSagemaker
          ? 'SageMaker (async) 사용 중. 끄면 로컬 AI 서버로 우회합니다.'
          : 'Local AI 서버 사용 중. 켜면 SageMaker async 로 전환합니다.'
      }
      onClick={() => setMode(isSagemaker ? 'local' : 'sagemaker')}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium shadow-sm transition-colors',
        isSagemaker
          ? 'border-primary/40 bg-primary/5 text-primary hover:bg-primary/10'
          : 'border-amber-400/50 bg-amber-50 text-amber-700 hover:bg-amber-100',
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      <span>SageMaker</span>
      {/* Track */}
      <span
        className={cn(
          'relative ml-1 inline-flex h-3.5 w-7 items-center rounded-full transition-colors',
          isSagemaker ? 'bg-primary' : 'bg-muted',
        )}
      >
        <span
          className={cn(
            'inline-block h-2.5 w-2.5 transform rounded-full bg-white shadow transition-transform',
            isSagemaker ? 'translate-x-3.5' : 'translate-x-0.5',
          )}
        />
      </span>
      <span className="ml-1 tabular-nums text-[10px] opacity-70">{label}</span>
    </button>
  );
}
