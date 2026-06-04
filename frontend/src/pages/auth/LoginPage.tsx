import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Link, Navigate } from 'react-router-dom';
import { Wifi } from 'lucide-react';
import { useLogin } from '@/hooks/use-auth';
import { useAuthStore } from '@/stores/auth-store';
import type { HttpError } from '@/api/client';

const schema = z.object({
  email: z.string().email('올바른 이메일을 입력하세요'),
  password: z.string().min(1, '비밀번호를 입력하세요'),
});

type FormValues = z.infer<typeof schema>;

export default function LoginPage() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated());
  const login = useLogin();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  if (isAuthed) return <Navigate to="/" replace />;

  const onSubmit = (data: FormValues) => login.mutate(data);
  const apiError = login.error as HttpError | null;

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4" style={{ animation: 'page-enter 0.4s cubic-bezier(0.16, 1, 0.3, 1) both' }}>
      <div className="w-full max-w-sm rounded-xl border bg-card p-8 shadow-sm" style={{ animation: 'panel-rise 0.7s cubic-bezier(0.16, 1, 0.3, 1) both' }}>
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="flex items-center gap-2">
            <Wifi className="h-6 w-6 text-primary" />
            <h1 className="text-xl font-semibold tracking-tight">Wi-Fi Space</h1>
          </div>
          <p className="text-xs text-muted-foreground">
            매장의 와이파이를 더 똑똑하게
          </p>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="email" className="text-sm font-medium">이메일</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              {...register('email')}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
            {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
          </div>
          <div className="space-y-1.5">
            <label htmlFor="password" className="text-sm font-medium">비밀번호</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              {...register('password')}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
            {errors.password && <p className="text-xs text-destructive">{errors.password.message}</p>}
          </div>
          {apiError && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {apiError.code === 'INVALID_CREDENTIALS'
                ? '이메일 또는 비밀번호가 올바르지 않습니다.'
                : apiError.message}
            </div>
          )}
          <button
            type="submit"
            disabled={login.isPending}
            className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {login.isPending ? '로그인 중…' : '로그인'}
          </button>
        </form>
        <p className="mt-4 text-center text-xs text-muted-foreground">
          계정이 없으신가요?{' '}
          <Link to="/auth/signup" className="text-primary hover:underline">
            회원가입
          </Link>
        </p>
      </div>
    </div>
  );
}
