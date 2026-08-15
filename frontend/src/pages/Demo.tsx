import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { DemoRun, DemoScenario } from "../api/types";
import { StatusBadge, ScoreBar } from "../components/StatusBadge";
import { QualityPanel } from "../components/QualityPanel";

export function Demo() {
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [run, setRun] = useState<DemoRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .demoScenarios()
      .then(setScenarios)
      .catch(() => setError("Could not load demo scenarios."));
  }, []);

  const runScenario = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      setRun(await api.demoRun(id, 28.6139, 77.209));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Scenario run failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-3xl font-bold text-white">Interactive demo</h1>
      <p className="mt-2 max-w-2xl text-sm text-slate-400">
        TRAYA runs entirely on synthetic demo data. Pick a scenario to see how the platform
        behaves — including the cases where it deliberately refuses to guess.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-danger-500/30 bg-danger-500/10 p-3 text-sm text-danger-400">
          {error}
        </div>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {scenarios.map((s) => (
          <button
            key={s.id}
            onClick={() => runScenario(s.id)}
            disabled={busy}
            className="card text-left transition-colors hover:border-accent-500/40"
          >
            <h2 className="font-semibold text-white">{s.title}</h2>
            <p className="mt-1 text-sm text-slate-400">{s.description}</p>
            <span className="mt-3 inline-block text-xs font-medium text-accent-400">
              {busy ? "Running…" : "Run scenario →"}
            </span>
          </button>
        ))}
      </div>

      {run && (
        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          <div>
            <h2 className="mb-3 font-semibold text-white">Scenario input</h2>
            {run.preview_image ? (
              <img
                src={`data:image/jpeg;base64,${run.preview_image}`}
                alt="Scenario input"
                className="aspect-[3/4] w-full rounded-xl border border-slate-800 object-cover"
              />
            ) : (
              <div className="flex aspect-[3/4] w-full items-center justify-center rounded-xl border border-slate-800 bg-ink-950 text-slate-600">
                No image available
              </div>
            )}
          </div>

          <div className="space-y-4">
            <div className="card space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-white">Identification outcome</h2>
                <StatusBadge status={run.identification.status} />
              </div>
              <p className="text-sm text-slate-300">{run.identification.human_readable}</p>
              <ScoreBar value={run.identification.confidence} thresholdHigh={0.82} thresholdReview={0.62} />
              <div className="flex flex-wrap gap-2">
                {run.identification.method.map((m) => (
                  <span key={m} className="badge bg-slate-700 text-slate-300">
                    {m.replace(/_/g, " ")}
                  </span>
                ))}
                {run.identification.fallback_used && (
                  <span className="badge bg-warn-400/15 text-warn-400">fallback used</span>
                )}
              </div>
              <p className="text-xs text-slate-500">
                Session {run.session_code} · faces detected: {run.identification.face_count}
              </p>
            </div>

            {run.identification.candidates.length > 0 && (
              <div className="card">
                <h3 className="mb-3 font-semibold text-white">Candidates</h3>
                <ul className="space-y-2">
                  {run.identification.candidates.map((c) => (
                    <li
                      key={c.user_id}
                      className="flex items-center justify-between rounded-lg border border-slate-800 bg-ink-900 p-3"
                    >
                      <div>
                        <span className="text-sm font-medium text-white">#{c.rank}</span>
                        <span className="ml-2 text-sm text-slate-400">{c.user_id.slice(0, 12)}…</span>
                      </div>
                      <span className="font-mono text-sm text-accent-400">
                        {Math.round(c.confidence * 100)}%
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {run.identification.quality && <QualityPanel quality={run.identification.quality} />}
          </div>
        </div>
      )}
    </div>
  );
}
