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
import { useI18n, type StringKey } from "../i18n";
import { NextAction, StatusBadge, ScoreBar } from "../components/StatusBadge";
import { LiveStatus } from "../components/LiveStatus";
import { QualityPanel } from "../components/QualityPanel";
import { Tabs, TabPanel } from "../components/Tabs";
import { AlertIcon } from "../components/icons";
import { fmtKm, fmtTime } from "../utils/format";

type Tab = "result" | "medical" | "contact" | "location" | "timeline";

const TABS: ReadonlyArray<{ id: Tab; label: StringKey }> = [
  { id: "result", label: "result.tabs.summary" },
  { id: "medical", label: "result.tabs.medical" },
  { id: "contact", label: "result.tabs.contact" },
  { id: "location", label: "result.tabs.location" },
  { id: "timeline", label: "result.tabs.timeline" },
];

export function EmergencyHub() {
  const { sessionId: routeId } = useParams();
  const navigate = useNavigate();
  const { sessionId, result, previewImage, setResult } = useEmergency();
  const { hasRole } = useAuth();
  const { t } = useI18n();

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
  const [announcement, setAnnouncement] = useState("");

  const id = sid as string;

  /** Never leak a driver error, and never blame the person's session. */
  const describe = (err: unknown, fallback: StringKey) => {
    if (err instanceof ApiError) {
      if (err.isNetwork) return t("hub.error.network");
      if (err.status === 403) return t("hub.error.ended");
      if (err.status === 404) return t("hub.error.gone");
      // The server's own detail is shown verbatim because it is authored for
      // this audience; the fallback covers a detail that is absent or blank.
      return err.detail || t(fallback);
    }
    return t(fallback);
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
      setError(describe(err, "hub.error.medical"));
    }
  }, [id, hasRole, t]);

  const loadTimeline = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      setTimeline(await api.timeline(id));
    } catch (err) {
      setError(describe(err, "hub.error.timeline"));
    }
  }, [id, t]);

  const loadHospitals = useCallback(async (lat: number, lng: number) => {
    setError(null);
    try {
      setHospitals(await api.nearbyHospitals(lat, lng, 30));
    } catch (err) {
      setError(describe(err, "hub.error.hospitals"));
    }
  }, [t]);

  const onTab = (next: Tab) => {
    setTab(next);
    const label = TABS.find((entry) => entry.id === next)?.label;
    if (label) setAnnouncement(t("hub.live.tab", { label: t(label) }));
    if (next === "medical") loadMedical();
    if (next === "timeline") loadTimeline();
    if (next === "location") {
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
      setAnnouncement(t("hub.live.sentLocation"));
    } catch (err) {
      setError(describe(err, "hub.error.location"));
    } finally {
      setBusy(false);
    }
  };

  const contactAction = async (action: "call" | "sms" | "share_location") => {
    setBusy(true);
    setError(null);
    try {
      setContact(await api.contactAction(id, action));
      setAnnouncement(t("hub.live.contactLogged"));
    } catch (err) {
      setError(describe(err, "hub.error.contact"));
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
      setAnnouncement(t("hub.live.confirmed"));
    } catch (err) {
      setError(describe(err, "hub.error.confirm"));
    } finally {
      setBusy(false);
    }
  };

  if (!id) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 text-center">
        <p className="text-muted">{t("hub.none.title")}</p>
        <button onClick={() => navigate("/emergency")} className="btn-primary mt-4">
          {t("hub.none.begin")}
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-text">{t("hub.title")}</h1>
          <p className="text-sm text-muted">
            {t("hub.sessionCode", { code: result ? id.slice(0, 8) : id })}
          </p>
        </div>
        {result && <StatusBadge status={result.status} />}
      </div>

      <LiveStatus message={announcement} className="sr-only" />

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger"
        >
          {error}
        </div>
      )}

      <div className="mt-6">
        <Tabs
          tabs={TABS}
          value={tab}
          onChange={onTab}
          label="hub.tabs.label"
          idPrefix="hub"
        />

        <TabPanel tabId="result" idPrefix="hub" active={tab === "result"} className="mt-6">
          {result ? (
            <MatchResultSection
              result={result}
              preview={previewImage}
              onConfirm={confirmCandidate}
              canConfirm={hasRole("medical_responder", "police_responder", "admin")}
              busy={busy}
            />
          ) : null}
        </TabPanel>

        <TabPanel tabId="medical" idPrefix="hub" active={tab === "medical"} className="mt-6">
          <div className="space-y-6">
            {medical && <PublicMedicalSummary summary={medical} />}
            {responder && <ResponderExtras profile={responder} />}
            {!medical && (
              <div className="card text-center text-sm text-muted">
                {t("hub.medical.pending")}
              </div>
            )}
          </div>
        </TabPanel>

        <TabPanel tabId="contact" idPrefix="hub" active={tab === "contact"} className="mt-6">
          <div className="card space-y-4">
            <h2 className="font-semibold text-text">{t("hub.contact.title")}</h2>
            <div className="flex flex-wrap gap-3">
              <button onClick={() => contactAction("call")} className="btn-primary" disabled={busy}>
                {t("hub.contact.call")}
              </button>
              <button onClick={() => contactAction("sms")} className="btn-ghost" disabled={busy}>
                {t("hub.contact.sms")}
              </button>
              <button onClick={() => contactAction("share_location")} className="btn-ghost" disabled={busy}>
                {t("hub.contact.share")}
              </button>
            </div>
            {contact && (
              <div className="rounded-lg border border-accent/30 bg-accent/10 p-4 text-sm">
                <p className="font-medium text-text">
                  {contact.contact_name ?? t("hub.contact.unknown")} · {contact.contact_phone ?? "—"}
                </p>
                <p className="mt-1 text-accent">
                  {t("hub.contact.logged", {
                    action: contact.action,
                    time: fmtTime(contact.logged_at),
                  })}
                </p>
              </div>
            )}
          </div>
        </TabPanel>

        <TabPanel tabId="location" idPrefix="hub" active={tab === "location"} className="mt-6">
          <div className="card space-y-4">
            <h2 className="font-semibold text-text">{t("hub.location.title")}</h2>
            <div className="flex flex-wrap gap-3">
              <button onClick={useGeolocationNow} className="btn-primary" disabled={busy}>
                {t("hub.location.useGps")}
              </button>
              <button
                onClick={() => useManualCoords(28.6139, 77.209)}
                className="btn-ghost"
                disabled={busy}
              >
                {t("hub.location.demo")}
              </button>
            </div>
            {geo.error && <p className="text-xs text-danger">{geo.error}</p>}

            <div className="grid gap-4 sm:grid-cols-2">
              {/*
                Each input is labelled by its own <label htmlFor> rather than by
                wrapping alone. Wrapping does associate the label, but the id is
                what lets `aria-describedby` point the lat/long pair at shared
                help text later, and it is the form a screen reader can navigate
                by landmark rather than by position.
              */}
              <div className="rounded-lg border border-line bg-surface p-4">
                <label className="label" htmlFor="hub-latitude">
                  {t("hub.location.lat")}
                </label>
                <input
                  id="hub-latitude"
                  className="input"
                  type="number"
                  step="0.0001"
                  inputMode="decimal"
                  value={locCoords?.latitude ?? ""}
                  onChange={(e) =>
                    setLocCoords((c) => ({ ...(c ?? { longitude: 0 }), latitude: Number(e.target.value) }))
                  }
                />
                <label className="label mt-3" htmlFor="hub-longitude">
                  {t("hub.location.lng")}
                </label>
                <input
                  id="hub-longitude"
                  className="input"
                  type="number"
                  step="0.0001"
                  inputMode="decimal"
                  value={locCoords?.longitude ?? ""}
                  onChange={(e) =>
                    setLocCoords((c) => ({ ...(c ?? { latitude: 0 }), longitude: Number(e.target.value) }))
                  }
                />
                <button
                  onClick={() => locCoords && loadHospitals(locCoords.latitude, locCoords.longitude)}
                  className="btn-ghost mt-3 w-full"
                >
                  {t("hub.location.find")}
                </button>
              </div>

              <div className="rounded-lg border border-line bg-surface p-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted">{t("hub.location.current")}</span>
                  {locCoords && <span className="badge bg-ok/15 text-ok">{t("hub.location.set")}</span>}
                </div>
                {locCoords ? (
                  <p className="mt-1 font-mono text-sm text-muted">
                    {locCoords.latitude.toFixed(4)}, {locCoords.longitude.toFixed(4)}
                  </p>
                ) : (
                  <p className="mt-1 text-sm text-faint">{t("hub.location.unset")}</p>
                )}
                <button
                  onClick={sendLocation}
                  className="btn-primary mt-3 w-full"
                  disabled={busy || !locCoords}
                >
                  {sentLocation ? t("hub.location.sent") : t("hub.location.send")}
                </button>
              </div>
            </div>

            <div>
              <h3 className="mb-3 font-semibold text-text">{t("hub.location.nearby")}</h3>
              {hospitals === null && (
                <p className="text-sm text-faint">{t("hub.location.needCoords")}</p>
              )}
              {hospitals && hospitals.length === 0 && (
                <p className="text-sm text-faint">{t("hub.location.noneFound")}</p>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                {hospitals?.map((h) => (
                  <div key={h.id} className="rounded-lg border border-line bg-surface p-4">
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="font-medium text-text">{h.name}</h4>
                      <span className="whitespace-nowrap font-mono text-xs text-accent">
                        {fmtKm(h.distance_km)}
                      </span>
                    </div>
                    {h.address && <p className="mt-1 text-xs text-muted">{h.address}</p>}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <span className={`badge ${h.emergency_available ? "bg-ok/15 text-ok" : "bg-raised text-muted"}`}>
                        {h.emergency_available ? t("hub.location.emergency") : t("hub.location.nonEmergency")}
                      </span>
                      <span className={`badge ${h.availability_verified ? "bg-accent/15 text-accent" : "bg-warn/15 text-warn"}`}>
                        {h.availability_verified ? t("hub.location.verified") : t("hub.location.unverified")}
                      </span>
                    </div>
                    {h.phone && <p className="mt-2 text-xs text-muted">{h.phone}</p>}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </TabPanel>

        <TabPanel tabId="timeline" idPrefix="hub" active={tab === "timeline"} className="mt-6">
          <div className="card">
            <h2 className="mb-4 font-semibold text-text">{t("hub.timeline.title")}</h2>
            {timeline === null && <p className="text-sm text-faint">{t("hub.timeline.loading")}</p>}
            {timeline && timeline.length === 0 && (
              <p className="text-sm text-faint">{t("hub.timeline.empty")}</p>
            )}
            <ol className="relative space-y-4 border-l border-line pl-5">
              {timeline?.map((ev, i) => (
                <li key={i} className="relative">
                  <span aria-hidden className="absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full bg-accent" />
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
        </TabPanel>
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
  const { t } = useI18n();

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <div className="lg:col-span-2">
        {preview ? (
          <img
            src={preview}
            alt={t("hub.result.preview.alt")}
            className="aspect-[3/4] w-full rounded-xl border border-line object-cover"
          />
        ) : (
          <div className="flex aspect-[3/4] w-full items-center justify-center rounded-xl border border-line bg-raised text-faint">
            {t("hub.result.preview.none")}
          </div>
        )}
      </div>

      <div className="space-y-5 lg:col-span-3">
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-text">{t("hub.result.title")}</h2>
            <StatusBadge status={result.status} />
          </div>

          {/*
            The instruction comes before the score, not after it. A responder
            reading top to bottom should meet "what do I do" before "how
            confident", because the number is the one thing on this screen they
            are most likely to over-trust.
          */}
          <div className="rounded-lg border border-line bg-raised p-3">
            <NextAction status={result.status} />
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
              <span className="badge bg-warn/15 text-warn">{t("hub.result.fallback")}</span>
            )}
          </div>

          {result.requires_human_confirmation && (
            <div
              role="alert"
              className="rounded-lg border border-warn/30 bg-warn/10 p-3 text-sm text-warn"
            >
              {t("hub.result.reviewWarning")}
            </div>
          )}

          {canConfirm && result.candidates.length > 0 && (
            <button
              onClick={() => onConfirm(result.candidates[0].user_id)}
              className="btn-primary w-full"
              disabled={busy || result.status === "CONFIRMED"}
            >
              {result.status === "CONFIRMED" ? t("hub.result.confirmed") : t("hub.result.confirm")}
            </button>
          )}
        </div>

        {result.candidates.length > 0 && (
          <div className="card">
            <h3 className="mb-3 font-semibold text-text">{t("hub.result.candidates")}</h3>
            <ul className="space-y-2">
              {result.candidates.map((c) => (
                <li
                  key={c.user_id}
                  className="flex items-center justify-between rounded-lg border border-line bg-surface p-3"
                >
                  <div>
                    <span className="text-sm font-medium text-text">#{c.rank}</span>
                    <span className="ml-2 text-sm text-muted">{c.user_id.slice(0, 12)}…</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-accent">
                      {Math.round(c.confidence * 100)}%
                    </span>
                    <span
                      className={`badge ${c.status === "accepted" ? "bg-ok/15 text-ok" : "bg-raised text-muted"}`}
                    >
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
 * `BIOMETRIC_ENGINE` selects a real recogniser or the simulation, and the API
 * reports `engine_mode` and `demo_mode` on every result. When the simulation is
 * running it does not detect faces at all - it reads twelve brightness
 * measurements and calls them an identity - so a responder seeing a bare
 * percentage had no way to know the number meant nothing.
 *
 * This must stay above the score, must not be dismissible, and must say plainly
 * that the confidence does not reflect identity. The honest reading of the
 * simulation is in docs/AUDIT.md and ADR 0001.
 */
function EngineDisclosure({ result }: { result: IdentifyResult }) {
  const { t } = useI18n();
  const simulated =
    result.engine_mode === "simulation" || result.engine_mode === "demo";

  if (!simulated) {
    return (
      <p className="text-xs text-faint">
        {result.algo_version
          ? t("hub.engine.version", { mode: result.engine_mode, version: result.algo_version })
          : t("hub.engine.label", { mode: result.engine_mode })}
      </p>
    );
  }

  return (
    <div className="rounded-lg border border-warn/40 bg-warn/10 p-3" role="note">
      <p className="flex items-center gap-2 text-sm font-medium text-warn">
        <AlertIcon size={16} className="shrink-0" />
        {t("hub.engine.simulationTitle")}
      </p>
      <p className="mt-1.5 text-xs leading-relaxed text-muted">
        {t("hub.engine.simulationBody", {
          mode: result.engine_mode,
          demo: result.demo_mode ? t("hub.engine.demo") : "",
          version: result.algo_version ? ` · ${result.algo_version}` : "",
        })}
      </p>
    </div>
  );
}

function PublicMedicalSummary({ summary }: { summary: PublicSummary }) {
  const { t } = useI18n();
  const dash = t("hub.medical.none");

  return (
    <div className="card">
      <h2 className="mb-1 font-semibold text-text">{t("hub.result.title")}</h2>
      <p className="text-sm text-faint">{t("hub.medical.for", { name: summary.full_name })}</p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-line bg-surface p-4">
          <p className="label">{t("hub.medical.age")}</p>
          <p className="text-lg text-text">{summary.age ?? dash}</p>
        </div>
        <div className="rounded-lg border border-line bg-surface p-4">
          <p className="label">{t("hub.medical.blood")}</p>
          <p className="text-lg font-mono text-text">{summary.blood_group ?? dash}</p>
        </div>
      </div>

      {summary.emergency_warnings.length > 0 && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-4"
        >
          <p className="mb-2 text-sm font-semibold text-danger">
            {t("hub.medical.warnings")}
          </p>
          <ul className="list-inside list-disc space-y-1 text-sm text-danger">
            {summary.emergency_warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <div>
          <p className="label">{t("hub.medical.allergies")}</p>
          <div className="flex flex-wrap gap-1.5">
            {summary.critical_allergies.length === 0 && (
              <span className="text-sm text-faint">{t("hub.medical.noneRecorded")}</span>
            )}
            {summary.critical_allergies.map((a) => (
              <span key={a} className="badge bg-danger/15 text-danger">{a}</span>
            ))}
          </div>
        </div>
        <div>
          <p className="label">{t("hub.medical.conditions")}</p>
          <div className="flex flex-wrap gap-1.5">
            {summary.critical_conditions.length === 0 && (
              <span className="text-sm text-faint">{t("hub.medical.noneRecorded")}</span>
            )}
            {summary.critical_conditions.map((c) => (
              <span key={c} className="badge bg-warn/15 text-warn">{c}</span>
            ))}
          </div>
        </div>
        <div>
          <p className="label">{t("hub.medical.medications")}</p>
          <div className="flex flex-wrap gap-1.5">
            {summary.critical_medications.length === 0 && (
              <span className="text-sm text-faint">{t("hub.medical.noneRecorded")}</span>
            )}
            {summary.critical_medications.map((m) => (
              <span key={m} className="badge bg-raised text-muted">{m}</span>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-line bg-surface p-4 text-sm">
        <p className="label">{t("hub.medical.contact")}</p>
        <p className="text-text">{summary.emergency_contact.name ?? dash}</p>
        <p className="text-muted">
          {summary.emergency_contact.relationship
            ? `${summary.emergency_contact.relationship} · `
            : ""}
          {summary.emergency_contact.phone ?? t("hub.medical.noPhone")}
        </p>
      </div>
    </div>
  );
}

function ResponderExtras({ profile }: { profile: ResponderProfile }) {
  const { t } = useI18n();

  return (
    <div className="card">
      <h2 className="mb-3 font-semibold text-text">{t("hub.responder.title")}</h2>
      <div className="space-y-4 text-sm">
        {Object.entries(profile.additional).map(([k, v]) => (
          <div key={k} className="rounded-lg border border-line bg-surface p-3">
            <p className="label">{k.replace(/_/g, " ")}</p>
            <p className="text-text">{String(v)}</p>
          </div>
        ))}
        {profile.visible_features.length > 0 && (
          <div>
            <p className="label mb-2">{t("hub.responder.features")}</p>
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
            <p className="label mb-2">{t("hub.responder.contacts")}</p>
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