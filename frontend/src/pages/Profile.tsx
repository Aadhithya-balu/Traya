import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type {
BiometricStatus,
Consent,
ConsentStatus,
EmergencyContact,
MedicalProfile,
VisibleFeature,
} from "../api/types";
import { useAuth } from "../context/AuthContext";
import { fileToBase64 } from "../hooks/useCamera";
import { fmtDateTime } from "../utils/format";

const BLANK_MEDICAL: MedicalProfile = {
  blood_group: null,
  allergies: [],
  conditions: [],
  medications: [],
  emergency_notes: null,
  preferred_hospital: null,
};

export function Profile() {
  const { user, refreshUser } = useAuth();

  const [profile, setProfile] = useState({ full_name: "", phone: "", date_of_birth: "" });
  const [, setMedical] = useState<MedicalProfile>(BLANK_MEDICAL);
  const [medicalDraft, setMedicalDraft] = useState({ blood_group: "", allergies: "", conditions: "", medications: "", emergency_notes: "", preferred_hospital: "" });
  const [contacts, setContacts] = useState<EmergencyContact[]>([]);
  const [features, setFeatures] = useState<VisibleFeature[]>([]);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [bio, setBio] = useState<BiometricStatus | null>(null);
  const [enrollImages, setEnrollImages] = useState<string[]>([]);

  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const flash = (msg: string) => {
    setOk(msg);
    setTimeout(() => setOk(null), 3000);
  };

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
      setError(err instanceof ApiError ? err.detail : "Could not load profile.");
    }
  }, []);

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
      flash("Profile updated.");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Update failed.");
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
      flash("Medical profile saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Update failed.");
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
      flash("Emergency contact added.");
      (e.target as HTMLFormElement).reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Add failed.");
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
      flash("Feature added.");
      (e.target as HTMLFormElement).reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Add failed.");
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
      flash(`Consent ${updated.status}.`);
      if (type === "biometric_enrollment" && updated.status === "withdrawn") setBio(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Consent update failed.");
    } finally {
      setBusy(false);
    }
  };

  const onEnrollFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    const images: string[] = [];
    for (const f of files) {
      if (f.size > 3 * 1024 * 1024) {
        setError("Each image must be under 3 MB.");
        return;
      }
      images.push(await fileToBase64(f));
    }
    setEnrollImages((prev) => [...prev, ...images].slice(0, 4));
  };

  const enroll = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.enrollBiometric(enrollImages);
      setBio({ status: "enrolled", num_samples: res.num_samples, algo_version: res.algo_version });
      setEnrollImages([]);
      flash(`Enrolled with ${res.num_samples} samples.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Enrollment failed.");
    } finally {
      setBusy(false);
    }
  };

  const deleteBiometric = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteBiometric();
      setBio(null);
      setEnrollImages([]);
      flash("Biometric templates deleted.");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Delete failed.");
    } finally {
      setBusy(false);
    }
  };

  const bioConsent = consents.find((c) => c.consent_type === "biometric_enrollment");

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="text-3xl font-bold text-text">Profile</h1>
      <p className="mt-1 text-sm text-muted">
        Everything here is used to help identify you and reach your contacts in an emergency.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </div>
      )}
      {ok && (
        <div className="mt-4 rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">
          {ok}
        </div>
      )}

      <div className="mt-6 space-y-6">
        <form onSubmit={saveProfile} className="card space-y-4">
          <h2 className="font-semibold text-text">Basic information</h2>
          <div>
            <label className="label">Full name</label>
            <input className="input" value={profile.full_name} onChange={(e) => setProfile((p) => ({ ...p, full_name: e.target.value }))} required />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label">Phone</label>
              <input className="input" value={profile.phone} onChange={(e) => setProfile((p) => ({ ...p, phone: e.target.value }))} />
            </div>
            <div>
              <label className="label">Date of birth</label>
              <input type="date" className="input" value={profile.date_of_birth} onChange={(e) => setProfile((p) => ({ ...p, date_of_birth: e.target.value }))} />
            </div>
          </div>
          <button className="btn-primary" disabled={busy}>Save profile</button>
        </form>

        <form onSubmit={saveMedical} className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-text">Medical profile</h2>
            <span className="badge bg-raised text-muted">
              only critical info is shared with responders
            </span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label">Blood group</label>
              <input className="input" placeholder="e.g. O+ / A-" value={medicalDraft.blood_group} onChange={(e) => setMedicalDraft((m) => ({ ...m, blood_group: e.target.value }))} />
            </div>
            <div>
              <label className="label">Preferred hospital</label>
              <input className="input" value={medicalDraft.preferred_hospital} onChange={(e) => setMedicalDraft((m) => ({ ...m, preferred_hospital: e.target.value }))} />
            </div>
          </div>
          <div>
            <label className="label">Critical allergies (comma separated)</label>
            <input className="input" placeholder="e.g. penicillin, peanuts" value={medicalDraft.allergies} onChange={(e) => setMedicalDraft((m) => ({ ...m, allergies: e.target.value }))} />
          </div>
          <div>
            <label className="label">Critical conditions (comma separated)</label>
            <input className="input" placeholder="e.g. diabetes, epilepsy" value={medicalDraft.conditions} onChange={(e) => setMedicalDraft((m) => ({ ...m, conditions: e.target.value }))} />
          </div>
          <div>
            <label className="label">Critical medications (comma separated)</label>
            <input className="input" placeholder="e.g. insulin" value={medicalDraft.medications} onChange={(e) => setMedicalDraft((m) => ({ ...m, medications: e.target.value }))} />
          </div>
          <div>
            <label className="label">Emergency notes</label>
            <textarea className="input min-h-20" value={medicalDraft.emergency_notes} onChange={(e) => setMedicalDraft((m) => ({ ...m, emergency_notes: e.target.value }))} />
          </div>
          <button className="btn-primary" disabled={busy}>Save medical profile</button>
        </form>

        <div className="card">
          <h2 className="mb-3 font-semibold text-text">Emergency contacts</h2>
          <form onSubmit={addContact} className="grid gap-3 sm:grid-cols-4">
            <input name="name" className="input" placeholder="Name" required />
            <input name="relation" className="input" placeholder="Relation" />
            <input name="phone" className="input" placeholder="Phone" required />
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-sm text-muted">
                <input type="checkbox" name="is_primary" className="accent-accent" />
                Primary
              </label>
              <button className="btn-ghost flex-1" disabled={busy}>Add</button>
            </div>
          </form>
          <ul className="mt-4 space-y-2">
            {contacts.length === 0 && <li className="text-sm text-faint">No contacts yet.</li>}
            {contacts.map((c) => (
              <li key={c.id} className="flex items-center justify-between rounded-lg border border-line bg-surface p-3">
                <div>
                  <span className="text-sm font-medium text-text">{c.name}</span>
                  {c.is_primary && <span className="badge ml-2 bg-accent/15 text-accent">primary</span>}
                  <span className="ml-2 text-sm text-muted">{c.relation}</span>
                  <p className="text-xs text-faint">{c.phone}</p>
                </div>
                <button onClick={() => deleteContact(c.id)} className="btn-ghost !px-2.5 !py-1 text-xs text-danger">
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2 className="mb-3 font-semibold text-text">Visible identifying features</h2>
          <form onSubmit={addFeature} className="grid gap-3 sm:grid-cols-4">
            <input name="feature_type" className="input" placeholder="e.g. scar" required />
            <input name="description" className="input" placeholder="Description" required />
            <input name="body_location" className="input" placeholder="Body location" />
            <button className="btn-ghost" disabled={busy}>Add</button>
          </form>
          <ul className="mt-4 space-y-2">
            {features.length === 0 && <li className="text-sm text-faint">No features recorded.</li>}
            {features.map((f) => (
              <li key={f.id} className="flex items-center justify-between rounded-lg border border-line bg-surface p-3">
                <div className="flex items-center gap-2">
                  <span className="badge bg-accent/15 text-accent">{f.feature_type}</span>
                  <span className="text-sm text-muted">{f.description}</span>
                  {f.body_location && <span className="text-xs text-faint">({f.body_location})</span>}
                </div>
                <button onClick={() => deleteFeature(f.id)} className="btn-ghost !px-2.5 !py-1 text-xs text-danger">
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card space-y-4">
          <h2 className="font-semibold text-text">Biometric consent</h2>
          <p className="text-sm text-muted">
            Face matching is opt-in and fully revocable. Templates are encrypted at rest and never
            returned to clients.
          </p>
          <div className="flex items-center justify-between rounded-lg border border-line bg-surface p-4">
            <div>
              <p className="text-sm font-medium text-text">biometric_enrollment</p>
              <p className="text-xs text-faint">
                Current status:{" "}
                {bioConsent ? (
                  <span className={bioConsent.status === "active" ? "text-ok" : "text-warn"}>
                    {bioConsent.status}
                  </span>
                ) : (
                  "not recorded"
                )}
              </p>
            </div>
            <button
              onClick={() => toggleConsent("biometric_enrollment", bioConsent?.status)}
              className={bioConsent?.status === "active" ? "btn-ghost" : "btn-primary"}
              disabled={busy}
            >
              {bioConsent?.status === "active" ? "Withdraw consent" : "Grant consent"}
            </button>
          </div>
        </div>

        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-text">Biometric enrollment</h2>
            <span className={bio?.status === "enrolled" ? "badge bg-ok/15 text-ok" : "badge bg-raised text-muted"}>
              {bio?.status === "enrolled" ? `Enrolled · ${bio.num_samples} samples` : "Not enrolled"}
            </span>
          </div>

          {bio?.status === "enrolled" && (
            <div className="rounded-lg border border-line bg-surface p-4 text-sm">
              <p className="text-muted">
                Enrolled {fmtDateTime(bio.enrolled_at)} · algorithm {bio.algo_version ?? "current"}
              </p>
              <button onClick={deleteBiometric} className="btn-ghost mt-3 !px-3 !py-1.5 text-danger" disabled={busy}>
                Delete all templates
              </button>
            </div>
          )}

          <div>
            <label className="label">Sample photos (2–4 front-facing, well-lit)</label>
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple className="input file:mr-3 file:border-0 file:bg-raised file:px-3 file:py-1.5 file:text-accent" onChange={onEnrollFiles} />
            {enrollImages.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {enrollImages.map((img, i) => (
                  <img key={i} src={`data:image/jpeg;base64,${img}`} className="h-16 w-16 rounded-lg border border-line object-cover" alt="sample" />
                ))}
              </div>
            )}
            <button onClick={enroll} className="btn-primary mt-3" disabled={busy || enrollImages.length === 0}>
              Enroll face samples
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
