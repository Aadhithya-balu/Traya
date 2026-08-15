import type {
  AdminUser,
  Analytics,
  AuditLog,
  BiometricStatus,
  CaptureOut,
  Consent,
  ContactAction,
  DemoRun,
  DemoScenario,
  EmergencyContact,
  HospitalAdmin,
  HospitalNearby,
  IdentifyResult,
  MedicalProfile,
  PublicSummary,
  ResponderProfile,
  SessionStatus,
  Setting,
  TimelineEvent,
  TokenResponse,
  UserSummary,
  VisibleFeature,
} from "./types";

const ACCESS_KEY = "traya_access";
const REFRESH_KEY = "traya_refresh";

export function getTokens() {
  return {
    access: localStorage.getItem(ACCESS_KEY),
    refresh: localStorage.getItem(REFRESH_KEY),
  };
}

export function setTokens(access: string, refresh?: string | null) {
  localStorage.setItem(ACCESS_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refresh = getTokens().refresh;
  if (!refresh) return null;
  const res = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!res.ok) return null;
  const data = (await res.json()) as TokenResponse;
  setTokens(data.access_token, data.refresh_token);
  return data.access_token;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const attempt = async (token?: string): Promise<Response> => {
    const headers: Record<string, string> = {
      ...((options.headers as Record<string, string>) || {}),
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch(`/api${path}`, { ...options, headers });
  };

  let res = await attempt(getTokens().access ?? undefined);

  if (res.status === 401 && !path.startsWith("/auth/login") && !path.startsWith("/auth/refresh")) {
    refreshPromise = refreshPromise ?? refreshAccessToken();
    const newToken = await refreshPromise;
    refreshPromise = null;
    if (newToken) {
      res = await attempt(newToken);
    }
  }

  if (res.status === 204) return undefined as T;

  const contentType = res.headers.get("content-type") || "";
  let body: unknown = null;
  if (contentType.includes("application/json")) {
    body = await res.json();
  }

  if (!res.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

export const api = {
  // auth
  login: (email: string, password: string) =>
    request<TokenResponse>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  register: (payload: {
    full_name: string;
    email: string;
    password: string;
    phone?: string;
    date_of_birth?: string | null;
  }) =>
    request<TokenResponse>("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  me: () => request<UserSummary>("/auth/me"),

  // emergency (public)
  startSession: (accessType = "public") =>
    request<{ session_id: string; session_code: string; status: string; started_at: string; expires_at: string }>(
      "/emergency/start",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ access_type: accessType }) },
    ),
  sessionStatus: (sessionId: string) => request<SessionStatus>(`/emergency/${sessionId}`),
  capture: (sessionId: string, image: string) =>
    request<CaptureOut>(`/emergency/${sessionId}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image }),
    }),
  identify: (sessionId: string, image: string, secondaryFeatures: string[] = [], lat?: number | null, lng?: number | null) =>
    request<IdentifyResult>(`/emergency/${sessionId}/identify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image,
        secondary_features: secondaryFeatures,
        latitude: lat ?? null,
        longitude: lng ?? null,
      }),
    }),
  confirm: (sessionId: string, candidateUserId: string, accept = true) =>
    request<{ status: string }>(`/emergency/${sessionId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_user_id: candidateUserId, accept }),
    }),
  medicalSummary: (sessionId: string) => request<PublicSummary>(`/emergency/${sessionId}/medical-summary`),
  responderProfile: (sessionId: string) => request<ResponderProfile>(`/emergency/${sessionId}/responder-profile`),
  contactAction: (sessionId: string, action: "call" | "sms" | "share_location") =>
    request<ContactAction>(`/emergency/${sessionId}/contact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }),
  sendLocation: (sessionId: string, latitude: number, longitude: number, source: "gps" | "manual") =>
    request<{ id: string; latitude: number; longitude: number; source: string; captured_at: string }>(
      `/emergency/${sessionId}/location`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ latitude, longitude, source }) },
    ),
  timeline: (sessionId: string) => request<TimelineEvent[]>(`/emergency/${sessionId}/timeline`),

  // hospitals
  nearbyHospitals: (lat: number, lng: number, radiusKm = 50) =>
    request<HospitalNearby[]>(`/hospitals/nearby?lat=${lat}&lng=${lng}&radius_km=${radiusKm}`),

  // users
  updateProfile: (payload: { full_name?: string; phone?: string | null; date_of_birth?: string | null }) =>
    request<Record<string, unknown>>("/users/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getMedical: () => request<MedicalProfile>("/users/medical"),
  updateMedical: (payload: Partial<MedicalProfile>) =>
    request<MedicalProfile>("/users/medical", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  listContacts: () => request<EmergencyContact[]>("/users/contacts"),
  addContact: (payload: { name: string; relation?: string; phone: string; email?: string; is_primary: boolean }) =>
    request<EmergencyContact>("/users/contacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteContact: (id: string) =>
    request<void>(`/users/contacts/${id}`, { method: "DELETE" }),
  listFeatures: () => request<VisibleFeature[]>("/users/features"),
  addFeature: (payload: { feature_type: string; description: string; body_location?: string }) =>
    request<VisibleFeature>("/users/features", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteFeature: (id: string) => request<void>(`/users/features/${id}`, { method: "DELETE" }),
  listConsents: () => request<Consent[]>("/users/consents"),
  grantConsent: (consentType: string) =>
    request<Consent>("/users/consents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ consent_type: consentType, granted: true }),
    }),
  withdrawConsent: (consentType: string) =>
    request<Consent>("/users/consents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ consent_type: consentType, granted: false }),
    }),
  biometricStatus: () => request<BiometricStatus>("/biometric/status"),
  enrollBiometric: (images: string[]) =>
    request<{ status: string; num_samples: number; algo_version?: string; image_reports: unknown[] }>("/biometric/enroll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ images }),
    }),
  deleteBiometric: () => request<void>("/users/biometric", { method: "DELETE" }),
  accessHistory: () => request<TimelineEvent[]>("/users/access-history"),
  notifications: () => request<Record<string, unknown>[]>("/users/notifications"),

  // demo
  demoScenarios: () => request<DemoScenario[]>("/demo/scenarios"),
  demoRun: (scenarioId: string, lat?: number | null, lng?: number | null, sessionId?: string) =>
    request<DemoRun>("/demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_id: scenarioId, latitude: lat ?? null, longitude: lng ?? null, session_id: sessionId ?? null }),
    }),
  demoEnroll: (samples = 3) =>
    request<{ status: string; num_samples: number; mode: string }>("/demo/enroll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ samples }),
    }),

  // admin
  adminAnalytics: () => request<Analytics>("/admin/analytics"),
  adminAudit: () => request<AuditLog[]>("/admin/audit"),
  adminUsers: () => request<AdminUser[]>("/admin/users"),
  adminSetRoles: (userId: string, roles: string[]) =>
    request<AdminUser>(`/admin/users/${userId}/roles`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roles }),
    }),
  adminSetActive: (userId: string, isActive: boolean) =>
    request<AdminUser>(`/admin/users/${userId}/active?active=${isActive}`, {
      method: "PATCH",
    }),
  adminSessions: () => request<Record<string, unknown>[]>("/admin/sessions"),
  adminSettings: () => request<Setting[]>("/admin/settings"),
  adminUpdateSetting: (key: string, value: string) =>
    request<Setting>(`/admin/settings/${key}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    }),
  adminHospitals: () => request<HospitalAdmin[]>("/admin/hospitals"),
  adminAddHospital: (payload: Omit<HospitalAdmin, "id" | "created_at">) =>
    request<HospitalAdmin>("/admin/hospitals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
};
