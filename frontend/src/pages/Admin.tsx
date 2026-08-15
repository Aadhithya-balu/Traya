import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { AdminUser, Analytics, AuditLog, HospitalAdmin, Setting } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";

const ROLES = ["registered", "medical_responder", "police_responder", "auditor", "admin"];

type Tab = "analytics" | "users" | "settings" | "hospitals" | "audit";

export function Admin() {
  const [tab, setTab] = useState<Tab>("analytics");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [settings, setSettings] = useState<Setting[]>([]);
  const [hospitals, setHospitals] = useState<HospitalAdmin[]>([]);
  const [audit, setAudit] = useState<AuditLog[]>([]);

  const onTab = (t: Tab) => {
    setTab(t);
    setError(null);
    if (t === "analytics") api.adminAnalytics().then(setAnalytics).catch(fail);
    if (t === "users") api.adminUsers().then(setUsers).catch(fail);
    if (t === "settings") api.adminSettings().then(setSettings).catch(fail);
    if (t === "hospitals") api.adminHospitals().then(setHospitals).catch(fail);
    if (t === "audit") api.adminAudit().then(setAudit).catch(fail);
  };

  useEffect(() => {
    onTab("analytics");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fail = (err: unknown) => setError(err instanceof ApiError ? err.detail : "Request failed.");

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

  const tabs: { key: Tab; label: string }[] = [
    { key: "analytics", label: "Analytics" },
    { key: "users", label: "Users" },
    { key: "settings", label: "Settings" },
    { key: "hospitals", label: "Hospitals" },
    { key: "audit", label: "Audit log" },
  ];

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="text-3xl font-bold text-white">Admin console</h1>
      <p className="mt-1 text-sm text-slate-400">Platform analytics, user management and configuration.</p>

      {error && (
        <div className="mt-4 rounded-lg border border-danger-500/30 bg-danger-500/10 p-3 text-sm text-danger-400">
          {error}
        </div>
      )}

      <div className="mt-6 flex gap-1 overflow-x-auto border-b border-slate-800">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => onTab(t.key)}
            className={`whitespace-nowrap rounded-t-lg px-4 py-2 text-sm font-medium ${
              tab === t.key ? "border-b-2 border-accent-500 text-accent-400" : "text-slate-400 hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === "analytics" && analytics && (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Users" value={analytics.total_users} />
              <Stat label="Enrolled" value={analytics.total_enrolled} />
              <Stat label="Sessions" value={analytics.total_sessions} />
              <Stat label="Identification rate" value={`${Math.round(analytics.identification_rate * 100)}%`} />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="card">
                <h3 className="mb-3 font-semibold text-white">Identifications by day</h3>
                {analytics.identifications_by_day.length === 0 ? (
                  <p className="text-sm text-slate-500">No data yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {analytics.identifications_by_day.map((d) => (
                      <li key={d.day} className="flex items-center justify-between text-sm">
                        <span className="text-slate-400">{d.day}</span>
                        <span className="font-mono text-white">{d.count}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="card">
                <h3 className="mb-3 font-semibold text-white">Outcomes</h3>
                {analytics.status_breakdown.map((s) => (
                  <div key={s.status} className="flex items-center justify-between py-1 text-sm">
                    <StatusBadge status={s.status} />
                    <span className="font-mono text-white">{s.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "users" && (
          <div className="card">
            <h2 className="mb-4 font-semibold text-white">Users ({users.length})</h2>
            <div className="space-y-3">
              {users.map((u) => (
                <div key={u.id} className="rounded-lg border border-slate-800 bg-ink-900 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-white">
                        {u.full_name} {u.is_demo && <span className="badge ml-2 bg-slate-700 text-slate-400">demo</span>}
                      </p>
                      <p className="text-xs text-slate-500">{u.email} · {u.id.slice(0, 12)}…</p>
                    </div>
                    <button
                      onClick={() => setActive(u, !u.is_active)}
                      className={`badge border ${u.is_active ? "bg-emerald-500/15 text-emerald-300" : "bg-danger-500/15 text-danger-400"}`}
                      disabled={busy}
                    >
                      {u.is_active ? "active" : "disabled"} — click to toggle
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
                            ? "border-accent-500 bg-accent-500/15 text-accent-400"
                            : "border-slate-700 text-slate-400 hover:border-slate-500"
                        }`}
                        disabled={busy}
                      >
                        {r.replace(/_/g, " ")}
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
            <h2 className="mb-4 font-semibold text-white">Runtime settings</h2>
            <ul className="space-y-2">
              {settings.map((s) => (
                <li key={s.key} className="rounded-lg border border-slate-800 bg-ink-900 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="font-mono text-sm text-white">{s.key}</p>
                      {s.description && <p className="text-xs text-slate-500">{s.description}</p>}
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
              <h2 className="mb-4 font-semibold text-white">Registered hospitals ({hospitals.length})</h2>
              <ul className="space-y-2">
                {hospitals.map((h) => (
                  <li key={h.id} className="rounded-lg border border-slate-800 bg-ink-900 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-medium text-white">{h.name}</p>
                        {h.address && <p className="text-xs text-slate-500">{h.address}</p>}
                        {h.phone && <p className="text-xs text-slate-500">{h.phone}</p>}
                      </div>
                      <div className="flex flex-col gap-1 text-right">
                        <span className={`badge ${h.emergency_available ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-700 text-slate-400"}`}>
                          {h.emergency_available ? "emergency" : "non-emergency"}
                        </span>
                        <span className={`badge ${h.availability_verified ? "bg-accent-500/15 text-accent-400" : "bg-warn-400/15 text-warn-400"}`}>
                          {h.availability_verified ? "verified" : "unverified"}
                        </span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>

            <form onSubmit={addHospital} className="card h-fit space-y-3">
              <h2 className="font-semibold text-white">Add hospital</h2>
              <input name="name" className="input" placeholder="Name" required />
              <input name="address" className="input" placeholder="Address" />
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <input name="latitude" className="input" placeholder="Latitude" type="number" step="0.0001" />
                <input name="longitude" className="input" placeholder="Longitude" type="number" step="0.0001" />
              </div>
              <input name="phone" className="input" placeholder="Phone" />
              <div className="flex gap-4">
                <label className="flex items-center gap-1.5 text-sm text-slate-400">
                  <input type="checkbox" name="emergency" className="accent-accent-500" defaultChecked />
                  Emergency dept
                </label>
                <label className="flex items-center gap-1.5 text-sm text-slate-400">
                  <input type="checkbox" name="verified" className="accent-accent-500" defaultChecked />
                  Availability verified
                </label>
              </div>
              <button className="btn-primary w-full" disabled={busy}>Add hospital</button>
            </form>
          </div>
        )}

        {tab === "audit" && (
          <div className="card">
            <h2 className="mb-4 font-semibold text-white">Audit log ({audit.length})</h2>
            <ul className="max-h-[60vh] space-y-2 overflow-y-auto">
              {audit.map((a) => (
                <li key={a.id} className="rounded-lg border border-slate-800 bg-ink-900 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-white">{a.action}</span>
                    <span className="text-xs text-slate-500">{new Date(a.created_at).toLocaleString()}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {a.actor_type} {a.actor_id ? `· ${a.actor_id.slice(0, 12)}…` : ""} · {a.resource_type ?? "—"} {a.resource_id ?? ""}
                  </p>
                  {a.details && Object.keys(a.details).length > 0 && (
                    <pre className="mt-2 overflow-x-auto rounded bg-ink-950 p-2 text-[11px] text-slate-400">
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

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold text-white">{value}</p>
    </div>
  );
}
