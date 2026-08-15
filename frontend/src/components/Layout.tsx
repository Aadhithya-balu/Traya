import { Link, NavLink, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../context/AuthContext";

export function Layout({ children }: { children?: ReactNode }) {
  const { user, isAuthed, logout, hasRole } = useAuth();
  const navigate = useNavigate();

  const navLink = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
      isActive ? "bg-slate-800 text-accent-400" : "text-slate-300 hover:text-white"
    }`;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-ink-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-500 font-mono text-lg font-bold text-ink-950">
              T
            </span>
            <span className="text-lg font-bold tracking-wide text-white">TRAYA</span>
          </Link>

          <nav className="hidden items-center gap-1 md:flex">
            <NavLink to="/" className={navLink} end>
              Home
            </NavLink>
            <NavLink to="/emergency" className={navLink}>
              Emergency
            </NavLink>
            <NavLink to="/demo" className={navLink}>
              Demo
            </NavLink>
            {isAuthed && (
              <NavLink to="/dashboard" className={navLink}>
                Dashboard
              </NavLink>
            )}
            {hasRole("admin") && (
              <NavLink to="/admin" className={navLink}>
                Admin
              </NavLink>
            )}
          </nav>

          <div className="flex items-center gap-2">
            {isAuthed ? (
              <>
                <span className="hidden text-sm text-slate-400 sm:inline">{user?.full_name}</span>
                <button
                  onClick={() => {
                    logout();
                    navigate("/");
                  }}
                  className="btn-ghost !px-3 !py-1.5 text-sm"
                >
                  Log out
                </button>
              </>
            ) : (
              <Link to="/login" className="btn-ghost !px-3 !py-1.5 text-sm">
                Log in
              </Link>
            )}
          </div>
        </div>

        <nav className="flex items-center gap-1 overflow-x-auto border-t border-slate-800 px-4 py-1.5 md:hidden">
          <NavLink to="/" className={navLink} end>
            Home
          </NavLink>
          <NavLink to="/emergency" className={navLink}>
            Emergency
          </NavLink>
          <NavLink to="/demo" className={navLink}>
            Demo
          </NavLink>
          {isAuthed && (
            <NavLink to="/dashboard" className={navLink}>
              Dashboard
            </NavLink>
          )}
          {hasRole("admin") && (
            <NavLink to="/admin" className={navLink}>
              Admin
            </NavLink>
          )}
        </nav>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-slate-800 bg-ink-950 py-6 text-center text-xs text-slate-500">
        <p>
          TRAYA — Emergency Victim Identification · Synthetic demo data only · Biometric templates are
          encrypted at rest and never shared.
        </p>
      </footer>
    </div>
  );
}
