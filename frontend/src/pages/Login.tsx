import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n";
import { AlertIcon } from "../components/icons";

const DEMO_ACCOUNTS = [
  { email: "aarav.kumar@demo.traya", label: "Registered person" },
  { email: "neha.rao@responder.traya", label: "Medical responder" },
  { email: "admin@traya.io", label: "Administrator" },
];
const DEMO_PASSWORD = "TrayaDemo#2026";

export function Login() {
  const { t } = useI18n();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="py-6">
      <h1 className="text-2xl font-semibold tracking-tight">
        {t("auth.login.title")}
      </h1>
      <p className="mt-1 text-sm text-muted">{t("auth.login.subtitle")}</p>

      {error && (
        <div
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger"
        >
          <AlertIcon size={18} className="mt-px shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <div>
          <label className="label" htmlFor="email">
            {t("auth.email")}
          </label>
          <input
            id="email"
            className="input"
            type="email"
            inputMode="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="password">
            {t("auth.password")}
          </label>
          <input
            id="password"
            className="input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button type="submit" disabled={busy} className="btn btn-primary btn-lg btn-block">
          {busy ? t("common.loading") : t("auth.login.submit")}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-muted">
        {t("auth.noAccount")}{" "}
        <Link
          to="/register"
          className="font-medium text-text underline underline-offset-4"
        >
          {t("auth.register.title")}
        </Link>
      </p>

      <div className="card-raised mt-8">
        <h2 className="text-sm font-semibold">{t("auth.demo.title")}</h2>
        <p className="mt-1 text-xs text-muted">
          {t("auth.demo.body", { password: DEMO_PASSWORD })}
        </p>
        <div className="mt-3 space-y-1">
          {DEMO_ACCOUNTS.map((account) => (
            <button
              key={account.email}
              type="button"
              onClick={() => {
                setEmail(account.email);
                setPassword(DEMO_PASSWORD);
              }}
              className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2.5 text-left hover:bg-surface"
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium">
                  {account.label}
                </span>
                <span className="block truncate text-xs text-faint">
                  {account.email}
                </span>
              </span>
              <span className="shrink-0 text-xs text-muted">Fill</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
