import type { ReactNode } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Link, useNavigate } from 'react-router-dom';
import { Wifi } from 'lucide-react';
import { useSignup } from '@/hooks/use-auth';
import type { HttpError } from '@/api/client';

const schema = z.object({
  name: z.string().min(1, '이름을 입력하세요'),
  email: z.string().email('올바른 이메일을 입력하세요'),
  password: z.string().min(8, '비밀번호는 8자 이상이어야 합니다'),
});

type FormValues = z.infer<typeof schema>;

export default function SignupPage() {
  const navigate = useNavigate();
  const signup = useSignup();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = (data: FormValues) =>
    signup.mutate(data, {
      onSuccess: () => navigate('/auth/login', { replace: true }),
    });
  const apiError = signup.error as HttpError | null;

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-sm rounded-xl border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <Wifi className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-semibold">회원가입</h1>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <Field label="이름" error={errors.name?.message}>
            <input
              type="text"
              {...register('name')}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </Field>
          <Field label="이메일" error={errors.email?.message}>
            <input
              type="email"
              autoComplete="email"
              {...register('email')}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </Field>
          <Field label="비밀번호" error={errors.password?.message}>
            <input
              type="password"
              autoComplete="new-password"
              {...register('password')}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </Field>
          {apiError && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {apiError.code === 'EMAIL_ALREADY_EXISTS'
                ? '이미 사용 중인 이메일입니다.'
                : apiError.code === 'INVALID_PASSWORD_FORMAT'
                  ? '비밀번호 형식이 올바르지 않습니다.'
                  : apiError.message}
            </div>
          )}
          <button
            type="submit"
            disabled={signup.isPending}
            className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {signup.isPending ? '가입 중…' : '회원가입'}
          </button>
        </form>
        <p className="mt-4 text-center text-xs text-muted-foreground">
          이미 계정이 있으신가요?{' '}
          <Link to="/auth/login" className="text-primary hover:underline">
            로그인
          </Link>
        </p>
      </div>
    </div>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
