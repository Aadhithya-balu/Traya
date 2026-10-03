import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  ApiError,
  checkConnection,
  clearApiBase,
  getApiBase,
  getDefaultApiBase,
  setApiBase,
} from "../api/client";
import type { HealthReport } from "../api/types";
import { AlertIcon, CheckIcon } from "../components/icons";
import { useI18n } from "../i18n";

/** `192.168.1.10:8000` is what a person types; the scheme is what fetch needs. */
function withScheme(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
}

/**
 * Point the app at a backend it can reach.
 *
 * A packaged app cannot run the Python service, so it must be told where a
 * running one lives. The base is stored on the device, never compiled in, so a
 * shipped build is not tied to one machine and holds no server credential - only
 * a URL. The address is saved only after `/api/health` answers, so a typo cannot
 * leave the app pointed at a dead host.
 */
export function Connect() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [url, setUrl] = useState(getApiBase() || getDefaultApiBase());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<HealthReport | null>(null);
  const defaultBase = getDefaultApiBase();

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setReport(null);
    const candidate = withScheme(url);
    try {
      const health = await checkConnection(candidate);
      setApiBase(candidate);
      setReport(health);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="py-6">
      <h1 className="text-2xl font-semibold tracking-tight">
        {t("connect.title")}
      </h1>
      <p className="mt-1 text-sm text-muted">{t("connect.intro")}</p>

      {error && (
        <div
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger"
        >
          <AlertIcon size={18} className="mt-px shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {report && (
        <div className="mt-4 rounded-md border border-ok/40 bg-ok/10 p-3 text-sm">
          <p className="flex items-center gap-2 font-medium text-ok">
            <CheckIcon size={18} />
            {t("connect.ok")}
          </p>
          <p className="mt-2 text-muted">
            {t("connect.result.database", {
              backend: report.database.backend,
              tables: report.database.tables,
            })}
          </p>
          <p className="mt-1 text-muted">
            {t("connect.result.engine", { model: report.recognition.model })}
          </p>
        </div>
      )}

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <div>
          <label className="label" htmlFor="api-base">
            {t("connect.label")}
          </label>
          <input
            id="api-base"
            className="input"
            type="text"
            inputMode="url"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            placeholder={t("connect.placeholder", {
              url: "http://192.168.1.10:8000",
            })}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <p className="mt-1 text-xs text-faint">{t("connect.hint")}</p>
        </div>
        <button
          type="submit"
          disabled={busy}
          className="btn btn-primary btn-lg btn-block"
        >
          {busy ? t("common.loading") : t("connect.test")}
        </button>
      </form>

      {report && (
        <button
          type="button"
          onClick={() => navigate("/", { replace: true })}
          className="btn btn-ghost btn-lg btn-block mt-3"
        >
          {t("connect.continue")}
        </button>
      )}

      {defaultBase !== "" && (
        <button
          type="button"
          onClick={() => {
            clearApiBase();
            setUrl(defaultBase);
            setReport(null);
            setError(null);
          }}
          className="mt-6 block w-full text-center text-sm text-muted underline underline-offset-4"
        >
          {t("connect.reset")}
        </button>
      )}

      <p className="mt-6 text-center text-sm text-muted">
        <Link to="/" className="underline underline-offset-4">
          {t("nav.home")}
        </Link>
      </p>
    </div>
  );
}
