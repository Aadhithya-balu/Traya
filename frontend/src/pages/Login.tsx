import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Login failed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const fill = (demoEmail: string) => {
    setEmail(demoEmail);
    setPassword("TrayaDemo#2026");
  };

  return (
    <div className="mx-auto max-w-md px-4 py-16">
      <h1 className="mb-1 text-2xl font-bold text-white">Log in</h1>
      <p className="mb-6 text-sm text-slate-400">Access your TRAYA account.</p>

      <form onSubmit={submit} className="card space-y-4">
        <div>
          <label className="label">Email</label>
          <input
            type="email"
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </div>
        <div>
          <label className="label">Password</label>
          <input
            type="password"
            className="input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </div>

        {error && <p className="text-sm text-danger-400">{error}</p>}

        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>

      <div className="mt-6 rounded-xl border border-slate-800 bg-ink-800 p-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">
          Demo accounts (password: TrayaDemo#2026)
        </p>
        <div className="flex flex-wrap gap-2">
          {[
            ["aarav.kumar@demo.traya", "Enrolled user"],
            ["neha.rao@responder.traya", "Medical responder"],
            ["admin@traya.io", "Admin"],
          ].map(([em, label]) => (
            <button key={em} onClick={() => fill(em)} className="btn-ghost !px-2.5 !py-1 text-xs">
              {label}
            </button>
          ))}
        </div>
      </div>

      <p className="mt-4 text-center text-sm text-slate-400">
        New here?{" "}
        <Link to="/register" className="text-accent-400 hover:underline">
          Create an account
        </Link>
      </p>
    </div>
  );
}
