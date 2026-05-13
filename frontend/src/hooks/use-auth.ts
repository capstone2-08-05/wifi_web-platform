import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { authApi } from '@/api/auth';
import { useAuthStore } from '@/stores/auth-store';
import { toast } from '@/stores/toast-store';
import type { LoginRequest, SignupRequest } from '@/types/auth';

export function useLogin() {
  const setSession = useAuthStore((s) => s.setSession);
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (body: LoginRequest) => authApi.login(body),
    onSuccess: (data) => {
      setSession(data.access_token, data.expires_in, data.user);
      toast.success(`${data.user.name}님, 환영합니다`);
      const params = new URLSearchParams(window.location.search);
      const next = params.get('next');
      navigate(next ?? '/', { replace: true });
    },
  });
}

export function useSignup() {
  return useMutation({
    mutationFn: (body: SignupRequest) => authApi.signup(body),
    onSuccess: () => {
      toast.success('회원가입 완료', '로그인하여 시작해보세요.');
    },
  });
}

export function useMe(enabled = true) {
  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => authApi.me(),
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

export function useLogout() {
  const clear = useAuthStore((s) => s.clear);
  const qc = useQueryClient();
  const navigate = useNavigate();
  return () => {
    clear();
    qc.clear();
    navigate('/auth/login', { replace: true });
  };
}
