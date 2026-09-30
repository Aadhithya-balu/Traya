import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n";
import { AlertIcon, CheckIcon } from "../components/icons";

/** Mirrors the backend rule so the person finds out before the round trip. */
function passwordProblem(password: string): string | null {
  if (password.length < 8) return "8+";
  if (!/[A-Z]/.test(password)) return "A-Z";
  if (!/\d/.test(password)) return "0-9";
  return null;
}

export function Register() {
  const { t } = useI18n();
  const { register } = useAuth();
  const navigate = useNavigate();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const problem = useMemo(() => passwordProblem(password), [password]);
  const passwordOk = password.length > 0 && problem === null;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (problem) return;
    setBusy(true);
    setError(null);
    try {
      await register({
        full_name: fullName,
        email,
        password,
        phone: phone || undefined,
      });
      navigate("/profile", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="py-6">
      <h1 className="text-2xl font-semibold tracking-tight">
        {t("auth.register.title")}
      </h1>
      <p className="mt-1 text-sm text-muted">{t("auth.register.subtitle")}</p>

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
          <label className="label" htmlFor="full_name">
            {t("auth.name")}
          </label>
          <input
            id="full_name"
            className="input"
            autoComplete="name"
            required
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
        </div>
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
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-describedby="password-rule"
            aria-invalid={!passwordOk && password.length > 0}
          />
          <p
            id="password-rule"
            className={[
              "mt-2 flex items-center gap-1.5 text-xs",
              passwordOk ? "text-ok" : "text-muted",
            ].join(" ")}
          >
            {passwordOk && <CheckIcon size={14} />}
            <span>
              {passwordOk ? t("auth.passwordOk") : t("auth.passwordRule")}
            </span>
            {problem && password.length > 0 && (
              <span className="ml-auto font-mono text-faint">{problem}</span>
            )}
          </p>
        </div>
        <div>
          <label className="label" htmlFor="phone">
            {t("auth.phone")}{" "}
            <span className="normal-case text-faint">
              ({t("common.optional")})
            </span>
          </label>
          <input
            id="phone"
            className="input"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </div>
        <button
          type="submit"
          disabled={busy || !!problem}
          className="btn btn-primary btn-lg btn-block"
        >
          {busy ? t("common.loading") : t("auth.register.submit")}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-muted">
        {t("auth.haveAccount")}{" "}
        <Link
          to="/login"
          className="font-medium text-text underline underline-offset-4"
        >
          {t("auth.login.title")}
        </Link>
      </p>
    </div>
  );
}
