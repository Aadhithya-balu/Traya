import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { DemoRun, DemoScenario } from "../api/types";
import { StatusBadge, ScoreBar, NextAction } from "../components/StatusBadge";
import { QualityPanel } from "../components/QualityPanel";
import { LiveStatus } from "../components/LiveStatus";
import { useI18n } from "../i18n";

export function Demo() {
  const { t } = useI18n();
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [run, setRun] = useState<DemoRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    api
      .demoScenarios()
      .then(setScenarios)
      .catch(() => setError(t("demo.error.load")));
  }, [t]);

  const runScenario = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = await api.demoRun(id, 28.6139, 77.209);
      setRun(next);
      setAnnouncement(t("demo.live.done", { status: next.identification.status }));
    } catch (err) {
      setError(err instanceof ApiError && err.detail ? err.detail : t("demo.error.run"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-3xl font-bold text-text">{t("demo.heading")}</h1>
      <p className="mt-2 max-w-2xl text-sm text-muted">{t("demo.intro")}</p>

      <LiveStatus message={announcement} className="sr-only" />

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger"
        >
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
            {/*
              The scenario title and description are authored by the demo seed
              in the backend, not by this catalogue, so they are rendered as
              data. The buttons around them are still localized, which is what a
              user can be held to.
            */}
            <h2 className="font-semibold text-text">{s.title}</h2>
            <p className="mt-1 text-sm text-muted">{s.description}</p>
            <span className="mt-3 inline-block text-xs font-medium text-accent">
              {busy ? t("demo.running") : t("demo.runAction")}
            </span>
          </button>
        ))}
      </div>

      {run && (
        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          <div>
            <h2 className="mb-3 font-semibold text-text">{t("demo.inputTitle")}</h2>
            {run.preview_image ? (
              <img
                src={`data:image/jpeg;base64,${run.preview_image}`}
                alt={t("demo.inputAlt")}
                className="aspect-[3/4] w-full rounded-xl border border-line object-cover"
              />
            ) : (
              <div className="flex aspect-[3/4] w-full items-center justify-center rounded-xl border border-line bg-raised text-faint">
                {t("demo.noImage")}
              </div>
            )}
          </div>

          <div className="space-y-4">
            <div className="card space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-text">{t("demo.outcomeTitle")}</h2>
                <StatusBadge status={run.identification.status} />
              </div>

              {/* Instruction before the score, for the same reason as the hub. */}
              <div className="rounded-lg border border-line bg-raised p-3">
                <NextAction status={run.identification.status} />
              </div>

              <p className="text-sm text-muted">{run.identification.human_readable}</p>
              <ScoreBar
                value={run.identification.confidence}
                thresholdHigh={0.82}
                thresholdReview={0.62}
              />

              {/*
                The disclosure this page was missing. `Demo` is the first page a
                reviewer opens and it rendered a bare confidence percentage with
                no indication of which engine produced it - so a reader could
                reasonably take a scripted scenario's score for evidence that the
                recogniser works. Per ADR 0001 the disclosure belongs on every
                result.
              */}
              <DemoEngineDisclosure run={run} />

              <div className="flex flex-wrap gap-2">
                {run.identification.method.map((m) => (
                  <span key={m} className="badge bg-raised text-muted">
                    {m.replace(/_/g, " ")}
                  </span>
                ))}
                {run.identification.fallback_used && (
                  <span className="badge bg-warn/15 text-warn">{t("hub.result.fallback")}</span>
                )}
              </div>
              <p className="text-xs text-faint">
                {t("demo.sessionMeta", {
                  code: run.session_code,
                  count: run.identification.face_count,
                })}
              </p>
            </div>

            {run.identification.candidates.length > 0 && (
              <div className="card">
                <h3 className="mb-3 font-semibold text-text">{t("demo.candidates")}</h3>
                <ul className="space-y-2">
                  {run.identification.candidates.map((c) => (
                    <li
                      key={c.user_id}
                      className="flex items-center justify-between rounded-lg border border-line bg-surface p-3"
                    >
                      <div>
                        <span className="text-sm font-medium text-text">#{c.rank}</span>
                        <span className="ml-2 text-sm text-muted">{c.user_id.slice(0, 12)}…</span>
                      </div>
                      <span className="font-mono text-sm text-accent">
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

/**
 * Which engine produced this scripted result.
 *
 * Every scenario on this page runs the simulation by construction, because the
 * scenarios are generated from synthetic drawings that a real detector correctly
 * finds no face in. So the honest statement is unconditional rather than
 * conditional, and it is not dismissible: the whole point of the page is that a
 * reviewer can see what the platform does, including the fact that it is not
 * recognising anyone.
 */
function DemoEngineDisclosure({ run }: { run: DemoRun }) {
  const { t } = useI18n();
  return (
    <div className="rounded-lg border border-warn/40 bg-warn/10 p-3" role="note">
      <p className="text-sm font-medium text-warn">{t("demo.engine.title")}</p>
      <p className="mt-1.5 text-xs leading-relaxed text-muted">
        {t("demo.engine.body", {
          mode: run.identification.engine_mode,
          version: run.identification.algo_version ? ` · ${run.identification.algo_version}` : "",
        })}
      </p>
    </div>
  );
}