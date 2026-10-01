export interface UserSummary {
  id: string;
  email: string;
  full_name: string;
  phone?: string | null;
  date_of_birth?: string | null;
  is_active: boolean;
  roles: string[];
  permissions?: string[];
  created_at?: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  refresh_token?: string | null;
  user: UserSummary;
}

/**
 * The quality fields, with scores nullable.
 *
 * `CaptureOut` declares them optional-and-nullable because a capture can fail
 * before any score is computed. The panel used to receive it through a
 * `as unknown as Quality` cast, which turned a null into `Math.round(null * 100)`
 * and then into `width: NaN%` - a silently collapsed meter. Typing the panel
 * against this shape makes that unrepresentable.
 */
export interface QualityScores {
  image_quality_score: number | null;
  face_visibility_score: number | null;
  occlusion_score: number | null;
  blur_score: number | null;
  lighting_score: number | null;
  usable_for_matching: boolean;
  reasons: string[];
  reason_codes?: string[];
}

export interface Quality extends QualityScores {
  image_quality_score: number;
  face_visibility_score: number;
  occlusion_score: number;
  blur_score: number;
  lighting_score: number;
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
  confidence: number | null;
  candidates: Candidate[];
  method: string[];
  fallback_used: boolean;
  requires_human_confirmation: boolean;
  medical_alerts_available: boolean;
  quality: Quality | null;
face_count: number;
/**
 * Which matcher produced this. "simulation" is the demo engine: twelve
 * brightness measurements padded to 320 dimensions, compared by euclidean
 * distance. It does not detect faces and it is not a biometric.
 */
engine_mode: string;
demo_mode: boolean;
/**
 * Which build of the engine scored this result. Always present, and required in
 * the type so a result can never reach a responder without saying where the
 * number came from.
 */
algo_version: string | null;
}

export interface CaptureOut {
session_id: string;
/**
 * Nullable, not optional. The backend declares every one of these with a `None`
 * default, so the keys are always present in the JSON and may only be null.
 * The frontend used `?:`, which is a third state that does not exist on the
 * wire, and it is what forced the `as unknown as Quality` cast in Emergency.tsx.
 */
image_quality_score: number | null;
face_visibility_score: number | null;
occlusion_score: number | null;
blur_score: number | null;
lighting_score: number | null;
face_count: number;
usable_for_matching: boolean;
reasons: string[];
reason_codes?: string[];
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

/** Response of POST /emergency/start. */
export interface EmergencyStartOut {
  session_id: string;
  session_code: string;
  /**
   * Scoped credential for this emergency session. The backend requires it as
   * `X-TRAYA-Session-Token` on every subsequent session-scoped call; the
   * session id alone is not authorization. Held in sessionStorage by the API
   * client and never persisted beyond the tab.
   */
  session_token: string;
  status: string;
  started_at: string;
  expires_at: string;
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

/**
 * The seven roles the backend seeds into `role_permissions`.
 *
 * Mirrored here so the admin UI cannot offer a role that grants nothing, which
 * is exactly what "registered" did. backend/tests/test_rbac_matrix.py asserts
 * this list still equals ROLE_PERMISSIONS, so adding a role without updating
 * the type is a failing test rather than a silent no-op in the UI.
 */
export type Role =
  | "public"
  | "registered_user"
  | "medical_responder"
  | "police_responder"
  | "hospital"
  | "auditor"
  | "admin";

/**
 * The backend's stored consent state.
 *
 * It is "active" and "withdrawn" - never "granted". The UI compared against
 * "granted" for its entire life, so every toggle granted and none could ever
 * withdraw, and the compiler had nothing to say about it because the field was
 * a bare `string`. Union the real values so that class of bug is a type error.
 */
export type ConsentStatus = "active" | "withdrawn";

export interface Consent {
consent_type: string;
status: ConsentStatus;
version: string;
granted_at?: string | null;
withdrawn_at?: string | null;
}

/**
 * Enrolment state, lowercase.
 *
 * The API returns "not_enrolled" / "in_progress" / "enrolled" (api/biometric.py
 * and services/biometric/enrollment.py). `Profile.tsx` compared against "ENROLLED",
 * so the badge always read NOT ENROLLED and the delete-templates block never
 * rendered - a citizen who had successfully enrolled was told they had not.
 */
export type BiometricEnrollmentStatus =
  | "not_enrolled"
  | "in_progress"
  | "enrolled";

export interface BiometricStatus {
  status: BiometricEnrollmentStatus;
  enrolled_at?: string | null;
  num_samples: number;
  algo_version?: string | null;
}

/** One coached pose. `done` is the server's view, not the client's. */
export interface EnrollmentStep {
  index: number;
  key: string;
  pose: string;
  done: boolean;
}

export interface EnrollmentState {
  enrollment_id: string;
  status: string;
  current_step: number;
  total_steps: number;
  accepted_samples: number;
  rejected_samples: number;
  min_samples: number;
  steps: EnrollmentStep[];
  current_instruction: string;
  can_complete: boolean;
}

/**
 * The engine's verdict on one capture.
 *
 * `guidance` holds i18n keys under `enroll.guidance.`, not sentences. The reason
 * codes come from the engine so the quality panel and this wizard can never
 * disagree about whether a photo was usable; the mapping to language happens on
 * the client and lives in the same namespace.
 */
export interface SampleVerdict {
  accepted: boolean;
  guidance: string[];
  quality_score: number;
  face_count: number;
  step_index: number;
  step_key: string;
  matched_step: boolean;
  observed_direction: string;
  pose_offset_x: number | null;
  pose_offset_y: number | null;
  pose_confident: boolean;
}

/**
 * How much this person's own samples agreed with each other, measured at
 * `complete`. Reported rather than hidden because a template enrolled from
 * inconsistent captures matches badly, and `min_pairwise` is the first thing to
 * look at when it does.
 */
export interface ConsistencyReport {
  min_pairwise: number;
  mean_pairwise: number;
  pairs: number;
  threshold: number;
}

export interface EnrollmentComplete {
  status: string;
  num_samples: number;
  algo_version?: string | null;
  enrolled_at?: string | null;
  steps_completed: string[];
  consistency: ConsistencyReport;
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
