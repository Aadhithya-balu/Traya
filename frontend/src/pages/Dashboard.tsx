import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { BiometricStatus, Consent, EmergencyContact, MedicalProfile, TimelineEvent } from "../api/types";
import { useAuth } from "../context/AuthContext";

export function Dashboard() {
  const { user } = useAuth();
  const [bio, setBio] = useState<BiometricStatus | null>(null);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [medical, setMedical] = useState<MedicalProfile | null>(null);
  const [contacts, setContacts] = useState<EmergencyContact[]>([]);
  const [history, setHistory] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [b, c, m, ct, h] = await Promise.all([
        api.biometricStatus(),
        api.listConsents(),
        api.getMedical(),
        api.listContacts(),
        api.accessHistory(),
      ]);
      setBio(b);
      setConsents(c);
      setMedical(m);
      setContacts(ct);
      setHistory(h);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load dashboard data.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const bioConsent = consents.find((c) => c.consent_type === "biometric_enrollment");

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">Dashboard</h1>
          <p className="mt-1 text-sm text-slate-400">{user?.full_name} · {user?.email}</p>
        </div>
        <div className="flex gap-2">
          {user?.roles.map((r) => (
            <span key={r} className="badge bg-slate-700 text-slate-300">
              {r.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-danger-500/30 bg-danger-500/10 p-3 text-sm text-danger-400">
          {error}
        </div>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatusCard
          label="Biometric enrollment"
          value={bio?.status ?? "—"}
          good={bio?.status === "ENROLLED"}
        />
        <StatusCard
          label="Biometric consent"
          value={bioConsent?.status ?? "NOT GRANTED"}
          good={bioConsent?.status === "granted"}
        />
        <StatusCard label="Emergency contacts" value={String(contacts.length)} good={contacts.length > 0} />
        <StatusCard label="Blood group" value={medical?.blood_group ?? "—"} good={!!medical?.blood_group} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 font-semibold text-white">Be identified in an emergency</h2>
          {bio?.status === "ENROLLED" ? (
            <p className="text-sm text-slate-400">
              Your face template is enrolled ({bio.num_samples} samples, algorithm {bio.algo_version ?? "current"})
              and will be matched against emergency captures.
            </p>
          ) : (
            <p className="mb-3 text-sm text-slate-400">
              Face matching is what lets responders find you when you can't speak. It requires
              your explicit biometric consent and a few sample photos.
            </p>
          )}
          {bioConsent?.status !== "granted" ? (
            <Link to="/profile" className="btn-primary mt-2">
              Grant consent & enroll
            </Link>
          ) : bio?.status !== "ENROLLED" ? (
            <Link to="/profile" className="btn-primary mt-2">
              Enroll face samples
            </Link>
          ) : (
            <Link to="/profile" className="btn-ghost mt-2">
              Manage enrollment
            </Link>
          )}
        </div>

        <div className="card">
          <h2 className="mb-3 font-semibold text-white">Consents</h2>
          <ul className="space-y-2">
            {consents.length === 0 && (
              <li className="text-sm text-slate-500">No consents on record.</li>
            )}
            {consents.map((c) => (
              <li key={c.consent_type} className="flex items-center justify-between rounded-lg border border-slate-800 bg-ink-900 p-3">
                <span className="text-sm text-slate-300">{c.consent_type.replace(/_/g, " ")}</span>
                <span className={`badge ${c.status === "granted" ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-700 text-slate-400"}`}>
                  {c.status}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="mt-6 card">
        <h2 className="mb-3 font-semibold text-white">Recent access history</h2>
        {history.length === 0 && <p className="text-sm text-slate-500">No recorded access events.</p>}
        <ul className="space-y-2">
          {history.slice(0, 6).map((ev, i) => (
            <li key={i} className="flex items-center justify-between rounded-lg border border-slate-800 bg-ink-900 p-3">
              <span className="text-sm text-slate-300">{ev.action}</span>
              <span className="text-xs text-slate-500">{new Date(ev.at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function StatusCard({ label, value, good }: { label: string; value: string; good: boolean }) {
  return (
    <div className="card">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 truncate text-xl font-semibold ${good ? "text-emerald-300" : "text-slate-300"}`}>
        {value}
      </p>
    </div>
  );
}
