import { statusClass, statusLabel } from "../utils/format";

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${statusClass(status)}`}>{statusLabel(status)}</span>;
}

export function ScoreBar({ value, thresholdHigh, thresholdReview }: { value?: number | null; thresholdHigh?: number; thresholdReview?: number }) {
  if (value == null) return null;
  const pct = Math.max(0, Math.min(100, value * 100));
  const color =
    thresholdHigh != null && value >= thresholdHigh
      ? "bg-emerald-400"
      : thresholdReview != null && value >= thresholdReview
        ? "bg-warn-400"
        : "bg-danger-400";
  return (
    <div className="w-full">
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-slate-400">Confidence</span>
        <span className="font-mono text-slate-200">{Math.round(pct)}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-700">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function QualityGauge({ score, label }: { score?: number | null; label: string }) {
  if (score == null) return null;
  const pct = Math.max(0, Math.min(100, Math.round(score * 100)));
  const color = score >= 0.6 ? "bg-emerald-400" : score >= 0.4 ? "bg-warn-400" : "bg-danger-400";
  return (
    <div>
      <div className="mb-0.5 flex justify-between text-[11px]">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono text-slate-300">{pct}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-700">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
