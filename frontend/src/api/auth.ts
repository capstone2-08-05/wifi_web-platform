import { api } from './client';
import type { LoginRequest, LoginResponse, SignupRequest, User } from '@/types/auth';

export const authApi = {
  signup: (body: SignupRequest) => api.post<User>('/auth/signup', body).then((r) => r.data),
  login: (body: LoginRequest) => api.post<LoginResponse>('/auth/login', body).then((r) => r.data),
  me: () => api.get<User>('/auth/me').then((r) => r.data),
};
