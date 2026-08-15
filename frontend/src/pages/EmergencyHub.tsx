import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type {
  ContactAction,
  HospitalNearby,
  IdentifyResult,
  PublicSummary,
  ResponderProfile,
  TimelineEvent,
} from "../api/types";
import { useEmergency } from "../context/EmergencyContext";
import { useAuth } from "../context/AuthContext";
import { useGeolocation } from "../hooks/useGeolocation";
import { StatusBadge, ScoreBar } from "../components/StatusBadge";
import { QualityPanel } from "../components/QualityPanel";
import { fmtKm, fmtTime } from "../utils/format";

type Tab = "result" | "medical" | "contact" | "location" | "timeline";

export function EmergencyHub() {
  const { sessionId: routeId } = useParams();
  const navigate = useNavigate();
  const { sessionId, result, previewImage, setResult } = useEmergency();
  const { hasRole } = useAuth();

  const sid = routeId ?? sessionId;
  const [tab, setTab] = useState<Tab>("result");
  const [error, setError] = useState<string | null>(null);
  const [medical, setMedical] = useState<PublicSummary | null>(null);
  const [responder, setResponder] = useState<ResponderProfile | null>(null);
  const [contact, setContact] = useState<ContactAction | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[] | null>(null);
  const [hospitals, setHospitals] = useState<HospitalNearby[] | null>(null);
  const geo = useGeolocation(false);
  const [locCoords, setLocCoords] = useState<{ latitude: number; longitude: number } | null>(null);
  const [sentLocation, setSentLocation] = useState(false);
  const [busy, setBusy] = useState(false);

  const id = sid as string;

  const loadMedical = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const m = await api.medicalSummary(id);
      setMedical(m);
      if (hasRole("medical_responder", "police_responder", "admin")) {
        setResponder(await api.responderProfile(id));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Medical summary unavailable.");
    }
  }, [id, hasRole]);

  const loadTimeline = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      setTimeline(await api.timeline(id));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Timeline unavailable.");
    }
  }, [id]);

  const loadHospitals = useCallback(async (lat: number, lng: number) => {
    setError(null);
    try {
      setHospitals(await api.nearbyHospitals(lat, lng, 30));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Hospital lookup failed.");
    }
  }, []);

  const onTab = (t: Tab) => {
    setTab(t);
    if (t === "medical") loadMedical();
    if (t === "timeline") loadTimeline();
    if (t === "location") {
      geo.request();
      if (geo.coords) loadHospitals(geo.coords.latitude, geo.coords.longitude);
    }
  };

  const useGeolocationNow = async () => {
    geo.request();
  };

  useEffect(() => {
    if (geo.coords && tab === "location") {
      setLocCoords({ latitude: geo.coords.latitude, longitude: geo.coords.longitude });
      loadHospitals(geo.coords.latitude, geo.coords.longitude);
    }
  }, [geo.coords, tab, loadHospitals]);

  const useManualCoords = (lat: number, lng: number) => {
    setLocCoords({ latitude: lat, longitude: lng });
    loadHospitals(lat, lng);
  };

  const sendLocation = async () => {
    if (!locCoords) return;
    setBusy(true);
    setError(null);
    try {
      await api.sendLocation(id, locCoords.latitude, locCoords.longitude, "manual");
      setSentLocation(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not send location.");
    } finally {
      setBusy(false);
    }
  };

  const contactAction = async (action: "call" | "sms" | "share_location") => {
    setBusy(true);
    setError(null);
    try {
      setContact(await api.contactAction(id, action));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Action failed.");
    } finally {
      setBusy(false);
    }
  };

  const confirmCandidate = async (candidateUserId: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.confirm(id, candidateUserId, true);
      if (result) {
        const updated: IdentifyResult = { ...result, status: "CONFIRMED", requires_human_confirmation: false };
        setResult(updated, previewImage);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Confirmation failed.");
    } finally {
      setBusy(false);
    }
  };

  if (!id) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 text-center">
        <p className="text-slate-400">No emergency session in progress.</p>
        <button onClick={() => navigate("/emergency")} className="btn-primary mt-4">
          Start a session
        </button>
      </div>
    );
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "result", label: "Match result" },
    { key: "medical", label: "Medical alert" },
    { key: "contact", label: "Emergency contact" },
    { key: "location", label: "Location & hospitals" },
    { key: "timeline", label: "Timeline" },
  ];

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Emergency response</h1>
          <p className="text-sm text-slate-400">Session code {result ? id.slice(0, 8) : id}</p>
        </div>
        <StatusBadge status={result?.status ?? "NO_MATCH"} />
      </div>

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
              tab === t.key
                ? "border-b-2 border-accent-500 text-accent-400"
                : "text-slate-400 hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-6 space-y-6">
        {tab === "result" && result && <MatchResultSection result={result} preview={previewImage} onConfirm={confirmCandidate} canConfirm={hasRole("medical_responder", "police_responder", "admin")} busy={busy} />}

        {tab === "medical" && (
          <div className="space-y-6">
            {medical && <PublicMedicalSummary summary={medical} />}
            {responder && (
              <ResponderExtras profile={responder} />
            )}
            {!medical && (
              <div className="card text-center text-sm text-slate-400">
                Medical alerts become available after a reliable identification.
              </div>
            )}
          </div>
        )}

        {tab === "contact" && (
          <div className="card space-y-4">
            <h2 className="font-semibold text-white">Notify emergency contact</h2>
            <div className="flex flex-wrap gap-3">
              <button onClick={() => contactAction("call")} className="btn-primary" disabled={busy}>
                Call contact
              </button>
              <button onClick={() => contactAction("sms")} className="btn-ghost" disabled={busy}>
                Send SMS
              </button>
              <button onClick={() => contactAction("share_location")} className="btn-ghost" disabled={busy}>
                Share location
              </button>
            </div>
            {contact && (
              <div className="rounded-lg border border-accent-500/30 bg-accent-500/10 p-4 text-sm">
                <p className="font-medium text-white">
                  {contact.contact_name ?? "Emergency contact"} · {contact.contact_phone ?? "—"}
                </p>
                <p className="mt-1 text-accent-400">Action logged: {contact.action} at {fmtTime(contact.logged_at)}</p>
              </div>
            )}
          </div>
        )}

        {tab === "location" && (
          <div className="card space-y-4">
            <h2 className="font-semibold text-white">Location & nearby hospitals</h2>
            <div className="flex flex-wrap gap-3">
              <button onClick={useGeolocationNow} className="btn-primary" disabled={busy}>
                Use my location
              </button>
              <button
                onClick={() => useManualCoords(28.6139, 77.209)}
                className="btn-ghost"
                disabled={busy}
              >
                Use demo coords (Delhi)
              </button>
            </div>
            {geo.error && <p className="text-xs text-danger-400">{geo.error}</p>}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-ink-900 p-4">
                <label className="label">Manual latitude</label>
                <input
                  className="input"
                  type="number"
                  step="0.0001"
                  value={locCoords?.latitude ?? ""}
                  onChange={(e) =>
                    setLocCoords((c) => ({ ...(c ?? { longitude: 0 }), latitude: Number(e.target.value) }))
                  }
                />
                <label className="label mt-3">Manual longitude</label>
                <input
                  className="input"
                  type="number"
                  step="0.0001"
                  value={locCoords?.longitude ?? ""}
                  onChange={(e) =>
                    setLocCoords((c) => ({ ...(c ?? { latitude: 0 }), longitude: Number(e.target.value) }))
                  }
                />
                <button onClick={() => locCoords && loadHospitals(locCoords.latitude, locCoords.longitude)} className="btn-ghost mt-3 w-full">
                  Find hospitals here
                </button>
              </div>

              <div className="rounded-lg border border-slate-800 bg-ink-900 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-300">Current location</span>
                  {locCoords && <span className="badge bg-emerald-500/15 text-emerald-300">set</span>}
                </div>
                {locCoords ? (
                  <p className="mt-1 font-mono text-sm text-slate-400">
                    {locCoords.latitude.toFixed(4)}, {locCoords.longitude.toFixed(4)}
                  </p>
                ) : (
                  <p className="mt-1 text-sm text-slate-500">No location set yet.</p>
                )}
                <button onClick={sendLocation} className="btn-primary mt-3 w-full" disabled={busy || !locCoords}>
                  {sentLocation ? "Location sent" : "Send location to session"}
                </button>
              </div>
            </div>

            <div>
              <h3 className="mb-3 font-semibold text-white">Nearby hospitals</h3>
              {hospitals === null && <p className="text-sm text-slate-500">Set a location to see nearby hospitals.</p>}
              {hospitals && hospitals.length === 0 && (
                <p className="text-sm text-slate-500">No hospitals found within range.</p>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                {hospitals?.map((h) => (
                  <div key={h.id} className="rounded-lg border border-slate-800 bg-ink-900 p-4">
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="font-medium text-white">{h.name}</h4>
                      <span className="whitespace-nowrap font-mono text-xs text-accent-400">{fmtKm(h.distance_km)}</span>
                    </div>
                    {h.address && <p className="mt-1 text-xs text-slate-400">{h.address}</p>}
                    <div className="mt-2 flex gap-2">
                      <span className={`badge ${h.emergency_available ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-700 text-slate-400"}`}>
                        {h.emergency_available ? "Emergency" : "Non-emergency"}
                      </span>
                      <span className={`badge ${h.availability_verified ? "bg-accent-500/15 text-accent-400" : "bg-warn-400/15 text-warn-400"}`}>
                        {h.availability_verified ? "Verified" : "Unverified"}
                      </span>
                    </div>
                    {h.phone && <p className="mt-2 text-xs text-slate-400">{h.phone}</p>}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "timeline" && (
          <div className="card">
            <h2 className="mb-4 font-semibold text-white">Session timeline</h2>
            {timeline === null && <p className="text-sm text-slate-500">Loading…</p>}
            {timeline && timeline.length === 0 && <p className="text-sm text-slate-500">No events recorded yet.</p>}
            <ol className="relative space-y-4 border-l border-slate-800 pl-5">
              {timeline?.map((ev, i) => (
                <li key={i} className="relative">
                  <span className="absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full bg-accent-500" />
                  <p className="text-sm font-medium text-white">{ev.action}</p>
                  <p className="text-xs text-slate-500">{fmtTime(ev.at)}</p>
                  {ev.details && (
                    <pre className="mt-1 overflow-x-auto rounded bg-ink-900 p-2 text-[11px] text-slate-400">
                      {JSON.stringify(ev.details, null, 1)}
                    </pre>
                  )}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </div>
  );
}

function MatchResultSection({
  result,
  preview,
  onConfirm,
  canConfirm,
  busy,
}: {
  result: IdentifyResult;
  preview: string | null;
  onConfirm: (userId: string) => void;
  canConfirm: boolean;
  busy: boolean;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <div className="lg:col-span-2">
        {preview ? (
          <img src={preview} alt="Victim capture" className="aspect-[3/4] w-full rounded-xl border border-slate-800 object-cover" />
        ) : (
          <div className="flex aspect-[3/4] w-full items-center justify-center rounded-xl border border-slate-800 bg-ink-950 text-slate-600">
            No preview
          </div>
        )}
      </div>

      <div className="space-y-5 lg:col-span-3">
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-white">Identification result</h2>
            <StatusBadge status={result.status} />
          </div>
          <p className="text-sm text-slate-300">{result.human_readable}</p>
          <ScoreBar value={result.confidence} thresholdHigh={0.82} thresholdReview={0.62} />

          <div className="flex flex-wrap gap-2">
            {result.method.map((m) => (
              <span key={m} className="badge bg-slate-700 text-slate-300">
                {m.replace(/_/g, " ")}
              </span>
            ))}
            {result.fallback_used && (
              <span className="badge bg-warn-400/15 text-warn-400">fallback used</span>
            )}
          </div>

          {result.requires_human_confirmation && (
            <div className="rounded-lg border border-warn-400/30 bg-warn-400/10 p-3 text-sm text-warn-400">
              This match is below the high-confidence threshold and requires human
              confirmation before medical alerts are shared.
            </div>
          )}

          {canConfirm && result.candidates.length > 0 && (
            <button
              onClick={() => onConfirm(result.candidates[0].user_id)}
              className="btn-primary w-full"
              disabled={busy || result.status === "CONFIRMED"}
            >
              {result.status === "CONFIRMED" ? "Identity confirmed" : "Confirm identity"}
            </button>
          )}
        </div>

        {result.candidates.length > 0 && (
          <div className="card">
            <h3 className="mb-3 font-semibold text-white">Candidate matches</h3>
            <ul className="space-y-2">
              {result.candidates.map((c) => (
                <li key={c.user_id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-ink-900 p-3">
                  <div>
                    <span className="text-sm font-medium text-white">#{c.rank}</span>
                    <span className="ml-2 text-sm text-slate-400">{c.user_id.slice(0, 12)}…</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-accent-400">{Math.round(c.confidence * 100)}%</span>
                    <span className={`badge ${c.status === "accepted" ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-700 text-slate-400"}`}>
                      {c.status}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {result.quality && <QualityPanel quality={result.quality} />}
      </div>
    </div>
  );
}

function PublicMedicalSummary({ summary }: { summary: PublicSummary }) {
  return (
    <div className="card">
      <h2 className="mb-1 font-semibold text-white">Medical alert</h2>
      <p className="text-sm text-slate-500">Treatment-critical information for {summary.full_name}</p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-800 bg-ink-900 p-4">
          <p className="label">Age</p>
          <p className="text-lg text-white">{summary.age ?? "—"}</p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-ink-900 p-4">
          <p className="label">Blood group</p>
          <p className="text-lg font-mono text-white">{summary.blood_group ?? "—"}</p>
        </div>
      </div>

      {summary.emergency_warnings.length > 0 && (
        <div className="mt-4 rounded-lg border border-danger-500/30 bg-danger-500/10 p-4">
          <p className="mb-2 text-sm font-semibold text-danger-400">Critical warnings</p>
          <ul className="list-inside list-disc space-y-1 text-sm text-danger-300">
            {summary.emergency_warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <div>
          <p className="label">Allergies</p>
          <div className="flex flex-wrap gap-1.5">
            {summary.critical_allergies.length === 0 && <span className="text-sm text-slate-500">None recorded</span>}
            {summary.critical_allergies.map((a) => (
              <span key={a} className="badge bg-danger-500/15 text-danger-400">{a}</span>
            ))}
          </div>
        </div>
        <div>
          <p className="label">Conditions</p>
          <div className="flex flex-wrap gap-1.5">
            {summary.critical_conditions.length === 0 && <span className="text-sm text-slate-500">None recorded</span>}
            {summary.critical_conditions.map((c) => (
              <span key={c} className="badge bg-warn-400/15 text-warn-400">{c}</span>
            ))}
          </div>
        </div>
        <div>
          <p className="label">Medications</p>
          <div className="flex flex-wrap gap-1.5">
            {summary.critical_medications.length === 0 && <span className="text-sm text-slate-500">None recorded</span>}
            {summary.critical_medications.map((m) => (
              <span key={m} className="badge bg-slate-700 text-slate-300">{m}</span>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-slate-800 bg-ink-900 p-4 text-sm">
        <p className="label">Emergency contact</p>
        <p className="text-white">{summary.emergency_contact.name ?? "—"}</p>
        <p className="text-slate-400">
          {summary.emergency_contact.relationship ? `${summary.emergency_contact.relationship} · ` : ""}
          {summary.emergency_contact.phone ?? "no phone"}
        </p>
      </div>
    </div>
  );
}

function ResponderExtras({ profile }: { profile: ResponderProfile }) {
  return (
    <div className="card">
      <h2 className="mb-3 font-semibold text-white">Responder profile (authorized only)</h2>
      <div className="space-y-4 text-sm">
        {Object.entries(profile.additional).map(([k, v]) => (
          <div key={k} className="rounded-lg border border-slate-800 bg-ink-900 p-3">
            <p className="label">{k.replace(/_/g, " ")}</p>
            <p className="text-slate-200">{String(v)}</p>
          </div>
        ))}
        {profile.visible_features.length > 0 && (
          <div>
            <p className="label mb-2">Visible identifying features</p>
            <div className="flex flex-wrap gap-2">
              {profile.visible_features.map((f, i) => (
                <span key={i} className="badge bg-accent-500/15 text-accent-400">
                  {f.feature_type} · {f.description}
                </span>
              ))}
            </div>
          </div>
        )}
        {profile.all_contacts.length > 0 && (
          <div>
            <p className="label mb-2">All emergency contacts</p>
            <ul className="space-y-1">
              {profile.all_contacts.map((c, i) => (
                <li key={i} className="text-slate-300">
                  {c.name} {c.relationship ? `(${c.relationship})` : ""} — {c.phone}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
