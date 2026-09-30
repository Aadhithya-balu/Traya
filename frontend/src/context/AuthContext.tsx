import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, clearTokens, setTokens } from "../api/client";
import type { UserSummary } from "../api/types";

interface AuthState {
  user: UserSummary | null;
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("traya_access");
    if (!token) {
      setLoading(false);
      return;
    }
    refreshUser().finally(() => setLoading(false));
  }, [refreshUser]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.login(email, password);
      setTokens(res.access_token, res.refresh_token);
      setUser(res.user);
    },
    [],
  );

  const register = useCallback(
    async (payload: { full_name: string; email: string; password: string; phone?: string }) => {
      const res = await api.register(payload);
      setTokens(res.access_token, res.refresh_token);
      setUser(res.user);
    },
    [],
  );

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
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

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        register,
        logout,
        isAuthed: !!user,
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
