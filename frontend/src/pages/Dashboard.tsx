import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type {
  BiometricStatus,
  Consent,
  EmergencyContact,
  TimelineEvent,
} from "../api/types";
import { useI18n } from "../i18n";
import { CheckIcon, ChevronRightIcon } from "../components/icons";

export function Dashboard() {
  const { t } = useI18n();
  const [biometric, setBiometric] = useState<BiometricStatus | null>(null);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [contacts, setContacts] = useState<EmergencyContact[]>([]);
  const [history, setHistory] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // One round trip per concern, in parallel: the dashboard is a summary and
    // should not serialise four independent requests on a phone.
    Promise.all([
      api.biometricStatus(),
      api.listConsents(),
      api.listContacts(),
      api.accessHistory(),
    ])
      .then(([bio, con, con2, hist]) => {
        if (cancelled) return;
        setBiometric(bio);
        setConsents(con);
        setContacts(con2);
        setHistory(hist);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof ApiError ? err.detail : t("error.generic"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const enrolled = biometric?.status === "enrolled";

  return (
    <div className="py-5">
      <h1 className="text-2xl font-semibold tracking-tight">
        {t("dashboard.title")}
      </h1>

      {error && (
        <p className="mt-3 rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mt-5 grid grid-cols-2 gap-3">
        <Stat
          label={t("profile.biometric.status")}
          value={
            enrolled
              ? t("profile.biometric.enrolled")
              : t("profile.biometric.not_enrolled")
          }
          tone={enrolled ? "ok" : "warn"}
        />
        <Stat
          label={t("profile.contacts")}
          value={String(contacts.length)}
          tone={contacts.length ? "neutral" : "warn"}
        />
        <Stat
          label={t("profile.biometric.samples")}
          value={String(biometric?.num_samples ?? 0)}
          tone="neutral"
        />
        <Stat
          label={t("profile.consent")}
          value={`${consents.filter((c) => c.status === "active").length}/${consents.length}`}
          tone="neutral"
        />
      </div>

      {!enrolled && (
        <Link
          to="/profile"
          className="card mt-4 flex items-center justify-between gap-3 border-accent"
        >
          <div>
            <p className="text-sm font-semibold">{t("enroll.title")}</p>
            <p className="mt-0.5 text-xs text-muted">{t("enroll.intro")}</p>
          </div>
          <ChevronRightIcon size={18} className="shrink-0 text-faint" />
        </Link>
      )}

      <section className="mt-6">
        <h2 className="eyebrow">{t("profile.consent")}</h2>
        <ul className="mt-2 space-y-2">
          {consents.length === 0 && (
            <li className="card-raised text-sm text-muted">
              {t("common.none")}
            </li>
          )}
          {consents.map((consent) => (
            <li
              key={`${consent.consent_type}-${consent.version}`}
              className="card flex items-center justify-between"
            >
              <span className="text-sm">{consent.consent_type}</span>
              <span
                className={[
                  "badge",
                  consent.status === "active"
                    ? "bg-ok/15 text-ok"
                    : "bg-raised text-muted",
                ].join(" ")}
              >
                {consent.status}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-6">
        <h2 className="eyebrow">{t("dashboard.access")}</h2>
        <ul className="mt-2 space-y-2">
          {history.length === 0 && (
            <li className="card-raised text-sm text-muted">
              {t("dashboard.access.none")}
            </li>
          )}
          {history.slice(0, 6).map((event, index) => (
            <li key={`${event.at}-${index}`} className="card">
              <div className="flex items-start gap-2">
                <CheckIcon size={16} className="mt-0.5 shrink-0 text-faint" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{event.action}</p>
                  <p className="mt-0.5 text-xs text-faint">
                    {new Date(event.at).toLocaleString()}
                  </p>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "warn" | "neutral";
}) {
  const valueClass =
    tone === "ok"
      ? "text-ok"
      : tone === "warn"
        ? "text-warn"
        : "text-text";
  return (
    <div className="card">
      <p className="text-xs leading-tight text-muted">{label}</p>
      <p className={`mt-1.5 text-sm font-semibold ${valueClass}`}>{value}</p>
    </div>
  );
}
