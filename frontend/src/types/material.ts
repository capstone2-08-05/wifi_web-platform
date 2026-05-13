import type { ISODateString, UUID } from './common';

// 백엔드 §12 Material DTO 매핑 (app/schemas/material.py)

export interface Material {
  id: UUID;
  material_code: string;
  material_name: string;
  category: string | null;
  is_active: boolean;
  created_at: ISODateString;
}

export interface MaterialRfProfile {
  id: UUID;
  material_id: UUID;
  freq_ghz: string;
  permittivity: string;
  conductivity: string;
  penetration_loss_db: string;
  reference_thickness_m: string;
  profile_version: number;
  is_default: boolean;
}
