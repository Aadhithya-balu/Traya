import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n";

/**
 * `status === "error"` is not "signed out".
 *
 * A token exists, the server could not be reached. Redirecting to `/login` here
 * is the single most damaging thing this file could do: it renders a logged-out
 * screen while the tokens are still valid, the person believes they have been
 * signed out of their own account, and the Phase 8 gate explicitly forbids it.
 * So the transient state gets its own surface with a retry, and only a confirmed
 * 401/403 is allowed to navigate away.
 */
function AuthGate({ children, requireAdmin }: { children: ReactNode; requireAdmin?: boolean }) {
  const { isAuthed, loading, status, hasRole, refreshUser } = useAuth();
  const { t } = useI18n();

  if (loading) {
    return (
      <div
        className="flex min-h-[50vh] items-center justify-center text-muted"
        role="status"
        aria-live="polite"
      >
        {t("common.loading")}
      </div>
    );
  }

  if (status === "error") {
    return (
      <div
        className="flex min-h-[50vh] flex-col items-center justify-center gap-4 px-6 text-center"
        role="alert"
      >
        <p className="max-w-sm text-sm text-muted">{t("auth.session.unreachable")}</p>
        <div className="flex gap-2">
          <button type="button" className="btn btn-primary" onClick={() => void refreshUser()}>
            {t("common.retry")}
          </button>
          <button type="button" className="btn" onClick={() => window.location.assign("/")}>
            {t("nav.home")}
          </button>
        </div>
      </div>
    );
  }

  if (!isAuthed) return <Navigate to="/login" replace />;
  if (requireAdmin && !hasRole("admin")) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}

export function Protected({ children }: { children: ReactNode }) {
  return <AuthGate>{children}</AuthGate>;
}

export function AdminOnly({ children }: { children: ReactNode }) {
  return <AuthGate requireAdmin>{children}</AuthGate>;
}
