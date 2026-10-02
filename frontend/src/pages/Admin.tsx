import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { AdminUser, Analytics, AuditLog, HospitalAdmin, Role, Setting } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n, type StringKey } from "../i18n";

/**
 * The assignable roles, in the order they should read on screen.
 *
 * "registered" was never a role: the backend seeds "registered_user", and
 * assigning "registered" matched no row in role_permissions, so the toggle
 * silently granted nothing and the user appeared to have a role they did not
 * have. "hospital" was missing from the list entirely, so hospital staff
 * accounts could not be provisioned through the UI at all. Both lists are
 * asserted against ROLE_PERMISSIONS in backend/tests/test_rbac_matrix.py.
 */
const ROLES: readonly Role[] = [
  "registered_user",
  "medical_responder",
  "police_responder",
  "hospital",
  "auditor",
  "admin",
];

type Tab = "analytics" | "users" | "settings" | "hospitals" | "audit";

export function Admin() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("analytics");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [settings, setSettings] = useState<Setting[]>([]);
  const [hospitals, setHospitals] = useState<HospitalAdmin[]>([]);
  const [audit, setAudit] = useState<AuditLog[]>([]);

  const fail = (err: unknown) =>
    setError(err instanceof ApiError ? err.detail : t("error.generic"));

  const onTab = (next: Tab) => {
    setTab(next);
    setError(null);
    if (next === "analytics") api.adminAnalytics().then(setAnalytics).catch(fail);
    if (next === "users") api.adminUsers().then(setUsers).catch(fail);
    if (next === "settings") api.adminSettings().then(setSettings).catch(fail);
    if (next === "hospitals") api.adminHospitals().then(setHospitals).catch(fail);
    if (next === "audit") api.adminAudit().then(setAudit).catch(fail);
  };

  useEffect(() => {
    onTab("analytics");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setRoles = async (user: AdminUser, roles: string[]) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.adminSetRoles(user.id, roles);
      setUsers((prev) => prev.map((u) => (u.id === user.id ? { ...u, roles: updated.roles } : u)));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const setActive = async (user: AdminUser, isActive: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api.adminSetActive(user.id, isActive);
      setUsers((prev) => prev.map((u) => (u.id === user.id ? { ...u, is_active: isActive } : u)));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const updateSetting = async (key: string, value: string) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.adminUpdateSetting(key, value);
      setSettings((prev) => prev.map((s) => (s.key === key ? updated : s)));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const addHospital = async (e: FormEvent) => {
    e.preventDefault();
    const form = new FormData(e.target as HTMLFormElement);
    setBusy(true);
    setError(null);
    try {
      const h = await api.adminAddHospital({
        name: String(form.get("name")),
        address: String(form.get("address") || "") || undefined,
        phone: String(form.get("phone") || "") || undefined,
        latitude: Number(form.get("latitude")) || undefined,
        longitude: Number(form.get("longitude")) || undefined,
        emergency_available: (form.get("emergency") as string) === "on",
        availability_verified: (form.get("verified") as string) === "on",
      });
      setHospitals((prev) => [...prev, h]);
      (e.target as HTMLFormElement).reset();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const tabs: { key: Tab; labelKey: StringKey }[] = [
    { key: "analytics", labelKey: "admin.tab.analytics" },
    { key: "users", labelKey: "admin.tab.users" },
    { key: "settings", labelKey: "admin.tab.settings" },
    { key: "hospitals", labelKey: "admin.tab.hospitals" },
    { key: "audit", labelKey: "admin.tab.audit" },
  ];

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="text-3xl font-bold text-text">{t("admin.console.title")}</h1>
      <p className="mt-1 text-sm text-muted">{t("admin.console.subtitle")}</p>

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger"
        >
          {error}
        </div>
      )}

      {/* `.scroll-x` not `flex overflow-x-auto`: the composed class also hides the
          scrollbar and bleeds to the screen edge. `tap` because these tabs are
          32px tall otherwise. */}
      <div className="scroll-x mt-6 border-b border-line">
        {tabs.map((entry) => (
          <button
            key={entry.key}
            onClick={() => onTab(entry.key)}
            className={`tap whitespace-nowrap rounded-t-lg px-4 py-2 text-sm font-medium ${
              tab === entry.key ? "border-b-2 border-accent text-accent" : "text-muted hover:text-text"
            }`}
          >
            {t(entry.labelKey)}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === "analytics" && analytics && (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat labelKey="admin.stat.users" value={analytics.total_users} />
              <Stat labelKey="admin.stat.enrolled" value={analytics.total_enrolled} />
              <Stat labelKey="admin.stat.sessions" value={analytics.total_sessions} />
              <Stat
                labelKey="admin.stat.identificationRate"
                value={`${Math.round(analytics.identification_rate * 100)}%`}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="card">
                <h3 className="mb-3 font-semibold text-text">{t("admin.analytics.byDay")}</h3>
                {analytics.identifications_by_day.length === 0 ? (
                  <p className="text-sm text-faint">{t("admin.analytics.noData")}</p>
                ) : (
                  <ul className="space-y-2">
                    {analytics.identifications_by_day.map((d) => (
                      <li key={d.day} className="flex items-center justify-between text-sm">
                        <span className="text-muted">{d.day}</span>
                        <span className="font-mono text-text">{d.count}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="card">
                <h3 className="mb-3 font-semibold text-text">{t("admin.analytics.outcomes")}</h3>
                {analytics.status_breakdown.map((s) => (
                  <div key={s.status} className="flex items-center justify-between py-1 text-sm">
                    <StatusBadge status={s.status} />
                    <span className="font-mono text-text">{s.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "users" && (
          <div className="card">
            <h2 className="mb-4 font-semibold text-text">
              {t("admin.users.heading", { count: users.length })}
            </h2>
            <div className="space-y-3">
              {users.map((u) => (
                <div key={u.id} className="rounded-lg border border-line bg-surface p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-text">
                        {u.full_name}{" "}
                        {u.is_demo && (
                          <span className="badge ml-2 bg-raised text-muted">{t("common.demoTag")}</span>
                        )}
                      </p>
                      <p className="text-xs text-faint">{u.email} · {u.id.slice(0, 12)}…</p>
                    </div>
                    {/*
                      The state and the action are one control, so they are one
                      string: rendering "active" alone would tell an admin what is
                      true without telling them what pressing it does.
                    */}
                    <button
                      onClick={() => setActive(u, !u.is_active)}
                      className={`badge border ${u.is_active ? "bg-ok/15 text-ok" : "bg-danger/15 text-danger"}`}
                      disabled={busy}
                    >
                      {u.is_active ? t("admin.user.active") : t("admin.user.disabled")}{" "}
                      <span className="opacity-80">— {t("admin.user.toggle")}</span>
                    </button>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {ROLES.map((r) => (
                      <button
                        key={r}
                        onClick={() =>
                          setRoles(
                            u,
                            u.roles.includes(r) ? u.roles.filter((x) => x !== r) : [...u.roles, r],
                          )
                        }
                        className={`badge border ${
                          u.roles.includes(r)
                            ? "border-accent bg-accent/15 text-accent"
                            : "border-line text-muted hover:border-line-strong"
                        }`}
                        disabled={busy}
                      >
                        {t(ROLE_LABELS[r])}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "settings" && (
          <div className="card">
            <h2 className="mb-4 font-semibold text-text">{t("admin.settings.heading")}</h2>
            {/*
              The key and its description come from the backend's seeded
              `system_settings` rows, so they render as data. The rows are
              editable in place, which is why this tab has no static copy of its
              own beyond the heading.
            */}
            <ul className="space-y-2">
              {settings.map((s) => (
                <li key={s.key} className="rounded-lg border border-line bg-surface p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="font-mono text-sm text-text">{s.key}</p>
                      {s.description && <p className="text-xs text-faint">{s.description}</p>}
                    </div>
                    <input
                      className="input max-w-64 font-mono text-sm"
                      defaultValue={s.value}
                      onBlur={(e) => e.target.value !== s.value && updateSetting(s.key, e.target.value)}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {tab === "hospitals" && (
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="card">
              <h2 className="mb-4 font-semibold text-text">
                {t("admin.hospitals.heading", { count: hospitals.length })}
              </h2>
              <ul className="space-y-2">
                {hospitals.map((h) => (
                  <li key={h.id} className="rounded-lg border border-line bg-surface p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-medium text-text">{h.name}</p>
                        {h.address && <p className="text-xs text-faint">{h.address}</p>}
                        {h.phone && <p className="text-xs text-faint">{h.phone}</p>}
                      </div>
                      <div className="flex flex-col gap-1 text-right">
                        <span className={`badge ${h.emergency_available ? "bg-ok/15 text-ok" : "bg-raised text-muted"}`}>
                          {h.emergency_available ? t("admin.hospital.emergency") : t("admin.hospital.nonEmergency")}
                        </span>
                        <span className={`badge ${h.availability_verified ? "bg-accent/15 text-accent" : "bg-warn/15 text-warn"}`}>
                          {h.availability_verified ? t("admin.hospital.verified") : t("admin.hospital.unverified")}
                        </span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>

            <form onSubmit={addHospital} className="card h-fit space-y-3">
              <h2 className="font-semibold text-text">{t("admin.hospital.form.title")}</h2>
              <label className="sr-only" htmlFor="hospital-name">{t("admin.hospital.field.name")}</label>
              <input id="hospital-name" name="name" className="input" placeholder={t("admin.hospital.field.name")} required />
              <label className="sr-only" htmlFor="hospital-address">{t("admin.hospital.field.address")}</label>
              <input id="hospital-address" name="address" className="input" placeholder={t("admin.hospital.field.address")} />
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="sr-only" htmlFor="hospital-lat">{t("admin.hospital.field.latitude")}</label>
                <input id="hospital-lat" name="latitude" className="input" placeholder={t("admin.hospital.field.latitude")} type="number" step="0.0001" />
                <label className="sr-only" htmlFor="hospital-lng">{t("admin.hospital.field.longitude")}</label>
                <input id="hospital-lng" name="longitude" className="input" placeholder={t("admin.hospital.field.longitude")} type="number" step="0.0001" />
              </div>
              <label className="sr-only" htmlFor="hospital-phone">{t("admin.hospital.field.phone")}</label>
              <input id="hospital-phone" name="phone" className="input" placeholder={t("admin.hospital.field.phone")} />
              <div className="flex gap-4">
                <label className="flex items-center gap-1.5 text-sm text-muted">
                  <input type="checkbox" name="emergency" className="accent-accent" defaultChecked />
                  {t("admin.hospital.field.emergencyDept")}
                </label>
                <label className="flex items-center gap-1.5 text-sm text-muted">
                  <input type="checkbox" name="verified" className="accent-accent" defaultChecked />
                  {t("admin.hospital.field.verified")}
                </label>
              </div>
              <button className="btn-primary w-full" disabled={busy}>{t("admin.hospital.form.submit")}</button>
            </form>
          </div>
        )}

        {tab === "audit" && (
          <div className="card">
            <h2 className="mb-4 font-semibold text-text">
              {t("admin.audit.heading", { count: audit.length })}
            </h2>
            <ul className="max-h-[60vh] space-y-2 overflow-y-auto">
              {audit.map((a) => (
                <li key={a.id} className="rounded-lg border border-line bg-surface p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-text">{a.action}</span>
                    <span className="text-xs text-faint">{new Date(a.created_at).toLocaleString()}</span>
                  </div>
                  <p className="mt-1 text-xs text-faint">
                    {a.actor_type} {a.actor_id ? `· ${a.actor_id.slice(0, 12)}…` : ""} · {a.resource_type ?? "—"} {a.resource_id ?? ""}
                  </p>
                  {a.details && Object.keys(a.details).length > 0 && (
                    <pre className="mt-2 overflow-x-auto rounded bg-raised p-2 text-[11px] text-muted">
                      {JSON.stringify(a.details, null, 1)}
                    </pre>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Role names for the assignment toggles.
 *
 * The slug is a backend contract and must not be translated; the label shown
 * beside it is copy. Typed as a total map over `Role` so adding a role to the
 * seed without adding a label is a typecheck failure rather than a raw slug
 * appearing in the console.
 */
const ROLE_LABELS: Record<Role, StringKey> = {
  public: "role.public",
  registered_user: "role.registered_user",
  medical_responder: "role.medical_responder",
  police_responder: "role.police_responder",
  hospital: "role.hospital",
  auditor: "role.auditor",
  admin: "role.admin",
};

function Stat({ labelKey, value }: { labelKey: StringKey; value: number | string }) {
  const { t } = useI18n();
  return (
    <div className="card">
      <p className="text-xs uppercase tracking-wide text-faint">{t(labelKey)}</p>
      <p className="mt-1 text-2xl font-bold text-text">{value}</p>
    </div>
  );
}