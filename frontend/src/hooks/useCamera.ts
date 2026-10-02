import { useCallback, useEffect, useRef, useState } from "react";
import type { StringKey } from "../i18n";

/**
 * Why the camera failed, as a code rather than a sentence.
 *
 * This hook previously held English strings, which meant a Tamil responder read
 * "Camera permission denied." in English at the exact moment they needed to
 * know whether to retry or change approach. Returning a code keeps presentation
 * in the page, where `t()` lives, and keeps the hook translatable by
 * construction - a hook that owns copy cannot be translated without the hook
 * changing.
 *
 * The set is closed on purpose: each member is a distinguishable thing a person
 * can act on differently. "denied" means grant permission or upload a file;
 * "unsupported" means this browser will never work and uploading is the only
 * route; "unavailable" means the hardware or another process is holding it.
 */
export type CameraErrorCode =
  | "unsupported"
  | "denied"
  | "unavailable"
  | "noFrames"
  | "encodeFailed";

/**
 * Total by construction: adding a `CameraErrorCode` without a translation here
 * is a compile error rather than a screen that renders an untranslated key at
 * the moment someone needs the message.
 */
export const CAMERA_ERROR_KEYS: Record<CameraErrorCode, StringKey> = {
  unsupported: "emergency.camera.error.unsupported",
  denied: "emergency.camera.error.denied",
  unavailable: "emergency.camera.error.unavailable",
  noFrames: "emergency.camera.error.noFrames",
  encodeFailed: "emergency.camera.error.encodeFailed",
};

export type CaptureResult =
  | { readonly ok: true; readonly data: string }
  | { readonly ok: false; readonly error: CameraErrorCode };

export interface CameraState {
  stream: MediaStream | null;
  error: CameraErrorCode | null;
  capturing: boolean;
  /** True while the stream is running, so the UI can show a stop affordance. */
  active: boolean;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  start: () => Promise<void>;
  stop: () => void;
  capture: () => Promise<CaptureResult>;
}

export function useCamera(): CameraState {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<CameraErrorCode | null>(null);
  const [capturing, setCapturing] = useState(false);

  const start = useCallback(async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("unsupported");
      return;
    }
    try {
      // environment, not user: a responder is photographing the person in
      // front of them, not themselves.
      const s = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1080 },
          height: { ideal: 1440 },
        },
        audio: false,
      });
      streamRef.current = s;
      setStream(s);
    } catch (e) {
      setError(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "denied"
          : "unavailable",
      );
    }
  }, []);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStream(null);
  }, []);

  const capture = useCallback(async (): Promise<CaptureResult> => {
    const video = videoRef.current;
    // readyState < 2 means no frame has been decoded yet, so drawing would
    // produce a black image that then fails a blur check for reasons that have
    // nothing to do with blur. Reported rather than swallowed: a silent null is
    // indistinguishable from a responder pressing the shutter on a camera that
    // is working perfectly.
    if (!video || video.readyState < 2) return { ok: false, error: "noFrames" };
    setCapturing(true);
    try {
      const width = video.videoWidth || 720;
      const height = video.videoHeight || 960;
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return { ok: false, error: "encodeFailed" };
      ctx.drawImage(video, 0, 0, width, height);
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", 0.9),
      );
      if (!blob) return { ok: false, error: "encodeFailed" };
      return { ok: true, data: await blobToBase64(blob) };
    } finally {
      setCapturing(false);
    }
  }, []);

  useEffect(() => {
    if (stream && videoRef.current) {
      videoRef.current.srcObject = stream;
      videoRef.current.play().catch(() => undefined);
    }
  }, [stream]);

  useEffect(() => () => stop(), [stop]);

  return {
    stream,
    error,
    capturing,
    active: !!stream,
    videoRef,
    start,
    stop,
    capture,
  };
}

export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

export function fileToBase64(file: File): Promise<string> {
  return blobToBase64(file);
}
