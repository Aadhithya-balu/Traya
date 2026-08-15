import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { CaptureOut } from "../api/types";
import { useCamera, fileToBase64 } from "../hooks/useCamera";
import { useEmergency } from "../context/EmergencyContext";
import { QualityPanel } from "../components/QualityPanel";
import { StatusBadge } from "../components/StatusBadge";

type Step = "intro" | "capture" | "quality" | "identifying" | "done";

export function Emergency() {
  const navigate = useNavigate();
  const { setSession, setResult } = useEmergency();
  const camera = useCamera();
  const fileRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<Step>("intro");
  const [sessionId, setSessionIdState] = useState<string | null>(null);
  const [sessionCode, setSessionCode] = useState<string | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [quality, setQuality] = useState<CaptureOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [secondaryFeatures, setSecondaryFeatures] = useState<string[]>([]);

  const begin = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.startSession("public");
      setSessionIdState(res.session_id);
      setSessionCode(res.session_code);
      setSession(res.session_id);
      setStep("capture");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not start an emergency session.");
    } finally {
      setBusy(false);
    }
  }, [setSession]);

  useEffect(() => {
    if (step === "capture") {
      camera.start();
    }
    return () => camera.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const useImage = useCallback(
    async (b64: string, preview: string) => {
      if (!sessionId) return;
      setImage(b64);
      setImagePreview(preview);
      setStep("quality");
      setBusy(true);
      setError(null);
      try {
        const q = await api.capture(sessionId, b64);
        setQuality(q);
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : "Quality check failed.");
      } finally {
        setBusy(false);
      }
    },
    [sessionId],
  );

  const onCameraCapture = async () => {
    const b64 = await camera.capture();
    if (b64) await useImage(b64, `data:image/jpeg;base64,${b64}`);
  };

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError("Please upload a JPEG, PNG or WebP image.");
      return;
    }
    const b64 = await fileToBase64(file);
    await useImage(b64, URL.createObjectURL(file));
  };

  const identify = async () => {
    if (!sessionId || !image) return;
    setStep("identifying");
    setError(null);
    try {
      const res = await api.identify(sessionId, image, secondaryFeatures);
      setResult(res, imagePreview);
      setStep("done");
      navigate(`/emergency/${sessionId}`, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Identification failed.");
      setStep("quality");
    }
  };

  const retry = () => {
    setImage(null);
    setImagePreview(null);
    setQuality(null);
    setStep("capture");
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-3xl font-bold text-white">Emergency identification</h1>
      <p className="mt-2 text-sm text-slate-400">
        A single clear photo of the victim's face is all we need to begin.
      </p>

      {sessionCode && (
        <div className="mt-4 flex items-center gap-3 rounded-xl border border-accent-500/30 bg-accent-500/10 px-4 py-3">
          <span className="font-mono text-sm text-accent-400">{sessionCode}</span>
          <span className="text-xs text-slate-400">
            Emergency session active · expires after 30 minutes
          </span>
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-lg border border-danger-500/30 bg-danger-500/10 p-3 text-sm text-danger-400">
          {error}
        </div>
      )}

      <div className="mt-6 space-y-6">
        {step === "intro" && (
          <div className="card">
            <h2 className="mb-2 font-semibold text-white">Before you begin</h2>
            <ul className="mb-4 list-inside list-disc space-y-1 text-sm text-slate-400">
              <li>Ensure the victim's face is visible and well lit.</li>
              <li>Only one face should be in the frame.</li>
              <li>Photos are processed for matching and are not stored.</li>
            </ul>
            <button onClick={begin} className="btn-primary" disabled={busy}>
              {busy ? "Starting…" : "Start session"}
            </button>
          </div>
        )}

        {(step === "capture" || step === "quality") && (
          <div className="card">
            <h2 className="mb-3 font-semibold text-white">Capture the victim's face</h2>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <div className="relative aspect-[3/4] w-full overflow-hidden rounded-lg border border-slate-700 bg-ink-950">
                  {camera.stream && (
                    <video
                      ref={camera.videoRef}
                      className="h-full w-full object-cover"
                      autoPlay
                      playsInline
                      muted
                    />
                  )}
                  {imagePreview && <img src={imagePreview} alt="capture" className="h-full w-full object-cover" />}
                </div>
                {camera.error && <p className="mt-2 text-xs text-danger-400">{camera.error}</p>}
                {!camera.stream && !imagePreview && (
                  <p className="mt-2 text-xs text-slate-500">Camera feed or uploaded image appears here.</p>
                )}
              </div>

              <div className="flex flex-col gap-3">
                <button onClick={onCameraCapture} className="btn-primary" disabled={camera.capturing || !camera.stream}>
                  {camera.capturing ? "Capturing…" : "Capture from camera"}
                </button>
                <button onClick={() => fileRef.current?.click()} className="btn-ghost">
                  Upload a photo
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  className="hidden"
                  onChange={onFile}
                />
                <p className="text-xs text-slate-500">
                  Face matching works best with a front-facing, evenly lit shot. Blurry or
                  multi-face images are automatically rejected.
                </p>
              </div>
            </div>
          </div>
        )}

        {step === "quality" && quality && (
          <div className="card space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white">Capture quality</h2>
              <StatusBadge status={quality.usable_for_matching ? "HIGH_CONFIDENCE" : "POOR_QUALITY"} />
            </div>
            <QualityPanel
              quality={{
                image_quality_score: quality.image_quality_score ?? 0,
                face_visibility_score: quality.face_visibility_score ?? 0,
                occlusion_score: quality.occlusion_score ?? 0,
                blur_score: quality.blur_score ?? 0,
                lighting_score: quality.lighting_score ?? 0,
                usable_for_matching: quality.usable_for_matching,
                reasons: quality.reasons,
              }}
            />

            <div>
              <label className="label">Secondary features (optional)</label>
              <div className="flex flex-wrap gap-2">
                {["glasses", "tattoo", "scar", "beard", "birthmark", "piercing"].map((f) => (
                  <button
                    key={f}
                    type="button"
                    onClick={() =>
                      setSecondaryFeatures((prev) =>
                        prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f],
                      )
                    }
                    className={`badge border ${
                      secondaryFeatures.includes(f)
                        ? "border-accent-500 bg-accent-500/15 text-accent-400"
                        : "border-slate-700 text-slate-400 hover:border-slate-500"
                    }`}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-3">
              <button onClick={identify} className="btn-primary" disabled={busy}>
                {busy ? "Analyzing…" : "Identify victim"}
              </button>
              <button onClick={retry} className="btn-ghost">
                Retake photo
              </button>
            </div>
          </div>
        )}

        {step === "identifying" && (
          <div className="card text-center">
            <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-slate-700 border-t-accent-400" />
            <p className="text-sm text-slate-300">Running facial matching against enrolled templates…</p>
            <p className="mt-1 text-xs text-slate-500">This may take a few seconds.</p>
          </div>
        )}
      </div>
    </div>
  );
}
