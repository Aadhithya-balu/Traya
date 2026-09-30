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
import { AlertIcon } from "../components/icons";
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
  /**
   * How the coordinates were obtained. The pipeline's context boost and the
   * incident record treat a GPS fix and a typed estimate as different evidence,
   * so this was previously lost: every fix was logged as "manual".
   */
  const [locSource, setLocSource] = useState<"gps" | "manual">("gps");
  const [sentLocation, setSentLocation] = useState(false);
  const [busy, setBusy] = useState(false);

  const id = sid as string;

  /** Never leak a driver error, and never blame the person's session. */
  const describe = (err: unknown, fallback: string) => {
    if (err instanceof ApiError) {
      if (err.isNetwork) return "Cannot reach the server. Check your connection.";
      if (err.status === 403) return "This emergency session has ended.";
      if (err.status === 404) return "This emergency session no longer exists.";
      return err.detail || fallback;
    }
    return fallback;
  };

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
      setError(describe(err, "Medical summary unavailable."));
    }
  }, [id, hasRole]);

  const loadTimeline = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      setTimeline(await api.timeline(id));
    } catch (err) {
      setError(describe(err, "Timeline unavailable."));
    }
  }, [id]);

  const loadHospitals = useCallback(async (lat: number, lng: number) => {
    setError(null);
    try {
      setHospitals(await api.nearbyHospitals(lat, lng, 30));
    } catch (err) {
      setError(describe(err, "Hospital lookup failed."));
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
      setLocSource("gps");
      loadHospitals(geo.coords.latitude, geo.coords.longitude);
    }
  }, [geo.coords, tab, loadHospitals]);

  const useManualCoords = (lat: number, lng: number) => {
    setLocCoords({ latitude: lat, longitude: lng });
    setLocSource("manual");
    loadHospitals(lat, lng);
  };

  const sendLocation = async () => {
    if (!locCoords) return;
    setBusy(true);
    setError(null);
    try {
      await api.sendLocation(id, locCoords.latitude, locCoords.longitude, locSource);
      setSentLocation(true);
    } catch (err) {
      setError(describe(err, "Could not send location."));
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
      setError(describe(err, "Action failed."));
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
      setError(describe(err, "Confirmation failed."));
    } finally {
      setBusy(false);
    }
  };

  if (!id) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 text-center">
        <p className="text-muted">No emergency session in progress.</p>
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
          <h1 className="text-2xl font-bold text-text">Emergency response</h1>
          <p className="text-sm text-muted">Session code {result ? id.slice(0, 8) : id}</p>
        </div>
        <StatusBadge status={result?.status ?? "NO_MATCH"} />
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </div>
      )}

      <div className="mt-6 flex gap-1 overflow-x-auto border-b border-line">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => onTab(t.key)}
            className={`whitespace-nowrap rounded-t-lg px-4 py-2 text-sm font-medium ${
              tab === t.key
                ? "border-b-2 border-accent text-accent"
                : "text-muted hover:text-text"
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
              <div className="card text-center text-sm text-muted">
                Medical alerts become available after a reliable identification.
              </div>
            )}
          </div>
        )}

        {tab === "contact" && (
          <div className="card space-y-4">
            <h2 className="font-semibold text-text">Notify emergency contact</h2>
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
              <div className="rounded-lg border border-accent/30 bg-accent/10 p-4 text-sm">
                <p className="font-medium text-text">
                  {contact.contact_name ?? "Emergency contact"} · {contact.contact_phone ?? "—"}
                </p>
                <p className="mt-1 text-accent">Action logged: {contact.action} at {fmtTime(contact.logged_at)}</p>
              </div>
            )}
          </div>
        )}

        {tab === "location" && (
          <div className="card space-y-4">
            <h2 className="font-semibold text-text">Location & nearby hospitals</h2>
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
            {geo.error && <p className="text-xs text-danger">{geo.error}</p>}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-lg border border-line bg-surface p-4">
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

              <div className="rounded-lg border border-line bg-surface p-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted">Current location</span>
                  {locCoords && <span className="badge bg-ok/15 text-ok">set</span>}
                </div>
                {locCoords ? (
                  <p className="mt-1 font-mono text-sm text-muted">
                    {locCoords.latitude.toFixed(4)}, {locCoords.longitude.toFixed(4)}
                  </p>
                ) : (
                  <p className="mt-1 text-sm text-faint">No location set yet.</p>
                )}
                <button onClick={sendLocation} className="btn-primary mt-3 w-full" disabled={busy || !locCoords}>
                  {sentLocation ? "Location sent" : "Send location to session"}
                </button>
              </div>
            </div>

            <div>
              <h3 className="mb-3 font-semibold text-text">Nearby hospitals</h3>
              {hospitals === null && <p className="text-sm text-faint">Set a location to see nearby hospitals.</p>}
              {hospitals && hospitals.length === 0 && (
                <p className="text-sm text-faint">No hospitals found within range.</p>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                {hospitals?.map((h) => (
                  <div key={h.id} className="rounded-lg border border-line bg-surface p-4">
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="font-medium text-text">{h.name}</h4>
                      <span className="whitespace-nowrap font-mono text-xs text-accent">{fmtKm(h.distance_km)}</span>
                    </div>
                    {h.address && <p className="mt-1 text-xs text-muted">{h.address}</p>}
                    <div className="mt-2 flex gap-2">
                      <span className={`badge ${h.emergency_available ? "bg-ok/15 text-ok" : "bg-raised text-muted"}`}>
                        {h.emergency_available ? "Emergency" : "Non-emergency"}
                      </span>
                      <span className={`badge ${h.availability_verified ? "bg-accent/15 text-accent" : "bg-warn/15 text-warn"}`}>
                        {h.availability_verified ? "Verified" : "Unverified"}
                      </span>
                    </div>
                    {h.phone && <p className="mt-2 text-xs text-muted">{h.phone}</p>}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "timeline" && (
          <div className="card">
            <h2 className="mb-4 font-semibold text-text">Session timeline</h2>
            {timeline === null && <p className="text-sm text-faint">Loading…</p>}
            {timeline && timeline.length === 0 && <p className="text-sm text-faint">No events recorded yet.</p>}
            <ol className="relative space-y-4 border-l border-line pl-5">
              {timeline?.map((ev, i) => (
                <li key={i} className="relative">
                  <span className="absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full bg-accent" />
                  <p className="text-sm font-medium text-text">{ev.action}</p>
                  <p className="text-xs text-faint">{fmtTime(ev.at)}</p>
                  {ev.details && (
                    <pre className="mt-1 overflow-x-auto rounded bg-surface p-2 text-[11px] text-muted">
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
          <img src={preview} alt="Victim capture" className="aspect-[3/4] w-full rounded-xl border border-line object-cover" />
        ) : (
          <div className="flex aspect-[3/4] w-full items-center justify-center rounded-xl border border-line bg-raised text-faint">
            No preview
          </div>
        )}
      </div>

      <div className="space-y-5 lg:col-span-3">
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-text">Identification result</h2>
            <StatusBadge status={result.status} />
          </div>
          <p className="text-sm text-muted">{result.human_readable}</p>
          <ScoreBar value={result.confidence} thresholdHigh={0.82} thresholdReview={0.62} />

          <EngineDisclosure result={result} />

          <div className="flex flex-wrap gap-2">
            {result.method.map((m) => (
              <span key={m} className="badge bg-raised text-muted">
                {m.replace(/_/g, " ")}
              </span>
            ))}
            {result.fallback_used && (
              <span className="badge bg-warn/15 text-warn">fallback used</span>
            )}
          </div>

          {result.requires_human_confirmation && (
            <div className="rounded-lg border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
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
            <h3 className="mb-3 font-semibold text-text">Candidate matches</h3>
            <ul className="space-y-2">
              {result.candidates.map((c) => (
                <li key={c.user_id} className="flex items-center justify-between rounded-lg border border-line bg-surface p-3">
                  <div>
                    <span className="text-sm font-medium text-text">#{c.rank}</span>
                    <span className="ml-2 text-sm text-muted">{c.user_id.slice(0, 12)}…</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-accent">{Math.round(c.confidence * 100)}%</span>
                    <span className={`badge ${c.status === "accepted" ? "bg-ok/15 text-ok" : "bg-raised text-muted"}`}>
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

/**
 * Says which engine produced the match, above the confidence bar.
 *
 * The current engine is a simulation: it reads twelve brightness measurements
 * off the image and calls them a face. The API reports `engine_mode` and
 * `demo_mode` on every result and the disclosure was previously never rendered,
 * so a responder saw a percentage with nothing saying where it came from. This
 * must stay above the score, not below it, and it must not be dismissible. The
 * honest reading of the current engine is in docs/AUDIT.md and ADR 0001.
 */
function EngineDisclosure({ result }: { result: IdentifyResult }) {
  const simulated =
    result.engine_mode === "simulation" || result.engine_mode === "demo";
  if (!simulated) {
    return (
      <p className="text-xs text-faint">
        Engine: {result.engine_mode}
        {result.algo_version ? ` · ${result.algo_version}` : ""}
      </p>
    );
  }
  return (
    <div
      className="rounded-lg border border-warn/40 bg-warn/10 p-3"
      role="note"
    >
      <p className="flex items-center gap-2 text-sm font-medium text-warn">
        <AlertIcon size={16} className="shrink-0" />
        Simulated match — not a biometric
      </p>
      <p className="mt-1.5 text-xs leading-relaxed text-muted">
        This engine does not detect faces. It scores brightness and contrast
        across the image and compares those numbers, so the confidence below
        reflects a simulation and not identity. Treat it as a prompt to look,
        never as a result. Mode: {result.engine_mode}
        {result.demo_mode ? " · demo data" : ""}
        {result.algo_version ? ` · ${result.algo_version}` : ""}
      </p>
    </div>
  );
}

function PublicMedicalSummary({ summary }: { summary: PublicSummary }) {
  return (
    <div className="card">
      <h2 className="mb-1 font-semibold text-text">Medical alert</h2>
      <p className="text-sm text-faint">Treatment-critical information for {summary.full_name}</p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-line bg-surface p-4">
          <p className="label">Age</p>
          <p className="text-lg text-text">{summary.age ?? "—"}</p>
        </div>
        <div className="rounded-lg border border-line bg-surface p-4">
          <p className="label">Blood group</p>
          <p className="text-lg font-mono text-text">{summary.blood_group ?? "—"}</p>
        </div>
      </div>

      {summary.emergency_warnings.length > 0 && (
        <div className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-4">
          <p className="mb-2 text-sm font-semibold text-danger">Critical warnings</p>
          <ul className="list-inside list-disc space-y-1 text-sm text-danger">
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
            {summary.critical_allergies.length === 0 && <span className="text-sm text-faint">None recorded</span>}
            {summary.critical_allergies.map((a) => (
              <span key={a} className="badge bg-danger/15 text-danger">{a}</span>
            ))}
          </div>
        </div>
        <div>
          <p className="label">Conditions</p>
          <div className="flex flex-wrap gap-1.5">
            {summary.critical_conditions.length === 0 && <span className="text-sm text-faint">None recorded</span>}
            {summary.critical_conditions.map((c) => (
              <span key={c} className="badge bg-warn/15 text-warn">{c}</span>
            ))}
          </div>
        </div>
        <div>
          <p className="label">Medications</p>
          <div className="flex flex-wrap gap-1.5">
            {summary.critical_medications.length === 0 && <span className="text-sm text-faint">None recorded</span>}
            {summary.critical_medications.map((m) => (
              <span key={m} className="badge bg-raised text-muted">{m}</span>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-line bg-surface p-4 text-sm">
        <p className="label">Emergency contact</p>
        <p className="text-text">{summary.emergency_contact.name ?? "—"}</p>
        <p className="text-muted">
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
      <h2 className="mb-3 font-semibold text-text">Responder profile (authorized only)</h2>
      <div className="space-y-4 text-sm">
        {Object.entries(profile.additional).map(([k, v]) => (
          <div key={k} className="rounded-lg border border-line bg-surface p-3">
            <p className="label">{k.replace(/_/g, " ")}</p>
            <p className="text-text">{String(v)}</p>
          </div>
        ))}
        {profile.visible_features.length > 0 && (
          <div>
            <p className="label mb-2">Visible identifying features</p>
            <div className="flex flex-wrap gap-2">
              {profile.visible_features.map((f, i) => (
                <span key={i} className="badge bg-accent/15 text-accent">
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
                <li key={i} className="text-muted">
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
