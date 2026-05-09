import type { ISODateString, UUID } from './common';

export interface User {
  id: UUID;
  email: string;
  name: string;
  created_at: ISODateString;
}

export interface SignupRequest {
  email: string;
  password: string;
  name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: User;
}
