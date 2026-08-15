import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

export function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", phone: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (form.password.length < 8 || !/[A-Z]/.test(form.password) || !/\d/.test(form.password)) {
      setError("Password must be at least 8 characters with one uppercase letter and one digit.");
      return;
    }
    setBusy(true);
    try {
      await register({ ...form, full_name: form.full_name.trim() });
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Registration failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md px-4 py-16">
      <h1 className="mb-1 text-2xl font-bold text-white">Create your profile</h1>
      <p className="mb-6 text-sm text-slate-400">
        Your profile lets responders reach you and your emergency contact if you're ever
        unresponsive.
      </p>

      <form onSubmit={submit} className="card space-y-4">
        <div>
          <label className="label">Full name</label>
          <input className="input" value={form.full_name} onChange={set("full_name")} required minLength={2} />
        </div>
        <div>
          <label className="label">Email</label>
          <input type="email" className="input" value={form.email} onChange={set("email")} required />
        </div>
        <div>
          <label className="label">Password</label>
          <input
            type="password"
            className="input"
            value={form.password}
            onChange={set("password")}
            required
            placeholder="8+ chars, 1 uppercase, 1 digit"
          />
        </div>
        <div>
          <label className="label">Phone (optional)</label>
          <input className="input" value={form.phone} onChange={set("phone")} />
        </div>

        {error && <p className="text-sm text-danger-400">{error}</p>}

        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-slate-400">
        Already registered?{" "}
        <Link to="/login" className="text-accent-400 hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
