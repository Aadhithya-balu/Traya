import { createContext, useCallback, useContext, useState } from "react";
import type { ReactNode } from "react";
import { clearSessionToken } from "../api/client";
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

function readStored(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string | null): void {
  try {
    if (value) sessionStorage.setItem(key, value);
    else sessionStorage.removeItem(key);
  } catch {
    /* sessionStorage unavailable (private mode, blocked). The session still
       works in memory for the life of the tab. */
  }
}

/**
 * Emergency Mode is a workflow state, not an authentication state.
 *
 * Nothing in this provider touches the auth tokens or the user. Ending an
 * emergency session must never end a login, which is why `clear` is scoped to
 * exactly the three keys below plus the scoped session credential.
 */
export function EmergencyProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(() =>
    readStored("traya_emergency_session"),
  );
  const [result, setResultState] = useState<IdentifyResult | null>(() => {
    const raw = readStored("traya_emergency_result");
    if (!raw) return null;
    try {
      return JSON.parse(raw) as IdentifyResult;
    } catch {
      writeStored("traya_emergency_result", null);
      return null;
    }
  });
  const [previewImage, setPreviewState] = useState<string | null>(() =>
    readStored("traya_emergency_preview"),
  );

  const setSession = useCallback((id: string) => {
    writeStored("traya_emergency_session", id);
    setSessionId(id);
  }, []);

  const setResult = useCallback((r: IdentifyResult, preview: string | null) => {
    writeStored("traya_emergency_result", JSON.stringify(r));
    if (preview) writeStored("traya_emergency_preview", preview);
    setResultState(r);
    setPreviewState(preview);
  }, []);

  const setPreview = useCallback((preview: string | null) => {
    writeStored("traya_emergency_preview", preview);
    setPreviewState(preview);
  }, []);

  const clear = useCallback(() => {
    writeStored("traya_emergency_session", null);
    writeStored("traya_emergency_result", null);
    writeStored("traya_emergency_preview", null);
    clearSessionToken();
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
