export function fmtPct(value?: number | null): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

export function fmtKm(km: number): string {
  return `${km.toFixed(1)} km`;
}

export function fmtTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Status tints, on the semantic ramp only.
 *
 * Three of these previously named classes that do not exist in the theme, so
 * the badge rendered with no background at all. The ramp is the whole palette:
 * `ok` for a confident match, `warn` for review, `danger` for a rejection,
 * `muted` for nothing found.
 */
export const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  HIGH_CONFIDENCE: { label: "High-confidence match", cls: "bg-ok/15 text-ok" },
  REVIEW_REQUIRED: { label: "Review required", cls: "bg-warn/15 text-warn" },
  LOW_CONFIDENCE: { label: "Low confidence", cls: "bg-warn/15 text-warn" },
  NO_MATCH: { label: "No match found", cls: "bg-raised text-muted" },
  MULTIPLE_FACES: { label: "Multiple faces detected", cls: "bg-danger/15 text-danger" },
  POOR_QUALITY: { label: "Image rejected (poor quality)", cls: "bg-danger/15 text-danger" },
  NO_FACE: { label: "No face detected", cls: "bg-danger/15 text-danger" },
};

/** Used for a status string that is not in the table above. */
export const NEUTRAL_STATUS_CLASS = "bg-raised text-muted";

export function statusLabel(status: string): string {
  return STATUS_LABELS[status]?.label ?? status.replace(/_/g, " ").toLowerCase();
}

export function statusClass(status: string): string {
  return STATUS_LABELS[status]?.cls ?? NEUTRAL_STATUS_CLASS;
}

export const DEMO_COORDS = { latitude: 28.6139, longitude: 77.209 }; // Delhi demo default
