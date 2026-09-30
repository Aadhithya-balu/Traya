import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, api, clearTokens, getTokens, setTokens } from "../api/client";
import type { UserSummary } from "../api/types";

/**
 * Authentication is a four-state machine, not a boolean.
 *
 * The previous version collapsed every failure into "signed out", so a 500 or a
 * dropped connection rendered the logged-out screen while the tokens were still
 * in localStorage. That is indistinguishable from a real logout to the person
 * using the app, and it is one of the two causes of the reported "the emergency
 * flow logs me out" complaint.
 */
type AuthStatus =
  /** The answer is not known yet. Never render a logged-out screen from here. */
  | "loading"
  /** Confirmed: a token exists and the server confirmed it. */
  | "authenticated"
  /** Confirmed: no token, or the server rejected the token with 401. */
  | "unauthenticated"
  /** A token exists but the server could not be reached. Retry, do not sign out. */
  | "error";

interface AuthState {
  user: UserSummary | null;
  status: AuthStatus;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: {
    full_name: string;
    email: string;
    password: string;
    phone?: string;
  }) => Promise<void>;
  logout: () => void;
  isAuthed: boolean;
  hasRole: (...roles: string[]) => boolean;
  /** True when the signed-in account holds the given permission. */
  can: (permission: string) => boolean;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/** Only a definitive rejection ends a session. Anything else is transient. */
function isDefinitiveRejection(err: unknown): boolean {
  if (err instanceof ApiError) {
    if (err.isNetwork) return false;
    return err.status === 401 || err.status === 403;
  }
  return false;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserSummary | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  /**
   * Re-reads the signed-in user.
   *
   * A network failure leaves the existing user and token intact and moves to
   * `error`, so the UI can offer a retry. Only an explicit 401/403 clears the
   * session.
   */
  const refreshUser = useCallback(async () => {
    if (!getTokens().access) {
      setUser(null);
      setStatus("unauthenticated");
      return;
    }
    try {
      const me = await api.me();
      setUser(me);
      setStatus("authenticated");
    } catch (err) {
      if (isDefinitiveRejection(err)) {
        clearTokens();
        setUser(null);
        setStatus("unauthenticated");
      } else {
        setStatus("error");
      }
    }
  }, []);

  useEffect(() => {
    // A first-time visitor has no token, so make no auth call at all.
    if (!getTokens().access) {
      setStatus("unauthenticated");
      return;
    }
    refreshUser();
  }, [refreshUser]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.login(email, password);
      setTokens(res.access_token, res.refresh_token);
      setUser(res.user);
      setStatus("authenticated");
    },
    [],
  );

  const register = useCallback(
    async (payload: { full_name: string; email: string; password: string; phone?: string }) => {
      const res = await api.register(payload);
      setTokens(res.access_token, res.refresh_token);
      setUser(res.user);
      setStatus("authenticated");
    },
    [],
  );

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const hasRole = useCallback(
    (...roles: string[]) => {
      if (!user) return false;
      return roles.some((r) => user.roles.includes(r));
    },
    [user],
  );

  // Roles decide which tabs a person sees; permissions decide what they can
  // actually do. Gating on permissions keeps the UI from offering an action the
  // API would refuse.
  const can = useCallback(
    (permission: string) => !!user?.permissions?.includes(permission),
    [user],
  );

  const loading = status === "loading";

  return (
    <AuthContext.Provider
      value={{
        user,
        status,
        loading,
        login,
        register,
        logout,
        isAuthed: status === "authenticated" && !!user,
        hasRole,
        can,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
