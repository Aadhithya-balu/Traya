import { createContext, useCallback, useContext, useState } from "react";
import type { ReactNode } from "react";
import type { IdentifyResult } from "../api/types";

interface EmergencyState {
  sessionId: string | null;
  result: IdentifyResult | null;
  previewImage: string | null;
  setSession: (sessionId: string) => void;
  setResult: (result: IdentifyResult, preview: string | null) => void;
  setPreview: (preview: string | null) => void;
  clear: () => void;
}

const Ctx = createContext<EmergencyState | null>(null);

export function EmergencyProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(() =>
    sessionStorage.getItem("traya_emergency_session"),
  );
  const [result, setResultState] = useState<IdentifyResult | null>(() => {
    const raw = sessionStorage.getItem("traya_emergency_result");
    if (!raw) return null;
    try {
      return JSON.parse(raw) as IdentifyResult;
    } catch {
      sessionStorage.removeItem("traya_emergency_result");
      return null;
    }
  });
  const [previewImage, setPreviewState] = useState<string | null>(() =>
    sessionStorage.getItem("traya_emergency_preview"),
  );

  const setSession = useCallback((id: string) => {
    sessionStorage.setItem("traya_emergency_session", id);
    setSessionId(id);
  }, []);

  const setResult = useCallback((r: IdentifyResult, preview: string | null) => {
    sessionStorage.setItem("traya_emergency_result", JSON.stringify(r));
    if (preview) sessionStorage.setItem("traya_emergency_preview", preview);
    setResultState(r);
    setPreviewState(preview);
  }, []);

  const setPreview = useCallback((preview: string | null) => {
    if (preview) sessionStorage.setItem("traya_emergency_preview", preview);
    else sessionStorage.removeItem("traya_emergency_preview");
    setPreviewState(preview);
  }, []);

  const clear = useCallback(() => {
    sessionStorage.removeItem("traya_emergency_session");
    sessionStorage.removeItem("traya_emergency_result");
    sessionStorage.removeItem("traya_emergency_preview");
    setSessionId(null);
    setResultState(null);
    setPreviewState(null);
  }, []);

  return (
    <Ctx.Provider
      value={{
        sessionId,
        result,
        previewImage,
        setSession,
        setResult,
        setPreview,
        clear,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useEmergency(): EmergencyState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useEmergency must be used within EmergencyProvider");
  return ctx;
}
