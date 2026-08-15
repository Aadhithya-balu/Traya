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

export const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  HIGH_CONFIDENCE: { label: "High-confidence match", cls: "bg-emerald-500/15 text-emerald-300" },
  REVIEW_REQUIRED: { label: "Review required", cls: "bg-warn-400/15 text-warn-400" },
  LOW_CONFIDENCE: { label: "Low confidence", cls: "bg-amber-500/15 text-amber-300" },
  NO_MATCH: { label: "No match found", cls: "bg-slate-600/20 text-slate-300" },
  MULTIPLE_FACES: { label: "Multiple faces detected", cls: "bg-danger-500/15 text-danger-400" },
  POOR_QUALITY: { label: "Image rejected (poor quality)", cls: "bg-danger-500/15 text-danger-400" },
  NO_FACE: { label: "No face detected", cls: "bg-danger-500/15 text-danger-400" },
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status]?.label ?? status.replace(/_/g, " ").toLowerCase();
}

export function statusClass(status: string): string {
  return STATUS_LABELS[status]?.cls ?? "bg-slate-600/20 text-slate-300";
}

export const DEMO_COORDS = { latitude: 28.6139, longitude: 77.209 }; // Delhi demo default
