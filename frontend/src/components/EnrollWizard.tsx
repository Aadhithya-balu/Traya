import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type {
  EnrollmentComplete,
  EnrollmentState,
  SampleVerdict,
} from "../api/types";
import { useCamera, fileToBase64 } from "../hooks/useCamera";
import { useI18n, type StringKey } from "../i18n";

/** Engine guidance codes arrive as bare strings; the prose lives in i18n. */
function guidanceKey(code: string): StringKey | null {
  const key = `enroll.guidance.${code}` as StringKey;
  return key;
}

interface EnrollWizardProps {
  onEnrolled: (status: EnrollmentComplete) => void;
  onCancel: () => void;
}

export function EnrollWizard({ onEnrolled, onCancel }: EnrollWizardProps) {
  const { t } = useI18n();
  const camera = useCamera();

  const [state, setState] = useState<EnrollmentState | null>(null);
  const [verdict, setVerdict] = useState<SampleVerdict | null>(null);
  const [done, setDone] = useState<EnrollmentComplete | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const begin = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      setState(await api.startEnrollment());
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : t("common.error"));
    } finally {
      setBusy(false);
    }
  }, [t]);

  useEffect(() => {
    void begin();
  }, [begin]);

  const submit = useCallback(
    async (image: string | null) => {
      if (!state || !image) return;
      setBusy(true);
      setError(null);
      try {
        const res = await api.submitEnrollmentSample(state.enrollment_id, image);
        setVerdict(res.verdict);
        setState(res.state);
      } catch (e) {
        // A 422 here is the consistency or minimum-sample guard. The wizard is
        // finished at that point, so the person has to start over rather than
        // keep capturing into an enrollment that will not commit.
        setError(e instanceof ApiError ? e.detail : t("common.error"));
        if (e instanceof ApiError && (e.status === 410 || e.status === 409)) {
          setState(null);
        }
      } finally {
        setBusy(false);
      }
    },
    [state, t],
  );

  const onCapture = useCallback(async () => {
    setBusy(true);
    try {
      await submit(await camera.capture());
    } finally {
      setBusy(false);
    }
  }, [camera, submit]);

  const onFile = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (file) await submit(await fileToBase64(file));
    },
    [submit],
  );

  const onFinish = useCallback(async () => {
    if (!state) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.completeEnrollment(state.enrollment_id);
      setDone(res);
      camera.stop();
      onEnrolled(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : t("common.error"));
    } finally {
      setBusy(false);
    }
  }, [camera, onEnrolled, state, t]);

  const onStartOver = useCallback(async () => {
    if (state) {
      await api.cancelEnrollment(state.enrollment_id).catch(() => undefined);
    }
    camera.stop();
    setVerdict(null);
    setDone(null);
    await begin();
  }, [begin, camera, state]);

  // ---- finished ---------------------------------------------------------
  if (done) {
    return (
      <div className="card space-y-4">
        <h3 className="font-semibold text-text">{t("enroll.done.title")}</h3>
        <p className="text-sm text-muted">
          {t("enroll.done.body", { count: done.num_samples })}
        </p>
        {done.consistency && (
          <p className="text-sm text-muted">
            {t("enroll.spread", {
              value: done.consistency.min_pairwise.toFixed(2),
            })}
          </p>
        )}
        <button type="button" onClick={onCancel} className="btn-primary btn-block">
          {t("common.close")}
        </button>
      </div>
    );
  }

  // ---- consent still missing, or the session died ----------------------
  if (!state) {
    return (
      <div className="card space-y-4">
        {error && <p className="text-sm text-danger">{error}</p>}
        <button
          type="button"
          onClick={begin}
          className="btn-primary btn-block"
          disabled={busy}
        >
          {t("enroll.restart")}
        </button>
      </div>
    );
  }

  const currentStep = state.steps[state.current_step];

  return (
    <div className="card space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-semibold text-text">{t("enroll.title")}</h3>
        <span className="text-xs text-muted">
          {t("enroll.sample.count", {
            done: state.accepted_samples,
            total: state.min_samples,
          })}
        </span>
      </div>

      <ol className="flex gap-1.5" aria-label={t("enroll.title")}>
        {state.steps.map((step) => (
          <li
            key={step.key}
            className={`h-1.5 flex-1 rounded-full ${step.done ? "bg-accent" : "bg-line"}`}
          />
        ))}
      </ol>

      <p className="text-sm text-muted">{t("enroll.intro")}</p>

      <p className="text-lg font-medium text-text">
        {t(`enroll.step.${currentStep?.key ?? "front"}` as StringKey)}
      </p>

      <div className="relative overflow-hidden rounded-xl bg-raised">
        <video
          ref={camera.videoRef as React.RefObject<HTMLVideoElement>}
          playsInline
          muted
          autoPlay
          className="aspect-[3/4] w-full object-cover"
        />
        {!camera.active && (
          <div className="absolute inset-0 flex items-center justify-center p-4">
            <button
              type="button"
              onClick={() => void camera.start()}
              className="btn btn-primary"
              disabled={busy}
            >
              {t("enroll.camera.start")}
            </button>
          </div>
        )}
        {camera.error && (
          <div className="absolute inset-x-0 bottom-0 bg-danger/90 p-3 text-center text-sm text-accent-fg">
            {camera.error}
          </div>
        )}
      </div>

      {verdict && verdict.guidance.length > 0 && (
        <ul className="space-y-1 text-sm" aria-live="polite">
          {verdict.guidance.map((code) => {
            const key = guidanceKey(code);
            return (
              <li
                key={code}
                className={
                  verdict.accepted ? "text-ok" : "text-warn"
                }
              >
                {key ? t(key) : code}
              </li>
            );
          })}
        </ul>
      )}

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={onCapture}
          className="btn btn-primary flex-1"
          disabled={busy || !camera.active}
        >
          {busy ? t("enroll.step.capturing") : t("enroll.capture")}
        </button>
        <label className="btn btn-ghost">
          {t("emergency.intro.upload")}
          <input
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={onFile}
          />
        </label>
        {camera.active && (
          <button
            type="button"
            onClick={camera.stop}
            className="btn-ghost px-3"
            disabled={busy}
          >
            {t("enroll.camera.stop")}
          </button>
        )}
      </div>

      <p className="text-xs text-muted">
        {state.accepted_samples === 1
          ? t("enroll.photos.one")
          : t("enroll.photos.many", { count: state.accepted_samples })}
      </p>

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => void onFinish()}
          className="btn btn-block"
          disabled={busy || !state.can_complete}
        >
          {t("enroll.finish")}
        </button>
        <button
          type="button"
          onClick={onStartOver}
          className="btn-ghost px-3"
          disabled={busy}
        >
          {t("enroll.restart")}
        </button>
      </div>
    </div>
  );
}