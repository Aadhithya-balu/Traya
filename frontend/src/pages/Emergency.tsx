import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { QualityScores } from "../api/types";
import { QualityPanel } from "../components/QualityPanel";
import { AlertIcon, CameraIcon, PulseIcon } from "../components/icons";
import { useEmergency } from "../context/EmergencyContext";
import { useI18n } from "../i18n";
import { fileToBase64, useCamera } from "../hooks/useCamera";

type Stage = "intro" | "capture" | "review" | "working";

export function Emergency() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const camera = useCamera();
  const { setPreview, setResult, setSession } = useEmergency();

  const [stage, setStage] = useState<Stage>("intro");
  const [imageB64, setImageB64] = useState<string | null>(null);
  const [quality, setQuality] = useState<QualityScores | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // Leaving the flow must release the camera, or the browser indicator stays on.
  useEffect(() => () => camera.stop(), [camera.stop]);

  /**
   * A transport failure is not "you have been logged out" and not "no match".
   * The distinction matters: a person in an emergency needs to be told the
   * server could not be reached so they can move somewhere with signal.
   */
  function describe(err: unknown): string {
    if (err instanceof ApiError) {
      if (err.isNetwork) return t("error.network");
      if (err.status === 403) return t("error.sessionExpired");
      return err.detail || t("error.generic");
    }
    if (err instanceof TypeError) return t("error.network");
    return t("error.generic");
  }

  async function openCamera() {
    setError(null);
    await camera.start();
    setStage("capture");
  }

  function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError(null);
    setBusy(true);
    fileToBase64(file)
      .then((b64) => {
        camera.stop();
        setImageB64(b64);
        setStage("review");
      })
      .catch(() => setError(t("error.generic")))
      .finally(() => setBusy(false));
  }

  async function shoot() {
    const shot = await camera.capture();
    if (!shot) {
      setError(t("emergency.camera.error"));
      return;
    }
    setImageB64(shot);
    camera.stop();
    setStage("review");
  }

  async function checkAndIdentify() {
    if (!imageB64) return;
    setBusy(true);
    setError(null);
    try {
      // A public session is opened lazily, at the point the photo exists, so
      // an abandoned attempt does not litter the incident log. startSession also
      // retains the scoped session credential the later calls require.
      const session = await api.startSession("public");
      const capture = await api.capture(session.session_id, imageB64);
      setQuality(capture);
      setPreview(imageB64);

      if (!capture.usable_for_matching) {
        setStage("review");
        setBusy(false);
        return;
      }

      setStage("working");
      const result = await api.identify(session.session_id, imageB64);

      // The result travels through EmergencyContext, not router state. It used
      // to be handed to navigate() as `state`, which the destination page never
      // read - so the Match Result tab rendered nothing and the responder could
      // never reach the confirm action. Context also survives a reload of the
      // hub, which is the state a real user is often in after a redirect.
      setSession(session.session_id);
      setResult(result, imageB64);
      navigate(`/emergency/${session.session_id}`);
    } catch (err) {
      setError(describe(err));
      setStage("review");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="py-4">
      {error && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger"
        >
          <AlertIcon size={18} className="mt-px shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {stage === "intro" && (
        <div className="animate-rise">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("emergency.intro.title")}
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            {t("emergency.intro.body")}
          </p>

          <button
            type="button"
            onClick={openCamera}
            className="btn btn-danger btn-lg btn-block mt-6"
          >
            <CameraIcon size={22} />
            {t("emergency.intro.begin")}
          </button>
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="btn btn-ghost btn-lg btn-block mt-3"
          >
            {t("emergency.intro.upload")}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={onFile}
          />
        </div>
      )}

      {stage === "capture" && (
        <div className="animate-fade-in">
          <div className="relative overflow-hidden rounded-xl bg-raised">
            <video
              ref={camera.videoRef as React.RefObject<HTMLVideoElement>}
              playsInline
              muted
              autoPlay
              className="aspect-[3/4] w-full object-cover"
            />
            {/* A face-shaped guide so the framing expectation is obvious. */}
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="h-2/5 w-2/5 rounded-[50%] border-2 border-dashed border-white/60" />
            </div>
            {camera.error && (
              // The label uses the ramp's "on this colour" token, not the body-text token.
              // Body text on a 90% danger tint measured 3.18:1 in light and
              // 3.22:1 in dark, both below AA; the on-colour token reads 5.63:1
              // and 5.48:1. Class names are deliberately not written out in this
              // comment - Tailwind's scanner does not strip comments, so naming a
              // utility here emits a rule for it.
              <div className="absolute inset-x-0 bottom-0 bg-danger/90 p-3 text-center text-sm text-accent-fg">
                {camera.error}
              </div>
            )}
          </div>

          <p className="mt-3 text-center text-sm text-muted">
            {t("emergency.capture.hint")}
          </p>

          <div className="mt-4 flex gap-3">
            <button
              type="button"
              onClick={() => {
                camera.stop();
                setStage("intro");
              }}
              className="btn btn-ghost btn-lg flex-1"
            >
              {t("common.back")}
            </button>
            <button
              type="button"
              onClick={shoot}
              disabled={!camera.active || camera.capturing}
              className="btn btn-primary btn-lg flex-1"
            >
              <CameraIcon size={20} />
              {t("emergency.capture.shutter")}
            </button>
          </div>

          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="btn btn-quiet btn-block mt-2 text-sm"
          >
            {t("emergency.intro.upload")}
          </button>
        </div>
      )}

      {stage === "review" && imageB64 && (
        <div className="animate-rise">
          <img
            src={`data:image/jpeg;base64,${imageB64}`}
            alt=""
            className="aspect-[3/4] w-full rounded-xl object-cover"
          />

          {quality && <div className="mt-4"><QualityPanel quality={quality} /></div>}

          {quality && !quality.usable_for_matching && (
            <div className="mt-4 flex gap-3">
              <button
                type="button"
                onClick={() => {
                  setImageB64(null);
                  setQuality(null);
                  setStage("intro");
                }}
                className="btn btn-ghost btn-lg flex-1"
              >
                {t("emergency.capture.retake")}
              </button>
            </div>
          )}

          {!quality?.usable_for_matching && (
            <button
              type="button"
              onClick={checkAndIdentify}
              disabled={busy}
              className="btn btn-primary btn-lg btn-block mt-4"
            >
              <PulseIcon size={20} />
              {busy ? t("emergency.checking") : t("emergency.capture.use")}
            </button>
          )}
        </div>
      )}

      {stage === "working" && (
        <div
          className="animate-fade-in py-16 text-center"
          role="status"
          aria-live="polite"
        >
          <span className="mx-auto flex h-14 w-14 animate-pulse items-center justify-center rounded-full bg-raised">
            <PulseIcon size={26} />
          </span>
          <p className="mt-4 text-sm font-medium">{t("emergency.identifying")}</p>
          <p className="mt-1 text-xs text-muted">
            {t("emergency.checking")}
          </p>
        </div>
      )}
    </div>
  );
}
