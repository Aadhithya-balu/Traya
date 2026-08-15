import type { Quality } from "../api/types";
import { QualityGauge } from "./StatusBadge";

export function QualityPanel({ quality, compact = false }: { quality: Quality | null | undefined; compact?: boolean }) {
  if (!quality) return null;

  if (compact) {
    return (
      <div className="rounded-lg border border-slate-800 bg-ink-900 p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-slate-300">Capture quality</span>
          <span
            className={`badge ${
              quality.usable_for_matching
                ? "bg-emerald-500/15 text-emerald-300"
                : "bg-danger-500/15 text-danger-400"
            }`}
          >
            {quality.usable_for_matching ? "Usable" : "Rejected"}
          </span>
        </div>
        <div className="mt-3 space-y-2">
          <QualityGauge score={quality.image_quality_score} label="Image quality" />
          <QualityGauge score={quality.face_visibility_score} label="Face visibility" />
          <QualityGauge score={quality.occlusion_score} label="Occlusion" />
          <QualityGauge score={quality.blur_score} label="Blur" />
          <QualityGauge score={quality.lighting_score} label="Lighting" />
        </div>
        {quality.reasons.length > 0 && (
          <ul className="mt-3 space-y-1">
            {quality.reasons.map((r) => (
              <li key={r} className="text-xs text-danger-400">
                • {r}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <QualityGauge score={quality.image_quality_score} label="Image quality" />
      <QualityGauge score={quality.face_visibility_score} label="Face visibility" />
      <QualityGauge score={quality.occlusion_score} label="Occlusion" />
      <QualityGauge score={quality.blur_score} label="Blur" />
      <QualityGauge score={quality.lighting_score} label="Lighting" />
      <div className="flex items-center">
        <span
          className={`badge ${
            quality.usable_for_matching
              ? "bg-emerald-500/15 text-emerald-300"
              : "bg-danger-500/15 text-danger-400"
          }`}
        >
          {quality.usable_for_matching ? "Usable for matching" : "Not usable"}
        </span>
      </div>
      {quality.reasons.length > 0 && (
        <div className="col-span-full">
          <ul className="space-y-1">
            {quality.reasons.map((r) => (
              <li key={r} className="text-xs text-danger-400">
                • {r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
