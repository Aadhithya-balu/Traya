import { useCallback, useEffect, useState } from "react";

export interface Coords {
  latitude: number;
  longitude: number;
  accuracy?: number | null;
}

export function useGeolocation(enabled = true) {
  const [coords, setCoords] = useState<Coords | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const request = useCallback(() => {
    if (!navigator.geolocation) {
      setError("Geolocation is not supported by this browser.");
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
        setError(err.code === err.PERMISSION_DENIED ? "Location permission denied." : "Could not determine your location.");
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
