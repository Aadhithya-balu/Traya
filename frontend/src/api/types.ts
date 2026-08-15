export interface UserSummary {
  id: string;
  email: string;
  full_name: string;
  phone?: string | null;
  date_of_birth?: string | null;
  is_active: boolean;
  roles: string[];
  created_at?: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  refresh_token?: string | null;
  user: UserSummary;
}

export interface Quality {
  image_quality_score: number;
  face_visibility_score: number;
  occlusion_score: number;
  blur_score: number;
  lighting_score: number;
  usable_for_matching: boolean;
  reasons: string[];
}

export interface Candidate {
  user_id: string;
  confidence: number;
  rank: number;
  method: string[];
  status: string;
}

export interface IdentifyResult {
  session_id: string;
  status: string;
  human_readable: string;
  confidence?: number | null;
  candidates: Candidate[];
  method: string[];
  fallback_used: boolean;
  requires_human_confirmation: boolean;
  medical_alerts_available: boolean;
  quality?: Quality | null;
  face_count: number;
}

export interface CaptureOut {
  session_id: string;
  image_quality_score?: number | null;
  face_visibility_score?: number | null;
  occlusion_score?: number | null;
  blur_score?: number | null;
  lighting_score?: number | null;
  face_count: number;
  usable_for_matching: boolean;
  reasons: string[];
}

export interface SessionStatus {
  session_id: string;
  session_code: string;
  status: string;
  access_type: string;
  outcome?: string | null;
  identification_method: string[];
  confidence_category?: string | null;
  started_at: string;
  expires_at: string;
  completed_at?: string | null;
  identified_user_id?: string | null;
}

export interface PublicSummary {
  user_id: string;
  full_name: string;
  age?: number | null;
  blood_group?: string | null;
  critical_allergies: string[];
  critical_conditions: string[];
  critical_medications: string[];
  emergency_warnings: string[];
  emergency_contact: {
    name?: string | null;
    phone?: string | null;
    relationship?: string | null;
  };
  photo_available: boolean;
}

export interface ResponderProfile extends PublicSummary {
  additional: Record<string, unknown>;
  visible_features: { feature_type: string; description: string; body_location?: string | null }[];
  all_contacts: { name: string; relationship?: string | null; phone: string }[];
}

export interface TimelineEvent {
  at: string;
  action: string;
  details?: Record<string, unknown> | null;
}

export interface ContactAction {
  session_id: string;
  action: string;
  contact_name?: string | null;
  contact_phone?: string | null;
  logged_at: string;
}

export interface HospitalNearby {
  id: string;
  name: string;
  address?: string | null;
  phone?: string | null;
  distance_km: number;
  travel_minutes?: number | null;
  emergency_available: boolean;
  availability_verified: boolean;
}

export interface EmergencyContact {
  id: string;
  name: string;
  relation?: string | null;
  phone: string;
  email?: string | null;
  is_primary: boolean;
  created_at?: string | null;
}

export interface MedicalProfile {
  blood_group?: string | null;
  allergies: string[];
  conditions: string[];
  medications: string[];
  emergency_notes?: string | null;
  preferred_hospital?: string | null;
  updated_at?: string | null;
}

export interface VisibleFeature {
  id: string;
  feature_type: string;
  description: string;
  body_location?: string | null;
  created_at?: string | null;
}

export interface Consent {
  consent_type: string;
  status: string;
  version: string;
  granted_at?: string | null;
  withdrawn_at?: string | null;
}

export interface BiometricStatus {
  status: string;
  enrolled_at?: string | null;
  num_samples: number;
  algo_version?: string | null;
}

export interface DemoScenario {
  id: string;
  title: string;
  description: string;
}

export interface DemoRun {
  session_id: string;
  session_code: string;
  preview_image?: string | null;
  identification: IdentifyResult;
}

export interface Analytics {
  total_users: number;
  total_enrolled: number;
  total_sessions: number;
  successful_identifications: number;
  identification_rate: number;
  fallback_usage: number;
  failed_attempts: number;
  average_identification_time_ms?: number | null;
  identifications_by_day: { day: string; count: number }[];
  status_breakdown: { status: string; count: number }[];
}

export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_demo: boolean;
  roles: string[];
  created_at?: string | null;
}

export interface AuditLog {
  id: string;
  actor_type: string;
  actor_id?: string | null;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  session_id?: string | null;
  details?: Record<string, unknown> | null;
  created_at: string;
}

export interface Setting {
  key: string;
  value: string;
  description?: string | null;
}

export interface HospitalAdmin {
  id: string;
  name: string;
  address?: string | null;
  phone?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  emergency_available: boolean;
  availability_verified: boolean;
  created_at?: string | null;
}
