export type UUID = string;
export type ISODateString = string;

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface PageQuery {
  page?: number;
  page_size?: number;
}
