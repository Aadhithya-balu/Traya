import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type {
  BiometricStatus,
  Consent,
  ConsentStatus,
  EmergencyContact,
  MedicalProfile,
  TimelineEvent,
  VisibleFeature,
} from "../api/types";
import { useAuth } from "../context/AuthContext";
import { EnrollWizard } from "../components/EnrollWizard";
import { useI18n, type StringKey } from "../i18n";
import { fmtDateTime } from "../utils/format";

const BLANK_MEDICAL: MedicalProfile = {
  blood_group: null,
  allergies: [],
  conditions: [],
  medications: [],
  emergency_notes: null,
  preferred_hospital: null,
};

/**
 * Consent status as displayed.
 *
 * `active` and `withdrawn` are the values the backend persists; rendering them
 * raw showed an English enum inside otherwise Tamil copy. The map is total over
 * `ConsentStatus`, so a third value fails the typecheck rather than leaking.
 */
const CONSENT_STATUS_LABELS: Record<ConsentStatus, StringKey> = {
  active: "consent.status.active",
  withdrawn: "consent.status.withdrawn",
};

export function Profile() {
  const { user, refreshUser } = useAuth();
  const { t } = useI18n();

  const [profile, setProfile] = useState({ full_name: "", phone: "", date_of_birth: "" });
  const [, setMedical] = useState<MedicalProfile>(BLANK_MEDICAL);
  const [medicalDraft, setMedicalDraft] = useState({ blood_group: "", allergies: "", conditions: "", medications: "", emergency_notes: "", preferred_hospital: "" });
  const [contacts, setContacts] = useState<EmergencyContact[]>([]);
  const [features, setFeatures] = useState<VisibleFeature[]>([]);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [bio, setBio] = useState<BiometricStatus | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [activity, setActivity] = useState<TimelineEvent[] | null>(null);
  const [activityOpen, setActivityOpen] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const flash = useCallback((msg: string) => {
    setOk(msg);
    setTimeout(() => setOk(null), 3000);
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [m, c, f, cs, b] = await Promise.all([
        api.getMedical(),
        api.listContacts(),
        api.listFeatures(),
        api.listConsents(),
        api.biometricStatus(),
      ]);
      setMedical(m);
      setMedicalDraft({
        blood_group: m.blood_group ?? "",
        allergies: m.allergies.join(", "),
        conditions: m.conditions.join(", "),
        medications: m.medications.join(", "),
        emergency_notes: m.emergency_notes ?? "",
        preferred_hospital: m.preferred_hospital ?? "",
      });
      setContacts(c);
      setFeatures(f);
      setConsents(cs);
      setBio(b);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("profile.error.load"));
    }
  }, [t]);

  useEffect(() => {
    load();
    if (user) {
      setProfile({
        full_name: user.full_name,
        phone: user.phone ?? "",
        date_of_birth: user.date_of_birth?.slice(0, 10) ?? "",
      });
    }
  }, [load, user]);

  const saveProfile = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateProfile({
        full_name: profile.full_name,
        phone: profile.phone || null,
        date_of_birth: profile.date_of_birth || null,
      });
      await refreshUser();
      flash(t("profile.flash.basics"));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("profile.error.update"));
    } finally {
      setBusy(false);
    }
  };

  const saveMedical = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload: MedicalProfile = {
        blood_group: medicalDraft.blood_group || null,
        allergies: medicalDraft.allergies.split(",").map((s) => s.trim()).filter(Boolean),
        conditions: medicalDraft.conditions.split(",").map((s) => s.trim()).filter(Boolean),
        medications: medicalDraft.medications.split(",").map((s) => s.trim()).filter(Boolean),
        emergency_notes: medicalDraft.emergency_notes || null,
        preferred_hospital: medicalDraft.preferred_hospital || null,
      };
      setMedical(await api.updateMedical(payload));
      flash(t("profile.flash.medical"));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("profile.error.update"));
    } finally {
      setBusy(false);
    }
  };

  const addContact = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(e.target as HTMLFormElement);
    try {
      const contact = await api.addContact({
        name: String(form.get("name")),
        relation: String(form.get("relation") || "") || undefined,
        phone: String(form.get("phone")),
        email: String(form.get("email") || "") || undefined,
        is_primary: (form.get("is_primary") as string) === "on",
      });
      setContacts((prev) => [...prev, contact]);
      flash(t("profile.flash.contact"));
      (e.target as HTMLFormElement).reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("profile.error.add"));
    } finally {
      setBusy(false);
    }
  };

  const deleteContact = async (id: string) => {
    await api.deleteContact(id);
    setContacts((prev) => prev.filter((c) => c.id !== id));
  };

  const addFeature = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(e.target as HTMLFormElement);
    try {
      const feature = await api.addFeature({
        feature_type: String(form.get("feature_type")),
        description: String(form.get("description")),
        body_location: String(form.get("body_location") || "") || undefined,
      });
      setFeatures((prev) => [...prev, feature]);
      flash(t("profile.flash.feature"));
      (e.target as HTMLFormElement).reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("profile.error.add"));
    } finally {
      setBusy(false);
    }
  };

  const deleteFeature = async (id: string) => {
    await api.deleteFeature(id);
    setFeatures((prev) => prev.filter((f) => f.id !== id));
  };

  /**
   * Flips a consent between active and withdrawn.
   *
   * The backend persists "active" / "withdrawn" (backend/app/api/users.py:220)
   * and never "granted". Testing for "granted" here made the condition
   * permanently false, so the button always granted: consent could be given but
   * never taken back, and a withdrawal was not merely hidden, it was
   * impossible. Compare against the real stored value.
   */
  const toggleConsent = async (type: string, current: ConsentStatus | undefined) => {
    setBusy(true);
    setError(null);
    try {
      const updated =
        current === "active" ? await api.withdrawConsent(type) : await api.grantConsent(type);
      setConsents((prev) => prev.map((c) => (c.consent_type === type ? updated : c)));
      flash(
        t("profile.flash.consent", { status: t(CONSENT_STATUS_LABELS[updated.status]) }),
      );
      if (type === "biometric_enrollment" && updated.status === "withdrawn") setBio(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("profile.error.consent"));
    } finally {
      setBusy(false);
    }
  };

  const deleteBiometric = async () => {
    if (!window.confirm(t("enroll.delete.confirm"))) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteBiometric();
      setBio(null);
      setEnrolling(false);
      flash(t("profile.flash.biometric"));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("profile.error.delete"));
    } finally {
      setBusy(false);
    }
  };

  /**
   * The activity log is opt-in. It is deliberately not loaded with the page:
   * it is a "check if you want" surface, not something a person needs in front
   * of them, and it never loads until they open it.
   */
  const toggleActivity = async () => {
    if (activityOpen) {
      setActivityOpen(false);
      return;
    }
    setActivityOpen(true);
    if (activity !== null) return;
    setActivityError(null);
    try {
      setActivity(await api.accessHistory());
    } catch (err) {
      setActivityError(err instanceof ApiError ? err.detail : t("profile.activity.error"));
    }
  };

  const bioConsent = consents.find((c) => c.consent_type === "biometric_enrollment");

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="text-3xl font-bold text-text">{t("profile.page.title")}</h1>
      <p className="mt-1 text-sm text-muted">{t("profile.page.intro")}</p>

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger"
        >
          {error}
        </div>
      )}
      {/* Confirmation, not an error: `status` rather than `alert` so it is
          announced without interrupting, and does not compete for the
          assertive channel an error needs. */}
      {ok && (
        <div
          role="status"
          className="mt-4 rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok"
        >
          {ok}
        </div>
      )}

      <div className="mt-6 space-y-6">
        <form onSubmit={saveProfile} className="card space-y-4">
          <h2 className="font-semibold text-text">{t("profile.basics.heading")}</h2>
          <div>
            <label className="label" htmlFor="profile-full-name">{t("profile.field.fullName")}</label>
            <input
              id="profile-full-name"
              className="input"
              value={profile.full_name}
              onChange={(e) => setProfile((p) => ({ ...p, full_name: e.target.value }))}
              required
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="profile-phone">{t("profile.field.phone")}</label>
              <input
                id="profile-phone"
                className="input"
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                value={profile.phone}
                onChange={(e) => setProfile((p) => ({ ...p, phone: e.target.value }))}
              />
            </div>
            <div>
              <label className="label" htmlFor="profile-dob">{t("profile.field.dob")}</label>
              <input
                id="profile-dob"
                type="date"
                className="input"
                value={profile.date_of_birth}
                onChange={(e) => setProfile((p) => ({ ...p, date_of_birth: e.target.value }))}
              />
            </div>
          </div>
          <button className="btn-primary" disabled={busy}>{t("profile.basics.submit")}</button>
        </form>

        <form onSubmit={saveMedical} className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-text">{t("profile.medical.heading")}</h2>
            <span className="badge bg-raised text-muted">{t("profile.medical.sharedBadge")}</span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="profile-blood-group">{t("profile.field.bloodGroup")}</label>
              <input
                id="profile-blood-group"
                className="input"
                placeholder={t("profile.ph.bloodGroup")}
                value={medicalDraft.blood_group}
                onChange={(e) => setMedicalDraft((m) => ({ ...m, blood_group: e.target.value }))}
              />
            </div>
            <div>
              <label className="label" htmlFor="profile-preferred-hospital">{t("profile.field.preferredHospital")}</label>
              <input
                id="profile-preferred-hospital"
                className="input"
                value={medicalDraft.preferred_hospital}
                onChange={(e) => setMedicalDraft((m) => ({ ...m, preferred_hospital: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="profile-allergies">{t("profile.field.allergies")}</label>
            <input
              id="profile-allergies"
              className="input"
              placeholder={t("profile.ph.allergies")}
              value={medicalDraft.allergies}
              onChange={(e) => setMedicalDraft((m) => ({ ...m, allergies: e.target.value }))}
            />
          </div>
          <div>
            <label className="label" htmlFor="profile-conditions">{t("profile.field.conditions")}</label>
            <input
              id="profile-conditions"
              className="input"
              placeholder={t("profile.ph.conditions")}
              value={medicalDraft.conditions}
              onChange={(e) => setMedicalDraft((m) => ({ ...m, conditions: e.target.value }))}
            />
          </div>
          <div>
            <label className="label" htmlFor="profile-medications">{t("profile.field.medications")}</label>
            <input
              id="profile-medications"
              className="input"
              placeholder={t("profile.ph.medications")}
              value={medicalDraft.medications}
              onChange={(e) => setMedicalDraft((m) => ({ ...m, medications: e.target.value }))}
            />
          </div>
          <div>
            <label className="label" htmlFor="profile-emergency-notes">{t("profile.field.emergencyNotes")}</label>
            <textarea
              id="profile-emergency-notes"
              className="input min-h-20"
              value={medicalDraft.emergency_notes}
              onChange={(e) => setMedicalDraft((m) => ({ ...m, emergency_notes: e.target.value }))}
            />
          </div>
          <button className="btn-primary" disabled={busy}>{t("profile.medical.submit")}</button>
        </form>

        <div className="card">
          <h2 className="mb-3 font-semibold text-text">{t("profile.contacts.heading")}</h2>
          <form onSubmit={addContact} className="grid gap-3 sm:grid-cols-4">
            {/*
              Placeholder-only inputs are unusable with a screen reader: the
              accessible name comes from the placeholder, which several readers
              do not announce. Each gets a visually hidden label so the field is
              named either way, and the visible placeholder stays a hint.
            */}
            <div>
              <label className="sr-only" htmlFor="contact-name">{t("profile.field.name")}</label>
              <input id="contact-name" name="name" className="input" placeholder={t("profile.field.name")} required />
            </div>
            <div>
              <label className="sr-only" htmlFor="contact-relation">{t("profile.field.relation")}</label>
              <input id="contact-relation" name="relation" className="input" placeholder={t("profile.field.relation")} />
            </div>
            <div>
              <label className="sr-only" htmlFor="contact-phone">{t("profile.field.phone")}</label>
              <input id="contact-phone" name="phone" className="input" type="tel" placeholder={t("profile.field.phone")} required />
            </div>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-sm text-muted" htmlFor="contact-primary">
                <input id="contact-primary" type="checkbox" name="is_primary" className="accent-accent" />
                {t("profile.contact.primary")}
              </label>
              <button className="btn-ghost flex-1" disabled={busy}>{t("profile.contact.add")}</button>
            </div>
          </form>
          <ul className="mt-4 space-y-2">
            {contacts.length === 0 && (
              <li className="text-sm text-faint">{t("profile.contact.empty")}</li>
            )}
            {contacts.map((c) => (
              <li key={c.id} className="flex items-center justify-between rounded-lg border border-line bg-surface p-3">
                <div>
                  <span className="text-sm font-medium text-text">{c.name}</span>
                  {c.is_primary && (
                    <span className="badge ml-2 bg-accent/15 text-accent">
                      {t("profile.contact.primaryBadge")}
                    </span>
                  )}
                  <span className="ml-2 text-sm text-muted">{c.relation}</span>
                  <p className="text-xs text-faint">{c.phone}</p>
                </div>
                <button
                  onClick={() => deleteContact(c.id)}
                  className="btn-ghost !px-2.5 !py-1 text-xs text-danger"
                  aria-label={t("profile.contact.removeNamed", { name: c.name })}
                >
                  {t("profile.contact.remove")}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2 className="mb-3 font-semibold text-text">{t("profile.features.heading")}</h2>
          <form onSubmit={addFeature} className="grid gap-3 sm:grid-cols-4">
            <div>
              <label className="sr-only" htmlFor="feature-type">{t("profile.field.featureType")}</label>
              <input
                id="feature-type"
                name="feature_type"
                className="input"
                placeholder={t("profile.ph.featureType")}
                required
              />
            </div>
            <div>
              <label className="sr-only" htmlFor="feature-description">{t("profile.field.description")}</label>
              <input id="feature-description" name="description" className="input" placeholder={t("profile.field.description")} required />
            </div>
            <div>
              <label className="sr-only" htmlFor="feature-location">{t("profile.field.bodyLocation")}</label>
              <input id="feature-location" name="body_location" className="input" placeholder={t("profile.field.bodyLocation")} />
            </div>
            <button className="btn-ghost" disabled={busy}>{t("profile.feature.add")}</button>
          </form>
          <ul className="mt-4 space-y-2">
            {features.length === 0 && (
              <li className="text-sm text-faint">{t("profile.feature.empty")}</li>
            )}
            {features.map((f) => (
              <li key={f.id} className="flex items-center justify-between rounded-lg border border-line bg-surface p-3">
                <div className="flex items-center gap-2">
                  {/* `feature_type` is free text a person typed, not a closed
                      set, so it renders as data. */}
                  <span className="badge bg-accent/15 text-accent">{f.feature_type}</span>
                  <span className="text-sm text-muted">{f.description}</span>
                  {f.body_location && <span className="text-xs text-faint">({f.body_location})</span>}
                </div>
                <button
                  onClick={() => deleteFeature(f.id)}
                  className="btn-ghost !px-2.5 !py-1 text-xs text-danger"
                  aria-label={t("profile.feature.removeNamed", { name: f.description })}
                >
                  {t("profile.feature.remove")}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card space-y-4">
          <h2 className="font-semibold text-text">{t("profile.consent.heading")}</h2>
          <p className="text-sm text-muted">{t("profile.consent.body")}</p>
          <div className="flex items-center justify-between rounded-lg border border-line bg-surface p-4">
            <div>
              {/* The consent type is a backend enum and stays as-is. */}
              <p className="font-mono text-sm text-text">biometric_enrollment</p>
              <p className="text-xs text-faint">
                {t("profile.consent.currentStatus")}{" "}
                {bioConsent ? (
                  <span className={bioConsent.status === "active" ? "text-ok" : "text-warn"}>
                    {t(CONSENT_STATUS_LABELS[bioConsent.status])}
                  </span>
                ) : (
                  t("profile.consent.notRecorded")
                )}
              </p>
            </div>
            <button
              onClick={() => toggleConsent("biometric_enrollment", bioConsent?.status)}
              className={bioConsent?.status === "active" ? "btn-ghost" : "btn-primary"}
              disabled={busy}
            >
              {bioConsent?.status === "active" ? t("profile.consent.withdraw") : t("profile.consent.grant")}
            </button>
          </div>
        </div>

        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-text">{t("profile.biometric.heading")}</h2>
            <span className={bio?.status === "enrolled" ? "badge bg-ok/15 text-ok" : "badge bg-raised text-muted"}>
              {bio?.status === "enrolled"
                ? t("profile.biometric.enrolledWith", { count: bio.num_samples })
                : t("profile.biometric.notEnrolled")}
            </span>
          </div>

          {bio?.status === "enrolled" && (
            <div className="rounded-lg border border-line bg-surface p-4 text-sm">
              <p className="text-muted">
                {t("profile.biometric.detail", {
                  date: fmtDateTime(bio.enrolled_at),
                  version: bio.algo_version ?? t("profile.biometric.currentVersion"),
                })}
              </p>
              <button onClick={deleteBiometric} className="btn-ghost mt-3 !px-3 !py-1.5 text-danger" disabled={busy}>
                {t("profile.biometric.deleteAll")}
              </button>
            </div>
          )}

          {enrolling ? (
            <EnrollWizard
              onEnrolled={(res) => {
                setBio({
                  status: "enrolled",
                  num_samples: res.num_samples,
                  algo_version: res.algo_version ?? null,
                  enrolled_at: res.enrolled_at ?? null,
                });
                setEnrolling(false);
                flash(t("enroll.done.title"));
              }}
              onCancel={() => setEnrolling(false)}
            />
          ) : bioConsent?.status === "active" ? (
            <button
              type="button"
              onClick={() => setEnrolling(true)}
              className="btn-primary"
              disabled={busy}
            >
              {t("enroll.start")}
            </button>
          ) : (
            <p className="text-sm text-muted">{t("enroll.consent.required")}</p>
          )}
        </div>

        <div className="card space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold text-text">{t("profile.activity.heading")}</h2>
            <button
              type="button"
              onClick={toggleActivity}
              className="btn-ghost !px-3 !py-1.5 text-sm"
              aria-expanded={activityOpen}
            >
              {activityOpen ? t("profile.activity.hide") : t("profile.activity.show")}
            </button>
          </div>
          <p className="text-sm text-muted">{t("profile.activity.intro")}</p>

          {activityOpen && (
            <div>
              {activityError && <p className="text-sm text-danger">{activityError}</p>}
              {activity === null && !activityError && (
                <p className="text-sm text-faint">{t("common.loading")}</p>
              )}
              {activity && activity.length === 0 && (
                <p className="text-sm text-faint">{t("profile.activity.empty")}</p>
              )}
              <ul className="space-y-2">
                {activity?.map((ev, i) => (
                  <li
                    key={i}
                    className="flex items-center justify-between gap-2 rounded-lg border border-line bg-surface p-3"
                  >
                    <span className="font-mono text-xs text-text">{ev.action}</span>
                    <span className="whitespace-nowrap text-xs text-faint">{fmtDateTime(ev.at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}