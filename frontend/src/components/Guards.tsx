import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../context/AuthContext";

export function Protected({ children }: { children: ReactNode }) {
  const { isAuthed, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-muted">
        Loading…
      </div>
    );
  }
  if (!isAuthed) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function AdminOnly({ children }: { children: ReactNode }) {
  const { isAuthed, loading, hasRole } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-muted">
        Loading…
      </div>
    );
  }
  if (!isAuthed) return <Navigate to="/login" replace />;
  if (!hasRole("admin")) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}
