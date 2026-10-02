import { useCallback, useEffect, useState } from "react";
import type { StringKey } from "../i18n";

export interface Coords {
  latitude: number;
  longitude: number;
  accuracy?: number | null;
}

/**
 * Why a location request failed, as a code rather than a sentence.
 *
 * Same reasoning as `CameraErrorCode`: a hook that owns English copy cannot be
 * translated, and this one previously handed a Tamil responder
 * "Location permission denied." in English. The three members are kept apart
 * because they lead to different advice - grant permission, or enter the
 * location by hand - and collapsing them into one message is what makes a
 * responder tap a button that will never work.
 */
export type GeoErrorCode = "unsupported" | "denied" | "unavailable";

/** Exhaustive, so a new code cannot ship without a translation. */
export const GEO_ERROR_KEYS: Record<GeoErrorCode, StringKey> = {
  unsupported: "emergency.geo.error.unsupported",
  denied: "emergency.geo.error.denied",
  unavailable: "emergency.geo.error.unavailable",
};

export function useGeolocation(enabled = true) {
  const [coords, setCoords] = useState<Coords | null>(null);
  const [error, setError] = useState<GeoErrorCode | null>(null);
  const [loading, setLoading] = useState(false);

  const request = useCallback(() => {
    if (!navigator.geolocation) {
      setError("unsupported");
      return;
    }
    setLoading(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
        setLoading(false);
      },
      (err) => {
        // PERMISSION_DENIED is 1 and POSITION_UNAVAILABLE is 2 on the W3C
        // GeolocationError, but they are read off the instance rather than
        // hardcoded, matching the constants the browser actually defined.
        setError(err.code === err.PERMISSION_DENIED ? "denied" : "unavailable");
        setLoading(false);
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }, [enabled]);

  useEffect(() => {
    if (enabled) request();
  }, [enabled, request]);

  return { coords, error, loading, request };
}
